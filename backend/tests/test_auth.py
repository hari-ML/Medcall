"""Phase 2 auth tests: phone-OTP login, JWT access tokens, refresh rotation
and replay detection, profile, communication consent, and patient-data
isolation (someone else's records are a 404, never a 403/leak)."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from conftest import PRIMARY_PHONE, otp_login, register_patient

from app.core.config import get_settings
from app.db import SessionLocal
from app.main import app
from app.models import OtpCode, Patient, Prescription


def _fresh_phone() -> str:
    """A unique 11-digit phone so rate-limit budgets never collide."""
    return "+9198" + "".join(secrets.choice("0123456789") for _ in range(7))


def _wrong_code(code: str) -> str:
    return ("0" if code[0] != "0" else "1") + code[1:]


def _request_code(client, phone: str) -> str:
    """Register the phone (the sign-in flow requires an account) and return
    the dev-echoed OTP code."""
    return register_patient(client, phone)["dev_code"]


# ---------------------------------------------------------------------------
# Registration + OTP request / verify
# ---------------------------------------------------------------------------


def test_register_creates_account_and_returns_dev_code():
    client = TestClient(app)
    phone = _fresh_phone()
    response = client.post(
        "/api/auth/register",
        json={
            "phone": phone,
            "full_name": "New Patient",
            "preferred_lang": "ta",
            "preferred_channel": "sms",
            "caregiver_phone": "+919999999999",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["dev_code"].isdigit() and len(body["dev_code"]) == 6
    assert body["expires_in"] == 600
    assert body["sent_via"] == "sms"
    assert body["message"]

    db = SessionLocal()
    try:
        patient = db.query(Patient).filter(Patient.phone == phone).first()
        assert patient is not None
        assert patient.phone_verified is False
        assert patient.full_name == "New Patient"
        assert patient.preferred_lang == "ta"
        assert patient.preferred_channel == "sms"
        assert patient.caregiver_phone == "+919999999999"
    finally:
        db.close()


def test_register_duplicate_verified_phone_is_409():
    client = TestClient(app)
    phone = _fresh_phone()
    otp_login(client, phone, "Already Verified")
    response = client.post(
        "/api/auth/register",
        json={"phone": phone, "full_name": "Duplicate"},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "already_registered"


def test_register_reclaims_an_unverified_account():
    client = TestClient(app)
    phone = _fresh_phone()
    first = register_patient(client, phone, "First Name")
    assert first["dev_code"]
    second = client.post(
        "/api/auth/register",
        json={
            "phone": phone,
            "full_name": "Corrected Name",
            "preferred_lang": "hi",
            "preferred_channel": "whatsapp",
        },
    )
    assert second.status_code == 200, second.text
    assert second.json()["dev_code"]
    code = second.json()["dev_code"]
    verified = client.post("/api/auth/otp/verify", json={"phone": phone, "code": code})
    assert verified.status_code == 200
    assert verified.json()["patient"]["full_name"] == "Corrected Name"
    assert verified.json()["patient"]["preferred_lang"] == "hi"


def test_sign_in_with_unregistered_phone_is_404():
    client = TestClient(app)
    response = client.post(
        "/api/auth/otp/request", json={"phone": _fresh_phone()}
    )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "not_registered"


def test_otp_request_returns_dev_code_in_development():
    client = TestClient(app)
    phone = _fresh_phone()
    register_patient(client, phone)
    response = client.post("/api/auth/otp/request", json={"phone": phone})
    assert response.status_code == 200
    body = response.json()
    assert body["dev_code"].isdigit() and len(body["dev_code"]) == 6
    assert body["expires_in"] == 600
    assert body["message"]


def test_otp_request_rejects_invalid_phone():
    client = TestClient(app)
    assert client.post("/api/auth/otp/request", json={"phone": "12"}).status_code == 422
    assert client.post("/api/auth/otp/request", json={"phone": "call-me-maybe"}).status_code == 422


def test_otp_verify_wrong_code_is_rejected():
    client = TestClient(app)
    phone = _fresh_phone()
    code = _request_code(client, phone)
    response = client.post("/api/auth/otp/verify", json={"phone": phone, "code": _wrong_code(code)})
    assert response.status_code == 401
    detail = response.json()["detail"]
    assert detail["code"] == "invalid_otp"
    assert detail["attempts_left"] == 4


def test_otp_verify_creates_patient_and_issues_tokens():
    client = TestClient(app)
    phone = _fresh_phone()
    code = _request_code(client, phone)
    response = client.post(
        "/api/auth/otp/verify", json={"phone": phone, "code": code, "full_name": "Otp Tester"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 900  # 15-minute access token
    assert body["patient"]["phone"] == phone
    assert body["patient"]["phone_verified"] is True
    assert body["patient"]["full_name"] == "Otp Tester"

    cookie = response.headers.get("set-cookie", "")
    assert "medrecall_refresh=" in cookie
    assert "httponly" in cookie.lower()
    assert "path=/api/auth" in cookie.lower()
    assert "samesite=strict" in cookie.lower()

    # and the access token authorises a real API call
    me = client.get("/api/patients/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    assert me.json()["id"] == body["patient"]["id"]


def test_otp_verify_expired_code_is_rejected():
    client = TestClient(app)
    phone = _fresh_phone()
    code = _request_code(client, phone)
    db = SessionLocal()
    try:
        row = db.query(OtpCode).filter(OtpCode.phone == phone).first()
        assert row is not None
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    finally:
        db.close()
    response = client.post("/api/auth/otp/verify", json={"phone": phone, "code": code})
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "otp_expired"


def test_otp_five_wrong_attempts_lock_the_code():
    client = TestClient(app)
    phone = _fresh_phone()
    code = _request_code(client, phone)
    wrong = _wrong_code(code)
    for _ in range(5):
        response = client.post("/api/auth/otp/verify", json={"phone": phone, "code": wrong})
        assert response.status_code == 401
        assert response.json()["detail"]["code"] == "invalid_otp"
    response = client.post("/api/auth/otp/verify", json={"phone": phone, "code": wrong})
    assert response.status_code == 429
    assert response.json()["detail"]["code"] == "too_many_attempts"


def test_otp_request_rate_limited_per_phone():
    client = TestClient(app)
    phone = _fresh_phone()
    register_patient(client, phone)  # counts as the first request
    for _ in range(4):
        assert client.post("/api/auth/otp/request", json={"phone": phone}).status_code == 200
    response = client.post("/api/auth/otp/request", json={"phone": phone})
    assert response.status_code == 429
    detail = response.json()["detail"]
    assert detail["code"] == "rate_limited"
    assert detail["retry_after"] >= 1


def test_otp_delivery_refused_in_production(monkeypatch):
    # Register in development first so the phone exists, then switch to
    # production: the dev echo is forbidden and no real provider is set, so
    # the send is a 503 no_channel — never a silent success.
    client = TestClient(app)
    phone = _fresh_phone()
    register_patient(client, phone)
    monkeypatch.setenv("MEDRECALL_ENV", "production")
    get_settings.cache_clear()
    try:
        response = client.post("/api/auth/otp/request", json={"phone": phone})
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "no_channel"
        assert "dev_code" not in response.json()
    finally:
        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Access tokens
# ---------------------------------------------------------------------------


def test_missing_or_garbage_token_is_401():
    client = TestClient(app)
    assert client.get("/api/prescriptions").status_code == 401
    assert client.get("/api/prescriptions", headers={"Authorization": "Bearer not-a-jwt"}).status_code == 401
    assert client.post("/api/demo").status_code == 401


def test_refresh_token_cannot_be_used_as_access_token():
    client = TestClient(app)
    otp_login(client, _fresh_phone())
    refresh = client.cookies["medrecall_refresh"]
    response = client.get("/api/patients/me", headers={"Authorization": f"Bearer {refresh}"})
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Refresh rotation + replay detection
# ---------------------------------------------------------------------------


def test_refresh_rotates_tokens():
    client = TestClient(app)
    access1 = otp_login(client, _fresh_phone())
    old = client.cookies["medrecall_refresh"]
    response = client.post("/api/auth/refresh")
    assert response.status_code == 200
    body = response.json()
    assert body["access_token"] and body["access_token"] != access1
    assert body["token_type"] == "bearer"
    new = client.cookies["medrecall_refresh"]
    assert new and new != old
    me = client.get("/api/patients/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200


def test_refresh_replay_revokes_the_whole_family():
    client = TestClient(app)
    otp_login(client, _fresh_phone())
    first = client.cookies["medrecall_refresh"]
    assert client.post("/api/auth/refresh").status_code == 200
    current = client.cookies["medrecall_refresh"]

    # replay the already-consumed first token -> theft response
    client.cookies.set("medrecall_refresh", first, path="/api/auth")
    replay = client.post("/api/auth/refresh")
    assert replay.status_code == 401
    assert replay.json()["detail"]["code"] == "session_reuse"
    assert "reuse" in replay.json()["detail"]["message"].lower()

    # the whole family is now dead, including the newest token
    client.cookies.set("medrecall_refresh", current, path="/api/auth")
    assert client.post("/api/auth/refresh").status_code == 401


def test_refresh_without_cookie_is_401():
    client = TestClient(app)
    assert client.post("/api/auth/refresh").status_code == 401


def test_logout_consumes_the_session():
    client = TestClient(app)
    otp_login(client, _fresh_phone())
    assert client.post("/api/auth/logout").status_code == 204
    assert client.post("/api/auth/refresh").status_code == 401


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------


def test_profile_get_and_patch(client):
    me = client.get("/api/patients/me")
    assert me.status_code == 200
    assert me.json()["phone"] == PRIMARY_PHONE

    response = client.patch(
        "/api/patients/me",
        json={
            "full_name": "Updated Name",
            "preferred_lang": "ta",
            "timezone": "Asia/Singapore",
            "caregiver_name": "Nurse Anand",
            "caregiver_phone": "+919999999999",
        },
    )
    assert response.status_code == 200
    updated = response.json()
    assert updated["full_name"] == "Updated Name"
    assert updated["preferred_lang"] == "ta"
    assert updated["timezone"] == "Asia/Singapore"
    assert updated["caregiver_name"] == "Nurse Anand"
    assert client.get("/api/patients/me").json()["timezone"] == "Asia/Singapore"


def test_profile_patch_rejects_unknown_timezone(client):
    assert client.patch("/api/patients/me", json={"timezone": "Mars/Olympus"}).status_code == 422


def test_profile_patch_rejects_unknown_language(client):
    assert client.patch("/api/patients/me", json={"preferred_lang": "fr"}).status_code == 422


# ---------------------------------------------------------------------------
# Communication consent
# ---------------------------------------------------------------------------


def test_consent_defaults_to_deny(client):
    response = client.get("/api/patients/me/consent")
    assert response.status_code == 200
    entries = {entry["channel"]: entry for entry in response.json()}
    assert set(entries) == {"whatsapp", "sms", "voice"}
    assert all(not entry["granted"] for entry in entries.values())


def test_consent_grant_and_revoke(client):
    assert (
        client.post("/api/patients/me/consent", json={"channel": "whatsapp", "granted": True}).status_code
        == 200
    )
    entries = {e["channel"]: e for e in client.get("/api/patients/me/consent").json()}
    assert entries["whatsapp"]["granted"] is True
    assert entries["sms"]["granted"] is False

    client.post("/api/patients/me/consent", json={"channel": "whatsapp", "granted": False})
    entries = {e["channel"]: e for e in client.get("/api/patients/me/consent").json()}
    assert entries["whatsapp"]["granted"] is False


def test_consent_rejects_unknown_channel(client):
    response = client.post("/api/patients/me/consent", json={"channel": "email", "granted": True})
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Patient-data isolation
# ---------------------------------------------------------------------------


def test_other_patient_cannot_touch_records(client, other_headers):
    demo = client.post("/api/demo").json()
    item_id = demo["items"][0]["id"]
    pid = demo["id"]
    assert client.get(f"/api/prescriptions/{pid}", headers=other_headers).status_code == 404
    assert (
        client.patch(
            f"/api/prescriptions/{pid}/items/{item_id}", json={"action": "confirm"}, headers=other_headers
        ).status_code
        == 404
    )
    assert client.post(f"/api/prescriptions/{pid}/schedule", headers=other_headers).status_code == 404
    assert client.get(f"/api/prescriptions/{pid}/timetable.pdf", headers=other_headers).status_code == 404
    assert client.get(f"/api/prescriptions/{pid}/reminders", headers=other_headers).status_code == 404
    # ...while the owner still can
    assert client.get(f"/api/prescriptions/{pid}").status_code == 200


def test_list_prescriptions_returns_only_own(client, other_headers):
    first_id = client.post("/api/demo").json()["id"]
    second_id = client.post("/api/demo").json()["id"]
    b_id = client.post("/api/demo", headers=other_headers).json()["id"]

    mine = client.get("/api/prescriptions").json()
    ids = [p["id"] for p in mine]
    assert first_id in ids and second_id in ids
    assert b_id not in ids
    assert ids.index(second_id) < ids.index(first_id)  # newest first

    theirs = client.get("/api/prescriptions", headers=other_headers).json()
    assert [p["id"] for p in theirs] == [b_id]


def test_orphan_prescription_is_invisible_to_everyone(client, other_headers):
    """A row with patient_id NULL (pre-account legacy data) shows up nowhere."""
    db = SessionLocal()
    try:
        orphan = Prescription(
            image_filename="", original_filename="orphan.png", content_type="image/png", lang="en"
        )
        db.add(orphan)
        db.commit()
        orphan_id = orphan.id
    finally:
        db.close()

    assert client.get(f"/api/prescriptions/{orphan_id}").status_code == 404
    assert client.get(f"/api/prescriptions/{orphan_id}", headers=other_headers).status_code == 404
    assert orphan_id not in [p["id"] for p in client.get("/api/prescriptions").json()]


# ---------------------------------------------------------------------------
# Signed image URLs
# ---------------------------------------------------------------------------


def test_image_url_is_signed_and_served(client):
    demo = client.post("/api/demo").json()
    url = demo["image_url"]
    assert url.startswith("/uploads/")
    assert "exp=" in url and "sig=" in url
    response = client.get(url)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/")


def test_unsigned_or_forged_image_links_are_rejected(client):
    demo = client.post("/api/demo").json()
    plain = demo["image_url"].split("?")[0]
    assert client.get(plain).status_code == 403
    forged = demo["image_url"].rsplit("sig=", 1)[0] + "sig=" + "0" * 64
    assert client.get(forged).status_code == 403
    unknown = client.get("/uploads/does_not_exist.png?exp=9999999999&sig=" + "0" * 64)
    assert unknown.status_code == 404
