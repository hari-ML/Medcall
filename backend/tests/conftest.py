"""Shared pytest fixtures for MedRecall.

The environment must point at a throwaway SQLite database BEFORE any app
module is imported (conftest.py is collected first by pytest).

Phase 2: the session ``client`` is logged in via phone OTP (the dev mode
echoes the code) as a fixed primary patient, so every pre-existing test
reaches the API authenticated. ``other_headers`` gives isolation tests a
second patient's token.
"""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Throwaway database for the test session — set before app.db import.
_TEMP_DB = Path(os.environ.get("TEMP", str(BACKEND_DIR))) / (
    f"medrecall_pytest_{uuid.uuid4().hex[:8]}.db"
)
os.environ["MEDRECALL_DB"] = str(_TEMP_DB)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import init_db  # noqa: E402
from app.main import app  # noqa: E402

init_db()


# ---------------------------------------------------------------------------
# API client + demo prescription
# ---------------------------------------------------------------------------

#: fixed test identities (normalised E.164-ish; see core.deps.normalize_phone)
PRIMARY_PHONE = "+919812300001"
OTHER_PHONE = "+919812300002"


def otp_login(client, phone: str, full_name: str = "") -> str:
    """Dev-mode phone-OTP login; returns the access token.

    The refresh cookie lands in the client's cookie jar as a side effect.
    """
    response = client.post("/api/auth/otp/request", json={"phone": phone})
    assert response.status_code == 200, response.text
    code = response.json().get("dev_code")
    assert code, "dev_code missing — is MEDRECALL_ENV set to production?"
    payload: dict = {"phone": phone, "code": code}
    if full_name:
        payload["full_name"] = full_name
    response = client.post("/api/auth/otp/verify", json=payload)
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as test_client:
        token = otp_login(test_client, PRIMARY_PHONE, "Primary Test Patient")
        test_client.headers.update({"Authorization": f"Bearer {token}"})
        # keep the session client token-only: drop the refresh cookie so
        # /api/auth/refresh in later tests cannot rotate this session
        test_client.cookies.delete("medrecall_refresh", path="/api/auth")
        yield test_client


@pytest.fixture(scope="session")
def other_patient_token():
    """A second patient's access token (fresh client, isolated cookie jar)."""
    with TestClient(app) as probe:
        return otp_login(probe, OTHER_PHONE, "Other Test Patient")


@pytest.fixture()
def other_headers(other_patient_token):
    return {"Authorization": f"Bearer {other_patient_token}"}


@pytest.fixture()
def demo_prescription(client):
    """A fresh demo prescription per test (3 clear + 1 unclear line)."""
    response = client.post("/api/demo")
    assert response.status_code == 201, response.text
    return response.json()


# ---------------------------------------------------------------------------
# Item dictionaries for the unit-level builders (schedule / pdf / reminders)
# ---------------------------------------------------------------------------


@pytest.fixture()
def clear_item():
    return {
        "id": 1,
        "line_number": 7,
        "medicine": "Paracetamol",
        "strength": "500 mg",
        "form": "tab",
        "frequency": "1-0-1",
        "food_timing": "after",
        "duration_days": 5,
        "as_needed": False,
        "status": "clear",
        "reason": "",
        "source_text": "Tab Paracetamol 500 mg 1-0-1 after food x 5 days",
        "confidence": 95.0,
        "slots": ["morning", "night"],
    }


@pytest.fixture()
def amox_item():
    return {
        "id": 2,
        "line_number": 8,
        "medicine": "Amoxicillin",
        "strength": "250 mg",
        "form": "cap",
        "frequency": "1-1-1",
        "food_timing": None,
        "duration_days": 5,
        "as_needed": False,
        "status": "clear",
        "reason": "",
        "source_text": "Cap Amoxicillin 250 mg 1-1-1 x 5 days",
        "confidence": 95.0,
        "slots": ["morning", "afternoon", "night"],
    }


@pytest.fixture()
def unclear_item():
    return {
        "id": 3,
        "line_number": 9,
        "medicine": "Cetirizine",
        "strength": None,
        "form": "tab",
        "frequency": "0-0-1",
        "food_timing": None,
        "duration_days": None,
        "as_needed": False,
        "status": "unclear",
        "reason": "Dose unreadable",
        "source_text": "Tab Cetirizine ?? mg 0-0-1",
        "confidence": 95.0,
        "slots": ["night"],
    }


@pytest.fixture()
def as_needed_item():
    return {
        "id": 4,
        "line_number": 10,
        "medicine": "Cough Syrup",
        "strength": "5 ml",
        "form": "syrup",
        "frequency": "TDS",
        "food_timing": None,
        "duration_days": None,
        "as_needed": True,
        "status": "clear",
        "reason": "",
        "source_text": "Syp Cough Syrup 5 ml TDS SOS",
        "confidence": 95.0,
        "slots": ["morning", "afternoon", "night"],
    }


@pytest.fixture()
def mixed_items(clear_item, amox_item, unclear_item, as_needed_item):
    """The canonical mixed batch: 3 scheduleable + 1 unclear."""
    return [clear_item, amox_item, unclear_item, as_needed_item]


# ---------------------------------------------------------------------------
# Rendered prescription image (for the real-OCR upload test)
# ---------------------------------------------------------------------------


@pytest.fixture()
def prescription_image(tmp_path):
    """Render the demo prescription at a size Tesseract reads reliably
    (30 px font, generous line spacing — verified against real OCR)."""
    from PIL import Image, ImageDraw, ImageFont

    from app.seed import DEMO_TEXT

    lines = DEMO_TEXT.splitlines()
    line_height = 40
    img = Image.new("RGB", (1150, 60 + line_height * len(lines)), "white")
    draw = ImageDraw.Draw(img)
    font_path = "C:/Windows/Fonts/arial.ttf" if os.name == "nt" else "DejaVuSans.ttf"
    try:
        font = ImageFont.truetype(font_path, 30)
    except OSError:
        font = ImageFont.load_default()
    y = 30
    for line in lines:
        draw.text((30, y), line, fill="black", font=font)
        y += line_height
    path = tmp_path / "rx.png"
    img.save(path, "PNG")
    return path


# ---------------------------------------------------------------------------
# Teardown: remove the throwaway database
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def _cleanup_temp_db():
    yield
    try:
        if _TEMP_DB.name.startswith("medrecall_pytest_"):
            _TEMP_DB.unlink(missing_ok=True)
    except Exception:  # pragma: no cover - best effort cleanup
        pass
