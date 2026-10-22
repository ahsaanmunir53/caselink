"""Which models are answering right now.

Every model call reports back here. A model that cannot answer is parked for a while, so the next
check goes straight to the next model instead of waiting on a failure again:

* retired model or no access (404, "decommissioned", "does not exist")   parked for 6 hours
* key rejected (401 / 403)                                                parked for 6 hours
* rate limit (429, RESOURCE_EXHAUSTED)    parked for the delay the provider asks for (default 60 s)
* two timeouts or server errors in a row                                  parked for 30 s

A bad request (400, for example a malformed tool call) is about that one request, so it does not
park the model. When every model is parked the check runs on the rules alone, which is quick and
still safe because the rules decide the verdict anyway.

State lives in the process. Each server worker keeps its own, which is fine for a free-tier app.
"""

import re
import time
from dataclasses import dataclass, field

LONG_PARK = 6 * 3600.0
RATE_LIMIT_DEFAULT = 60.0
RATE_LIMIT_MAX = 3600.0
TRANSIENT_PARK = 30.0
TRANSIENT_STRIKES = 2

_RETRY_IN = re.compile(r"(?:retry|try again) in\s+((?:\d+(?:\.\d+)?h)?(?:\d+(?:\.\d+)?m(?!s))?(?:\d+(?:\.\d+)?s)?)", re.I)
_RETRY_DELAY = re.compile(r"retryDelay['\"]?\s*[:=]\s*['\"]?(\d+(?:\.\d+)?)s", re.I)
_UNIT = re.compile(r"(\d+(?:\.\d+)?)([hms])")


@dataclass
class ModelState:
    until: float = 0.0
    kind: str = "ok"  # ok | retired | bad_key | rate_limited | unstable
    reason: str = ""
    strikes: int = 0
    calls: int = 0
    failures: int = 0
    last_ok: float | None = None
    since: float = field(default_factory=time.time)


_states: dict[str, ModelState] = {}


def model_key(model) -> str:
    """Provider and model id, for example 'groq:openai/gpt-oss-120b'."""
    name = str(getattr(model, "model_name", None) or getattr(model, "model", None) or type(model).__name__)
    provider = type(model).__name__.lower()
    if "groq" in provider:
        provider = "groq"
    elif "google" in provider or "gemini" in provider:
        provider = "gemini"
    return f"{provider}:{name.removeprefix('models/')}"


def _state(model) -> ModelState:
    return _states.setdefault(model_key(model), ModelState())


def _seconds(text: str) -> float | None:
    match = _RETRY_DELAY.search(text)
    if match:
        return float(match.group(1))
    match = _RETRY_IN.search(text)
    if match and match.group(1):
        factor = {"h": 3600.0, "m": 60.0, "s": 1.0}
        return sum(float(n) * factor[u] for n, u in _UNIT.findall(match.group(1)))
    return None


def classify(exc: BaseException) -> tuple[str, float]:
    """(kind, seconds to park). kind 'request' means the error belongs to the request, not the model."""
    if isinstance(exc, TimeoutError):
        return "unstable", TRANSIENT_PARK
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    text = f"{type(exc).__name__} {exc}"
    low = text.lower()
    if status == 429 or "429" in low or "rate limit" in low or "resource_exhausted" in low or "ratelimit" in low:
        delay = _seconds(text)
        if delay is None and ("per day" in low or "perday" in low or "tokens per day" in low or "requests per day" in low):
            delay = RATE_LIMIT_MAX
        return "rate_limited", min(max(delay if delay is not None else RATE_LIMIT_DEFAULT, 2.0), RATE_LIMIT_MAX)
    if (status == 404 or "notfound" in low or "model_not_found" in low or "decommissioned" in low
            or "does not exist" in low or "is not found" in low or "not supported for generatecontent" in low):
        return "retired", LONG_PARK
    if (status in (401, 403) or "authentication" in low or "permissiondenied" in low or "invalid api key" in low
            or "api key not valid" in low or "api_key_invalid" in low):
        return "bad_key", LONG_PARK
    if status == 400 or "badrequest" in low or "invalid_request" in low or "tool_use_failed" in low:
        return "request", 0.0
    return "unstable", TRANSIENT_PARK


def note_failure(model, exc: BaseException) -> str:
    """Record a failed call and return the kind of failure."""
    state = _state(model)
    state.calls += 1
    state.failures += 1
    kind, seconds = classify(exc)
    if kind == "request":
        return kind
    if kind == "unstable":
        state.strikes += 1
        if state.strikes < TRANSIENT_STRIKES:
            return kind
    now = time.monotonic()
    state.until = max(state.until, now + seconds)
    state.kind = kind
    state.reason = re.sub(r"\s+", " ", str(exc)).strip()[:200] or type(exc).__name__
    state.since = time.time()
    return kind


def note_success(model) -> None:
    state = _state(model)
    state.calls += 1
    state.until, state.kind, state.reason, state.strikes = 0.0, "ok", "", 0
    state.last_ok = time.time()


def is_parked(model) -> bool:
    return _state(model).until > time.monotonic()


def usable(models: list) -> list:
    """The models that are not parked, in their original order."""
    return [m for m in models if not is_parked(m)]


def seconds_until_free(models: list) -> float:
    """0 when some model can be used now, otherwise how long until the first one is free."""
    if not models or usable(models):
        return 0.0
    return max(0.0, min(_state(m).until for m in models) - time.monotonic())


HINTS = {
    "retired": "The provider no longer serves this model to your key. Set a current model in .env "
               "(GROQ_MODEL / GEMINI_MODEL); the app also picks one by itself on the next start.",
    "bad_key": "The API key was rejected. Check it in .env or in the hosting settings.",
    "rate_limited": "Free quota used up for now. The app uses the next model or the rules until it resets.",
    "unstable": "The model timed out or failed twice in a row; it gets a short break.",
}


def describe(model, detail: bool = True) -> dict:
    """Status for the health endpoints. detail=False leaves out the provider's error text."""
    state = _state(model)
    parked_for = max(0.0, state.until - time.monotonic())
    out = {"model": model_key(model), "status": state.kind if parked_for else "ok"}
    if parked_for:
        out["resting_seconds"] = int(parked_for)
    if detail:
        out.update(calls=state.calls, failures=state.failures)
        if parked_for:
            out.update(reason=state.reason, hint=HINTS.get(state.kind, ""))
    return out


def reset() -> None:
    """Forget everything (used by tests)."""
    _states.clear()
