"""Chat models: which ones, in what order, and a start-up check that they still exist.

With LLM_PROVIDER=auto and both keys set, the chain is

    Groq main model  ->  Gemini  ->  Groq fast model

and the tool-calling agents try the fast Groq model first. Each model has its own free quota, so
spreading the calls lets more checks run before any limit is reached. model_status parks a model
that is failing, so the chain skips it until it recovers.

Providers retire models often (Groq shut down llama-3.3-70b-versatile for free keys in August 2026).
check_models() runs at start-up: when a configured model is gone, it picks a current one, logs
what it changed, and the app keeps working.
"""

import asyncio
import logging
import re

import httpx
from langchain_core.language_models import BaseChatModel

from app.config import Settings

log = logging.getLogger(__name__)

GROQ_API = "https://api.groq.com/openai/v1"
GEMINI_API = "https://generativelanguage.googleapis.com/v1beta"

# Preferred replacements, best first. Only models the key can actually use are chosen.
GROQ_MAIN_PREFERENCE = ("openai/gpt-oss-120b", "qwen/qwen3.8-27b", "openai/gpt-oss-20b")
GROQ_FAST_PREFERENCE = ("openai/gpt-oss-20b", "qwen/qwen3.8-27b", "openai/gpt-oss-120b")
_GROQ_NOT_CHAT = re.compile(r"whisper|orpheus|guard|tts|playai|compound|distil", re.I)


# --------------------------------------------------------------------------- constructors

def groq_chat(settings: Settings, model: str, retries: int = 0) -> BaseChatModel:
    from langchain_groq import ChatGroq

    extra: dict = {}
    if "gpt-oss" in model:
        # Short reasoning keeps answers fast and inside the free tokens-per-minute limit.
        extra["reasoning_effort"] = settings.groq_reasoning_effort
    elif "qwen" in model:
        # Keep the model's thinking out of the answer text (raw thinking breaks tool calls).
        extra["reasoning_format"] = "parsed"
    return ChatGroq(model=model, api_key=settings.groq_api_key, temperature=0, max_retries=retries,
                    timeout=settings.llm_timeout_seconds, **extra)


def gemini_chat(settings: Settings, model: str, retries: int = 0) -> BaseChatModel:
    from langchain_google_genai import ChatGoogleGenerativeAI

    extra: dict = {}
    if not model.removeprefix("models/").startswith("gemini-3"):
        # Gemini 3 models use fixed sampling and warn when a temperature is passed.
        extra["temperature"] = 0
    return ChatGoogleGenerativeAI(model=model, api_key=settings.google_api_key, retries=retries,
                                  request_timeout=settings.llm_timeout_seconds, **extra)


# --------------------------------------------------------------------------- the chain

def _chain_spec(settings: Settings) -> list[tuple[str, str]]:
    """[(provider, model)] in the order a normal call tries them."""
    provider = settings.resolved_llm_provider
    if provider == "none":
        return []
    fast = settings.groq_fast_model if settings.groq_fast_model and settings.groq_fast_model != settings.groq_model else None
    groq = [("groq", settings.groq_model)] + ([("groq", fast)] if fast else [])
    gemini = [("gemini", settings.gemini_model)]
    if settings.llm_provider == "auto" and settings.groq_api_key and settings.google_api_key:
        if provider == "groq":
            return [groq[0], *gemini, *groq[1:]]
        return [*gemini, *groq]
    return groq if provider == "groq" else gemini


def build_model_chains(settings: Settings) -> tuple[list[BaseChatModel], list[BaseChatModel]]:
    """(normal order, agent order). Both lists hold the same model objects."""
    spec = _chain_spec(settings)
    retries = 1 if len(spec) == 1 else 0  # with a fallback, moving on is faster than retrying
    makers = {"groq": groq_chat, "gemini": gemini_chat}
    models = [makers[p](settings, m, retries) for p, m in spec]
    agent = list(models)
    fast = settings.groq_fast_model
    for i, (p, m) in enumerate(spec):
        if p == "groq" and m == fast and i:
            agent = [models[i]] + models[:i] + models[i + 1:]
            break
    return models, agent


def build_chat_models(settings: Settings) -> list[BaseChatModel]:
    """Main model first, then the fallbacks. Empty list = rules-only mode."""
    return build_model_chains(settings)[0]


def build_chat_model(settings: Settings) -> BaseChatModel | None:
    models = build_chat_models(settings)
    return models[0] if models else None


def model_label(settings: Settings) -> str:
    spec = _chain_spec(settings)
    return " → ".join(f"{p}/{m}" for p, m in spec) if spec else "none"


def text_of(message) -> str:
    """Plain text from a chat reply. Gemini returns a list of parts (text, signatures), not a string."""
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and part.get("type", "text") == "text" and isinstance(part.get("text"), str):
                parts.append(part["text"])
        return "".join(parts)
    return str(content or "")


# --------------------------------------------------------------------------- start-up check

async def _groq_models(http: httpx.AsyncClient, key: str) -> list[str]:
    r = await http.get(f"{GROQ_API}/models", headers={"Authorization": f"Bearer {key}"})
    r.raise_for_status()
    rows = r.json().get("data", [])
    return [row["id"] for row in rows if row.get("id") and row.get("active", True) and not _GROQ_NOT_CHAT.search(row["id"])]


async def _groq_usable(http: httpx.AsyncClient, key: str, model: str, effort: str) -> bool:
    """A one-word request. Only 'not found' or 'decommissioned' counts as unusable; a rate limit does not."""
    body: dict = {"model": model, "messages": [{"role": "user", "content": "Reply with OK."}], "max_completion_tokens": 16}
    if "gpt-oss" in model:
        body["reasoning_effort"] = effort
    r = await http.post(f"{GROQ_API}/chat/completions", json=body, headers={"Authorization": f"Bearer {key}"})
    if r.status_code == 404:
        return False
    text = r.text.lower()
    return not (r.status_code == 400 and ("decommissioned" in text or "does not exist" in text or "model_not_found" in text))


async def _pick_groq(http, key: str, wanted: str | None, preference: tuple[str, ...], available: list[str],
                     effort: str, avoid: str | None = None, max_probes: int = 3) -> str | None:
    """The wanted model if the key can use it, otherwise the best usable one from the list."""
    order = [wanted] if wanted and wanted in available else []
    order += [m for m in preference if m in available]
    order += [m for m in available if m not in preference]
    tried: list[str] = []
    for model in dict.fromkeys(order):
        if model == avoid:
            continue
        tried.append(model)
        if await _groq_usable(http, key, model, effort):
            return model
        if len(tried) >= max_probes:
            break
    return None


async def _gemini_models(http: httpx.AsyncClient, key: str) -> list[str]:
    r = await http.get(f"{GEMINI_API}/models", params={"pageSize": 1000}, headers={"x-goog-api-key": key})
    r.raise_for_status()
    return [m["name"].removeprefix("models/") for m in r.json().get("models", [])
            if "generateContent" in (m.get("supportedGenerationMethods") or [])]


def _gemini_rank(name: str) -> tuple:
    """Stable flash-lite first, then flash, newest version first. Previews and special models last."""
    version = re.match(r"gemini-(\d+)(?:\.(\d+))?", name)
    major, minor = (int(version.group(1)), int(version.group(2) or 0)) if version else (0, 0)
    special = bool(re.search(r"preview|exp|image|tts|live|thinking|audio|robotics|computer|embedding|learnlm", name))
    tier = 0 if name.endswith("flash-lite") else 1 if name.endswith("flash") else 2
    return (special, tier, -major, -minor, name)


def pick_gemini(wanted: str, available: list[str]) -> str | None:
    if wanted in available:
        return wanted
    choices = sorted((m for m in available if m.startswith("gemini-") and "flash" in m), key=_gemini_rank)
    return choices[0] if choices else None


async def check_models(settings: Settings, timeout: float = 8.0, transport: httpx.AsyncBaseTransport | None = None) -> list[str]:
    """Replace configured models that the keys can no longer use. Returns what was changed.

    Network problems or a rejected key leave the settings as they are; the chain and model_status
    still handle failures at run time.
    """
    if not settings.model_autoselect or settings.resolved_llm_provider == "none":
        return []
    changes: list[str] = []
    async with httpx.AsyncClient(timeout=timeout, transport=transport) as http:

        async def groq() -> None:
            if not settings.groq_api_key:
                return
            try:
                available = await _groq_models(http, settings.groq_api_key)
                effort = settings.groq_reasoning_effort
                main = await _pick_groq(http, settings.groq_api_key, settings.groq_model, GROQ_MAIN_PREFERENCE, available, effort)
                if main and main != settings.groq_model:
                    changes.append(f"GROQ_MODEL {settings.groq_model} is not available to this key; using {main}")
                    settings.groq_model = main
                if settings.groq_fast_model:
                    fast = await _pick_groq(http, settings.groq_api_key, settings.groq_fast_model, GROQ_FAST_PREFERENCE,
                                            available, effort, avoid=settings.groq_model)
                    if fast != settings.groq_fast_model:
                        changes.append(f"GROQ_FAST_MODEL {settings.groq_fast_model} is not available; "
                                       + (f"using {fast}" if fast else "running without it"))
                        settings.groq_fast_model = fast
            except Exception as exc:
                log.warning("Could not check Groq models (%s); keeping %s", _short(exc), settings.groq_model)

        async def gemini() -> None:
            if not settings.google_api_key:
                return
            try:
                available = await _gemini_models(http, settings.google_api_key)
                for field in ("gemini_model", "gemini_vision_model"):
                    wanted = getattr(settings, field)
                    chosen = pick_gemini(wanted, available)
                    if chosen and chosen != wanted:
                        changes.append(f"{field.upper()} {wanted} is not available to this key; using {chosen}")
                        setattr(settings, field, chosen)
            except Exception as exc:
                log.warning("Could not check Gemini models (%s); keeping %s", _short(exc), settings.gemini_model)

        await asyncio.gather(groq(), gemini())
    for change in changes:
        log.warning("Model check: %s. Update .env or the hosting settings to stop this message.", change)
    return changes


def _short(exc: BaseException) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    return type(exc).__name__
