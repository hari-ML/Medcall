"""Phase 6 tests: admin dashboard.

Separate credential, separate token type, read-only endpoints. Patient tokens
must never reach admin routes and admin tokens must never reach patient
routes; an unconfigured admin answers 503 on login and 401 everywhere else.
"""

from __future__ import annotations

import secrets

import pytest
from fastapi.testclient import TestClient

from conftest import PRIMARY_PHONE, otp_login

from app.core.config import get_settings
from app.core.security import reset_admin_failures
from app.main import app
from app.models import Patient


@pytest.fixture(autouse=True)
def _clean_admin_lockout():
    reset_admin_failures()
    yield
    reset_admin_failures()


@pytest.fixture()
def admin_configured(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "admin_username", "admin")
    monkeypatch.setattr(settings, "admin_password", "s3cret-pw")
    return settings


def _fresh_phone() -> str:
    return "+9198" + "".join(secrets.choice("0123456789") for _ in range(7))


def _admin_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _login(client, username="admin", password="s3cret-pw") -> TestClient | int:
    response = client.post(
        "/api/admin/login", json={"username": username, "password": password}
    )
    if response.status_code != 200:
        return response.status_code
    return response.json()["access_token"]


def _new_patient_with_demo():
    """A throwaway patient with one demo prescription.

    Returns (probe_client, profile, demo_id) — mutation tests must use a
    fresh patient so the session-scoped primary patient stays pristine.
    """
    probe = TestClient(app)
    token = otp_login(probe, _fresh_phone(), "Admin Test Patient")
    probe.headers.update({"Authorization": f"Bearer {token}"})
    demo = probe.post("/api/demo").json()
    me = probe.get("/api/patients/me").json()
    return probe, me, demo["id"]


# ---------------------------------------------------------------------------
# Configuration + login
# ---------------------------------------------------------------------------


def test_admin_unconfigured_fails_closed(client):
    response = client.post(
        "/api/admin/login", json={"username": "admin", "password": "x"}
    )
    assert response.status_code == 503
    assert client.get("/api/admin/stats").status_code == 401


def test_login_success(admin_configured, client):
    token = _login(client)
    assert isinstance(token, str) and token
    response = client.post(
        "/api/admin/login", json={"username": "admin", "password": "s3cret-pw"}
    )
    body = response.json()
    assert response.status_code == 200
    assert body["role"] == "admin"
    assert body["token_type"] == "bearer"
    assert body["expires_in"] > 0


def test_login_wrong_credentials(admin_configured, client):
    assert _login(client, password="wrong") == 401
    assert _login(client, username="other", password="s3cret-pw") == 401


def test_login_lockout_after_five_failures(admin_configured, client):
    for _ in range(5):
        assert _login(client, password="wrong") == 401
    # even the correct password is locked out now
    assert _login(client) == 429


# ---------------------------------------------------------------------------
# Token isolation (patient <-> admin)
# ---------------------------------------------------------------------------


def test_admin_routes_reject_patient_token(client, demo_prescription):
    # `client` carries the primary patient's access token
    assert client.get("/api/admin/stats").status_code == 401
    assert client.get("/api/admin/patients").status_code == 401
    assert client.get(f"/api/admin/prescriptions/{demo_prescription['id']}").status_code == 401
    assert client.get("/api/admin/reminders").status_code == 401


def test_patient_routes_reject_admin_token(admin_configured, client):
    token = _login(client)
    assert client.get("/api/patients/me", headers=_admin_headers(token)).status_code == 401
    assert client.get("/api/prescriptions", headers=_admin_headers(token)).status_code == 401
    # the same admin token works on admin routes from a different client
    with TestClient(app) as other:
        assert other.get("/api/admin/stats", headers=_admin_headers(token)).status_code == 200


def test_admin_routes_require_a_token(admin_configured):
    with TestClient(app) as anonymous:
        assert anonymous.get("/api/admin/stats").status_code == 401
        assert anonymous.get("/api/admin/patients").status_code == 401
        assert anonymous.get("/api/admin/reminders").status_code == 401


# ---------------------------------------------------------------------------
# Dashboard data
# ---------------------------------------------------------------------------


def test_stats_reflect_demo_data(admin_configured, client, demo_prescription):
    token = _login(client)
    response = client.get("/api/admin/stats", headers=_admin_headers(token))
    assert response.status_code == 200
    stats = response.json()
    assert stats["patients"] >= 1
    assert stats["prescriptions"] >= 1
    assert stats["items_by_status"]["clear"] >= 3
    assert stats["items_by_status"]["unclear"] >= 1
    assert set(stats["occurrences_by_status"]) <= {
        "pending",
        "sent",
        "blocked",
        "failed",
        "missed",
        "cancelled",
    }


def test_patient_list_is_paginated(admin_configured, client):
    probe, _profile, _demo_id = _new_patient_with_demo()
    try:
        token = _login(client)
        page1 = client.get(
            "/api/admin/patients?page=1&page_size=1", headers=_admin_headers(token)
        ).json()
        assert page1["total"] >= 2
        assert len(page1["items"]) == 1
        page2 = client.get(
            "/api/admin/patients?page=2&page_size=1", headers=_admin_headers(token)
        ).json()
        assert page2["items"][0]["id"] != page1["items"][0]["id"]
        for entry in page1["items"] + page2["items"]:
            assert entry["prescriptions"] >= 1
            assert entry["items"] >= 4
    finally:
        probe.close()


def test_patient_detail(admin_configured, client):
    probe, profile, demo_id = _new_patient_with_demo()
    try:
        token = _login(client)
        assert probe.post(
            "/api/patients/me/consent", json={"channel": "whatsapp", "granted": True}
        ).status_code == 200
        response = client.get(
            f"/api/admin/patients/{profile['id']}", headers=_admin_headers(token)
        )
        assert response.status_code == 200
        detail = response.json()
        assert detail["patient"]["phone"] == profile["phone"]
        assert detail["patient"]["id"] == profile["id"]
        assert any(p["id"] == demo_id for p in detail["prescriptions"])
        whatsapp = next(c for c in detail["consent"] if c["channel"] == "whatsapp")
        assert whatsapp["granted"] is True
        assert detail["active_schedules"] >= 0
    finally:
        probe.close()


def test_patient_detail_404(admin_configured, client):
    token = _login(client)
    assert (
        client.get("/api/admin/patients/999999", headers=_admin_headers(token)).status_code
        == 404
    )


def test_admin_can_view_any_prescription(admin_configured, client):
    probe, _profile, demo_id = _new_patient_with_demo()
    try:
        token = _login(client)
        response = client.get(
            f"/api/admin/prescriptions/{demo_id}", headers=_admin_headers(token)
        )
        assert response.status_code == 200
        body = response.json()
        assert body["id"] == demo_id
        assert len(body["items"]) == 4
    finally:
        probe.close()


def test_admin_prescription_404(admin_configured, client):
    token = _login(client)
    assert (
        client.get("/api/admin/prescriptions/999999", headers=_admin_headers(token)).status_code
        == 404
    )


def test_reminders_feed_is_verified_only(admin_configured, client):
    probe, profile, demo_id = _new_patient_with_demo()
    try:
        token = _login(client)
        headers = _admin_headers(token)

        enroll = probe.post(f"/api/prescriptions/{demo_id}/reminders/enroll")
        assert enroll.status_code == 200, enroll.text
        assert enroll.json()["scheduled_doses"] > 0
        assert probe.post(
            "/api/patients/me/consent", json={"channel": "whatsapp", "granted": True}
        ).status_code == 200
        assert probe.post("/api/reminders/run").status_code == 200

        feed = client.get("/api/admin/reminders?limit=500", headers=headers).json()["items"]
        mine = [entry for entry in feed if entry["patient_id"] == profile["id"]]
        assert mine, "expected occurrences for the enrolled patient"
        for entry in mine:
            # enrollment only ever schedules verified fixed-slot items
            assert entry["medicine"] in {"Paracetamol", "Amoxicillin"}
            assert entry["status"] in {
                "pending",
                "sent",
                "blocked",
                "failed",
                "missed",
                "cancelled",
            }

        chosen = sorted({entry["status"] for entry in feed})[0]
        filtered = client.get(
            f"/api/admin/reminders?status={chosen}&limit=500", headers=headers
        ).json()["items"]
        assert filtered
        assert all(entry["status"] == chosen for entry in filtered)
    finally:
        probe.close()


def test_admin_layer_is_read_only(client, demo_prescription, admin_configured):
    from app.db import SessionLocal
    from app.models import MedicineItem, Prescription

    db = SessionLocal()
    try:
        before = (
            db.query(MedicineItem).count(),
            db.query(Prescription).count(),
        )
    finally:
        db.close()

    token = _login(client)
    headers = _admin_headers(token)
    client.get("/api/admin/stats", headers=headers)
    client.get("/api/admin/patients", headers=headers)
    client.get("/api/admin/reminders", headers=headers)
    patient_id = client.get("/api/patients/me").json()["id"]
    client.get(f"/api/admin/patients/{patient_id}", headers=headers)
    client.get(f"/api/admin/prescriptions/{demo_prescription['id']}", headers=headers)

    db = SessionLocal()
    try:
        after = (
            db.query(MedicineItem).count(),
            db.query(Prescription).count(),
        )
    finally:
        db.close()
    assert before == after
