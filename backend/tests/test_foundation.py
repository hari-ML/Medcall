"""Phase 1 foundation tests: settings, request-ID middleware, Alembic baseline."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Settings (app.core.config)
# ---------------------------------------------------------------------------


def test_settings_defaults_match_vite_dev_origins():
    from app.core.config import Settings

    s = Settings(_env_file=None)
    assert s.cors_origins_list == ["http://localhost:5173", "http://127.0.0.1:5173"]
    assert s.log_level.upper() == "INFO"
    assert s.environment == "development"
    assert s.is_production is False


def test_settings_read_environment_overrides(monkeypatch):
    from app.core.config import Settings

    monkeypatch.setenv("MEDRECALL_CORS_ORIGINS", "https://a.example, https://b.example")
    monkeypatch.setenv("MEDRECALL_LOG_LEVEL", "WARNING")
    monkeypatch.setenv("MEDRECALL_ENV", "production")
    s = Settings(_env_file=None)
    assert s.cors_origins_list == ["https://a.example", "https://b.example"]
    assert s.log_level == "WARNING"
    assert s.is_production is True


def test_settings_ignore_unrelated_env():
    from app.core.config import Settings

    # MEDRECALL_DB / POPPLER_PATH / MEDRECALL_API must not blow up Settings.
    s = Settings(_env_file=None)
    assert not hasattr(s, "medrecall_db")


def test_secret_key_env_wins_and_dev_fallback_is_random(monkeypatch):
    from app.core.config import get_secret_key

    monkeypatch.setenv("SECRET_KEY", "configured-key")
    assert get_secret_key() == "configured-key"

    monkeypatch.delenv("SECRET_KEY")
    key1 = get_secret_key()
    assert key1 and len(key1) >= 32  # random per-process dev key


# ---------------------------------------------------------------------------
# Request-ID middleware (app.core.middleware)
# ---------------------------------------------------------------------------


def test_request_id_header_generated(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    rid = res.headers.get("X-Request-ID")
    assert rid and len(rid) == 16


def test_request_id_header_echoed_from_client(client):
    res = client.get("/api/health", headers={"X-Request-ID": "abc123def456"})
    assert res.headers.get("X-Request-ID") == "abc123def456"


def test_request_id_header_on_error_responses(client):
    res = client.get("/api/prescriptions/999999")
    assert res.status_code == 404
    assert res.headers.get("X-Request-ID")


# ---------------------------------------------------------------------------
# Alembic baseline migration
# ---------------------------------------------------------------------------


def test_alembic_upgrade_head_rebuilds_the_live_schema(tmp_path):
    """`alembic upgrade head` on an empty DB == `init_db()` create_all schema."""
    migrated = tmp_path / "migrated.db"
    created = tmp_path / "created.db"

    env = {**os.environ, "MEDRECALL_DB": str(migrated)}
    proc = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, f"alembic upgrade failed:\n{proc.stdout}\n{proc.stderr}"

    # build the same schema through the app's model metadata (same path
    # init_db() uses, bound explicitly to the second file)
    from sqlalchemy import create_engine

    from app.models import Base

    engine = create_engine(f"sqlite:///{created}")
    Base.metadata.create_all(engine)
    engine.dispose()

    def objects(path: Path) -> list[tuple]:
        con = sqlite3.connect(path)
        try:
            return [
                (t, n, " ".join((s or "").split()))
                for t, n, s in con.execute(
                    "SELECT type, name, sql FROM sqlite_master "
                    "WHERE name NOT LIKE 'sqlite_%' AND name != 'alembic_version' "
                    "ORDER BY type, name"
                )
            ]
        finally:
            con.close()

    assert objects(migrated) == objects(created), "alembic schema != init_db schema"

    # and the migration bookkeeping exists
    con = sqlite3.connect(migrated)
    try:
        versions = [row[0] for row in con.execute("SELECT version_num FROM alembic_version")]
    finally:
        con.close()
    assert versions, "alembic_version table not stamped"


def test_alembic_downgrade_to_base_removes_tables(tmp_path):
    db = tmp_path / "down.db"
    env = {**os.environ, "MEDRECALL_DB": str(db)}
    for target in ("head", "base"):
        proc = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade" if target == "head" else "downgrade", target],
            cwd=BACKEND_DIR,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert proc.returncode == 0, f"alembic {target} failed:\n{proc.stderr}"

    con = sqlite3.connect(db)
    try:
        tables = {row[0] for row in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
    finally:
        con.close()
    assert "prescriptions" not in tables and "medicine_items" not in tables
