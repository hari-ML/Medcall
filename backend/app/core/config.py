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

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment.strip().lower() == "production"


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
