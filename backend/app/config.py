"""Application settings, read from environment variables or a .env file."""

import logging
import re
from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger(__name__)


class Settings(BaseSettings):
    # Values pasted into a hosting dashboard often carry a trailing newline or space; strip them.
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore",
                                      str_strip_whitespace=True)

    app_env: Literal["development", "production", "test"] = "development"
    allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    public_app_url: str = ""

    # --- Language models (same free chain as Hoshiyar) --------------------
    llm_provider: Literal["auto", "groq", "gemini", "none"] = "auto"
    groq_api_key: str | None = None
    groq_model: str = "openai/gpt-oss-120b"
    groq_fast_model: str | None = "openai/gpt-oss-20b"
    groq_reasoning_effort: Literal["low", "medium", "high"] = "low"
    groq_whisper_model: str = "whisper-large-v3-turbo"
    google_api_key: str | None = None
    gemini_model: str = "gemini-3.5-flash-lite"
    gemini_vision_model: str = "gemini-3.5-flash-lite"
    model_autoselect: bool = True
    llm_timeout_seconds: float = 30.0
    agent_max_tool_rounds: int = 4

    # --- Storage ------------------------------------------------------------
    database_url: str | None = None
    sqlite_path: str = "./caselink.db"
    # Load the synthetic dataset on first start (clearly marked as synthetic everywhere).
    seed_synthetic_data: bool = True

    # --- Linking --------------------------------------------------------------
    # An identifier in more reports than this share is treated as common (a helpline, a big bank)
    # and never links reports on its own.
    hub_share: float = 0.08
    hub_min_reports: int = 12
    name_min_length: int = 5
    similarity_threshold: float = 0.55

    # --- Accounts and safety ---------------------------------------------------
    auth_secret: str = "dev-only-auth-secret-change-me"
    token_hours: int = 12
    admin_email: str | None = None
    admin_password: str | None = None
    # Public demo: one-click logins as demo analysts and a demo supervisor. Data is synthetic.
    demo_mode: bool = True
    # A case must be confirmed by a second person before it can be referred or exported.
    four_eyes: bool = True
    cron_secret: str | None = None
    integration_key: str | None = None
    rate_limit_per_minute: int = 60
    client_ip_header: str = "cf-connecting-ip"
    trusted_proxy_hops: int = 3

    # --- Hoshiyar link (optional) ----------------------------------------------
    hoshiyar_api_url: str = ""
    hoshiyar_integration_key: str | None = None

    telegram_bot_token: str | None = None
    telegram_alert_chat_id: str | None = None

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def resolved_llm_provider(self) -> Literal["groq", "gemini", "none"]:
        if self.llm_provider == "groq":
            return "groq" if self.groq_api_key else "none"
        if self.llm_provider == "gemini":
            return "gemini" if self.google_api_key else "none"
        if self.llm_provider == "none":
            return "none"
        if self.groq_api_key:
            return "groq"
        if self.google_api_key:
            return "gemini"
        return "none"

    @property
    def uses_postgres(self) -> bool:
        return bool(self.database_url)

    @field_validator("database_url")
    @classmethod
    def _clean_database_url(cls, value: str | None) -> str | None:
        """Remove whitespace a paste can leave inside the URL, and use Neon's direct endpoint."""
        if not value:
            return None
        url = re.sub(r"\s+", "", value)
        direct = re.sub(r"(@[^/?#]*?)-pooler(\.[^/?#]*neon\.tech)", r"\1\2", url)
        if direct != url:
            log.warning("DATABASE_URL uses Neon's -pooler host; connecting to the direct host instead.")
        return direct


@lru_cache
def get_settings() -> Settings:
    return Settings()
