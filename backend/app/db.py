"""Database engine + session management for MedRecall (SQLite)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .models import Base

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "medrecall.db"


def _resolve_db_url() -> str:
    """MEDRECALL_DB may be a file path or a full SQLAlchemy URL.

    Used by tests to point at a throwaway database.
    """
    override = os.environ.get("MEDRECALL_DB")
    if not override:
        return f"sqlite:///{DEFAULT_DB_PATH}"
    if "://" in override:
        return override
    return f"sqlite:///{Path(override).resolve()}"


engine = create_engine(
    _resolve_db_url(),
    connect_args={"check_same_thread": False},
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def init_db() -> None:
    """Create tables if they do not exist (idempotent)."""
    Base.metadata.create_all(bind=engine)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: one session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
