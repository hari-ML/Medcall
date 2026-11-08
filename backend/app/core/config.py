"""Application settings (pydantic-settings, .env-aware).

Environment variables win over the values in the ``.env`` file; the file is
optional and is looked up at the repo root (template: ``.env.example`` — copy
it to ``.env``) or in ``backend/``. Both are found regardless of the working
directory.

Owned settings (new in Phase 1):
    SECRET_KEY              session/JWT signing key (Phase 2+); generated
                            randomly per process when unset (dev only — a
                            production start WITHOUT a key must fail loudly,
                            enforced in Phase 2 when auth lands)
    MEDRECALL_CORS_ORIGINS  comma-separated allowed origins
    MEDRECALL_LOG_LEVEL     DEBUG | INFO | WARNING | ERROR
    MEDRECALL_ENV           development | production

NOT owned here (unchanged behaviour):
    MEDRECALL_DB            resolved by ``app.db`` (tests point it at a
                            throwaway file before the app is imported)
    POPPLER_PATH            resolved by ``app.ocr``
    MEDRECALL_API           consumed by the Node audit scripts only
"""

from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

#: backend/ — ``app/core/config.py`` -> parents[0]=core, [1]=app, [2]=backend
BACKEND_DIR = Path(__file__).resolve().parents[2]

#: Prescription uploads (mounted at /uploads). Kept here so main.py and the
#: routers resolve the same directory without importing each other.
UPLOAD_DIR = BACKEND_DIR / "uploads"

_DEFAULT_CORS = "http://localhost:5173,http://127.0.0.1:5173"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Absolute paths: read ".env" from the repo root (where .env.example
        # lives) or from backend/, regardless of the process working directory.
        env_file=(
            str(Path(__file__).resolve().parents[3] / ".env"),
            str(Path(__file__).resolve().parents[2] / ".env"),
        ),
        env_file_encoding="utf-8",
        case_sensitive=False,
        populate_by_name=True,  # allow Settings(log_level=...) as well as env vars
        extra="ignore",  # MEDRECALL_DB / POPPLER_PATH / MEDRECALL_API live on
    )

    secret_key: str = Field(default="", alias="SECRET_KEY")
    cors_origins: str = Field(default=_DEFAULT_CORS, alias="MEDRECALL_CORS_ORIGINS")
    log_level: str = Field(default="INFO", alias="MEDRECALL_LOG_LEVEL")
    environment: str = Field(default="development", alias="MEDRECALL_ENV")

    # --- Reminder engine (Phase 3) ----------------------------------------
    #: background dispatcher loop (tests disable it; a cron/CLI tick works too)
    reminder_dispatcher: bool = Field(default=True, alias="MEDRECALL_REMINDER_DISPATCHER")
    reminder_interval_seconds: int = Field(
        default=30, alias="MEDRECALL_REMINDER_INTERVAL_SECONDS"
    )
    #: how far ahead occurrences are generated
    reminder_horizon_hours: int = Field(default=48, alias="MEDRECALL_REMINDER_HORIZON_HOURS")
    #: a due reminder older than this is marked missed, never sent late
    reminder_grace_minutes: int = Field(
        default=120, alias="MEDRECALL_REMINDER_GRACE_MINUTES"
    )
    #: failed delivery attempts before an occurrence is marked failed
    reminder_max_attempts: int = Field(default=3, alias="MEDRECALL_REMINDER_MAX_ATTEMPTS")
    #: exponential backoff for transient provider failures
    reminder_retry_base_seconds: int = Field(
        default=60, alias="MEDRECALL_REMINDER_RETRY_BASE_SECONDS"
    )
    reminder_retry_max_seconds: int = Field(
        default=3600, alias="MEDRECALL_REMINDER_RETRY_MAX_SECONDS"
    )
    #: "fake" (development default) records sends instead of contacting a
    #: provider; production always uses real adapters (unconfigured -> failed)
    channel_mode: str = Field(default="fake", alias="MEDRECALL_CHANNEL_MODE")

    # --- Delivery providers (Phase 4) --------------------------------------
    http_timeout_seconds: float = Field(
        default=10.0, alias="MEDRECALL_HTTP_TIMEOUT_SECONDS"
    )

    # WhatsApp Cloud API (Meta Graph)
    whatsapp_token: str = Field(default="", alias="MEDRECALL_WHATSAPP_TOKEN")
    whatsapp_phone_number_id: str = Field(
        default="", alias="MEDRECALL_WHATSAPP_PHONE_NUMBER_ID"
    )
    whatsapp_api_base: str = Field(
        default="https://graph.facebook.com", alias="MEDRECALL_WHATSAPP_API_BASE"
    )
    whatsapp_api_version: str = Field(
        default="v21.0", alias="MEDRECALL_WHATSAPP_API_VERSION"
    )
    #: approved template name (empty = free-form text; free-form only works
    #: inside WhatsApp's 24-hour customer-service window)
    whatsapp_template_name: str = Field(
        default="", alias="MEDRECALL_WHATSAPP_TEMPLATE_NAME"
    )
    #: language code of the approved template (NOT the patient's language)
    whatsapp_template_lang: str = Field(
        default="en", alias="MEDRECALL_WHATSAPP_TEMPLATE_LANG"
    )

    # Twilio SMS
    sms_account_sid: str = Field(default="", alias="MEDRECALL_SMS_ACCOUNT_SID")
    sms_auth_token: str = Field(default="", alias="MEDRECALL_SMS_AUTH_TOKEN")
    sms_from: str = Field(default="", alias="MEDRECALL_SMS_FROM")

    # Twilio voice
    voice_account_sid: str = Field(default="", alias="MEDRECALL_VOICE_ACCOUNT_SID")
    voice_auth_token: str = Field(default="", alias="MEDRECALL_VOICE_AUTH_TOKEN")
    voice_from: str = Field(default="", alias="MEDRECALL_VOICE_FROM")
    #: patient language -> TwiML <Say language> (provider-dependent TTS)
    voice_lang_map: str = Field(
        default="en:en-US,ta:ta-IN,hi:hi-IN", alias="MEDRECALL_VOICE_LANG_MAP"
    )
    #: Twilio REST base (overridable for tests/proxies)
    twilio_api_base: str = Field(
        default="https://api.twilio.com", alias="MEDRECALL_TWILIO_API_BASE"
    )

    # --- AI care agent (Phase 5) -------------------------------------------
    #: "none" (deterministic answers only, default) or "openai" for any
    #: OpenAI-compatible /chat/completions endpoint. The LLM only rephrases
    #: unmatched questions from verified context; its output is always
    #: validated by app.agent.llm.is_safe_answer before it is returned.
    agent_llm_provider: str = Field(default="none", alias="MEDRECALL_AGENT_LLM_PROVIDER")
    agent_llm_api_key: str = Field(default="", alias="MEDRECALL_AGENT_LLM_API_KEY")
    agent_llm_model: str = Field(default="", alias="MEDRECALL_AGENT_LLM_MODEL")
    agent_llm_base_url: str = Field(
        default="https://api.openai.com/v1", alias="MEDRECALL_AGENT_LLM_BASE_URL"
    )
    agent_llm_timeout_seconds: float = Field(
        default=15.0, alias="MEDRECALL_AGENT_LLM_TIMEOUT_SECONDS"
    )
    agent_llm_max_tokens: int = Field(
        default=300, alias="MEDRECALL_AGENT_LLM_MAX_TOKENS"
    )

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def voice_lang_map_dict(self) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for entry in self.voice_lang_map.split(","):
            if ":" in entry:
                key, value = entry.split(":", 1)
                if key.strip() and value.strip():
                    mapping[key.strip()] = value.strip()
        mapping.setdefault("en", "en-US")
        return mapping

    @property
    def is_production(self) -> bool:
        return self.environment.strip().lower() == "production"

    @property
    def use_fake_channels(self) -> bool:
        return self.channel_mode.strip().lower() == "fake" and not self.is_production


_dev_key: str | None = None


def get_secret_key() -> str:
    """The configured SECRET_KEY, else a random per-process dev key.

    The dev fallback keeps local runs working with zero configuration; the
    key is stable *within* one process so tokens issued mid-session validate.
    """
    global _dev_key
    key = Settings().secret_key.strip()
    if key:
        return key
    if _dev_key is None:
        _dev_key = secrets.token_urlsafe(32)
    return _dev_key


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton (clear with get_settings.cache_clear())."""
    return Settings()
