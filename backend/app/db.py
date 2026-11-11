"""Database engine + session management for MedRecall (SQLite)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from .models import Base

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "medrecall.db"

#: Columns added after their table first shipped (Part 3 / registration).
#: ``create_all`` never ALTERs an existing table, and a dev database created
#: before alembic was wired has no ``alembic_version`` — this keeps those
#: databases runnable. Alembic-managed databases receive the same columns
#: from the additive migration, so the check is a no-op there.
_ADDITIVE_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "patients": [
        ("preferred_channel", "VARCHAR(16) DEFAULT 'whatsapp' NOT NULL"),
    ],
    "reminder_occurrences": [
        ("patient_action", "VARCHAR(16) DEFAULT '' NOT NULL"),
        ("patient_action_at", "DATETIME"),
    ],
}


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


def _ensure_additive_columns() -> None:
    """ADD COLUMN for known post-launch columns missing from existing tables."""
    with engine.begin() as conn:
        inspector = inspect(conn)
        for table, columns in _ADDITIVE_COLUMNS.items():
            if table not in inspector.get_table_names():
                continue  # create_all just built it with the model's columns
            existing = {col["name"] for col in inspector.get_columns(table)}
            for name, ddl in columns:
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


def init_db() -> None:
    """Create tables if they do not exist (idempotent) and backfill columns."""
    Base.metadata.create_all(bind=engine)
    _ensure_additive_columns()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: one session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
