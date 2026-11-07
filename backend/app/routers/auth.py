"""Phone-OTP authentication endpoints (Phase 2).

Flow:  POST /api/auth/otp/request  ->  (SMS; dev echoes the code)
       POST /api/auth/otp/verify   ->  access token + refresh cookie

Security notes:
* Codes are stored as HMAC-SHA256, expire in 10 min, max 5 verify attempts,
  max 5 requests per phone per 15 min (429).
* In production a 503 is returned until an SMS provider is wired (Phase 4b) —
  the dev echo never leaks into production.
* The refresh cookie is httpOnly, SameSite=Strict, scoped to /api/auth,
  Secure in production. Rotation consumes the old jti; replaying a consumed
  jti revokes the patient's whole token family (theft response).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import OtpCode, Patient, RefreshToken
from ..schemas import LoginOut, OtpRequestIn, OtpRequestOut, OtpVerifyIn, PatientOut, TokenOut
from ..core.config import get_settings
from ..core.deps import normalize_phone
from ..core.security import (
    OTP_MAX_ATTEMPTS,
    OTP_TTL,
    REFRESH_TOKEN_TTL,
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    generate_otp_code,
    hash_otp_code,
    otp_hashes_match,
)

router = APIRouter()

REFRESH_COOKIE = "medrecall_refresh"

#: at most this many OTP requests per phone within the window
OTP_REQUESTS_PER_WINDOW = 5
OTP_WINDOW = timedelta(minutes=15)


def _utcnow() -> datetime:
    """Naive UTC — SQLite strips tzinfo on round-trip, so every timestamp we
    store and compare must be naive UTC (models.utcnow() behaves the same)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _set_refresh_cookie(response: Response, token: str, max_age: int) -> None:
    settings = get_settings()
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=max_age,
        httponly=True,
        secure=settings.is_production,
        samesite="strict",
        path="/api/auth",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(REFRESH_COOKIE, path="/api/auth")


def _revoke_family(db: Session, patient_id: int) -> None:
    """Consume every un-consumed refresh token for a patient (theft response)."""
    db.query(RefreshToken).filter(
        RefreshToken.patient_id == patient_id,
        RefreshToken.consumed_at.is_(None),
    ).update({"consumed_at": _utcnow()}, synchronize_session=False)


def _login_response(db: Session, patient: Patient) -> Response:
    access_token, expires_in = create_access_token(patient.id)
    refresh_jwt, jti, refresh_max_age = create_refresh_token(patient.id)
    db.add(
        RefreshToken(
            jti=jti,
            patient_id=patient.id,
            expires_at=_utcnow() + REFRESH_TOKEN_TTL,
        )
    )
    db.commit()
    db.refresh(patient)
    payload = LoginOut(
        access_token=access_token,
        expires_in=expires_in,
        patient=PatientOut(
            id=patient.id,
            phone=patient.phone,
            phone_verified=patient.phone_verified,
            full_name=patient.full_name,
            preferred_lang=patient.preferred_lang,
            timezone=patient.timezone,
            caregiver_name=patient.caregiver_name,
            caregiver_phone=patient.caregiver_phone,
            created_at=patient.created_at,
        ),
    )
    response = Response(content=payload.model_dump_json(), media_type="application/json")
    _set_refresh_cookie(response, refresh_jwt, refresh_max_age)
    return response


# ---------------------------------------------------------------------------
# OTP request / verify
# ---------------------------------------------------------------------------


@router.post("/api/auth/otp/request", response_model=OtpRequestOut)
def otp_request(body: OtpRequestIn, db: Session = Depends(get_db)) -> OtpRequestOut | Response:
    phone = normalize_phone(body.phone)

    settings = get_settings()
    if settings.is_production:
        # No SMS provider is wired until Phase 4b — fail loudly, never echo.
        raise HTTPException(
            status_code=503,
            detail="OTP delivery is not configured yet (SMS provider pending).",
        )

    window_start = _utcnow() - OTP_WINDOW
    recent = db.query(func.count(OtpCode.id)).filter(
        OtpCode.phone == phone, OtpCode.created_at > window_start
    ).scalar()
    if recent >= OTP_REQUESTS_PER_WINDOW:
        raise HTTPException(
            status_code=429,
            detail="Too many codes requested for this number. Try again in 15 minutes.",
        )

    code = generate_otp_code()
    db.add(
        OtpCode(
            phone=phone,
            code_hash=hash_otp_code(phone, code),
            expires_at=_utcnow() + OTP_TTL,
        )
    )
    db.commit()

    return OtpRequestOut(
        message="Verification code sent.",
        expires_in=int(OTP_TTL.total_seconds()),
        dev_code=code,
    )


@router.post("/api/auth/otp/verify")
def otp_verify(body: OtpVerifyIn, db: Session = Depends(get_db)) -> Response:
    phone = normalize_phone(body.phone)
    now = _utcnow()

    code_row = (
        db.query(OtpCode)
        .filter(OtpCode.phone == phone, OtpCode.consumed_at.is_(None))
        .order_by(OtpCode.created_at.desc())
        .first()
    )
    if code_row is None or code_row.expires_at <= now:
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired code. Request a new one.",
        )
    if code_row.attempts >= OTP_MAX_ATTEMPTS:
        raise HTTPException(
            status_code=429,
            detail="Too many incorrect attempts. Request a new code.",
        )

    if not otp_hashes_match(code_row.code_hash, phone, body.code):
        code_row.attempts += 1
        db.commit()
        remaining = OTP_MAX_ATTEMPTS - code_row.attempts
        detail = "Incorrect code."
        if remaining <= 2:
            detail = f"Incorrect code. {remaining} attempts remaining."
        raise HTTPException(status_code=400, detail=detail)

    # ---- success: find-or-create the patient, verify the phone, issue tokens
    code_row.consumed_at = now
    patient = db.query(Patient).filter(Patient.phone == phone).first()
    if patient is None:
        patient = Patient(phone=phone, phone_verified=True)
        db.add(patient)
        db.flush()  # obtain patient.id
    if body.full_name and body.full_name.strip():
        patient.full_name = body.full_name.strip()
    patient.phone_verified = True

    return _login_response(db, patient)


# ---------------------------------------------------------------------------
# Refresh / logout
# ---------------------------------------------------------------------------


@router.post("/api/auth/refresh", response_model=TokenOut)
def refresh_tokens(request: Request, db: Session = Depends(get_db)) -> Response:
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="Not logged in.")
    try:
        patient_id, jti = decode_refresh_token(token)
    except TokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token.")

    row = db.get(RefreshToken, jti)
    if row is None or row.patient_id != patient_id:
        raise HTTPException(status_code=401, detail="Session not found.")
    if row.consumed_at is not None:
        # A consumed token was replayed -> assume theft, kill the family.
        _revoke_family(db, patient_id)
        db.commit()
        response = Response(status_code=401, media_type="application/json")
        response.set_cookie(REFRESH_COOKIE, "", max_age=0, path="/api/auth")
        response.body = b'{"detail":"Refresh token reuse detected. All sessions revoked."}'
        return response
    if row.expires_at <= _utcnow():
        db.delete(row)
        db.commit()
        raise HTTPException(status_code=401, detail="Session expired. Please log in again.")

    # rotate
    row.consumed_at = _utcnow()
    access_token, expires_in = create_access_token(patient_id)
    refresh_jwt, new_jti, refresh_max_age = create_refresh_token(patient_id)
    db.add(
        RefreshToken(
            jti=new_jti,
            patient_id=patient_id,
            expires_at=_utcnow() + REFRESH_TOKEN_TTL,
        )
    )
    db.commit()

    body = TokenOut(access_token=access_token, expires_in=expires_in).model_dump_json()
    response = Response(content=body, media_type="application/json")
    _set_refresh_cookie(response, refresh_jwt, refresh_max_age)
    return response


@router.post("/api/auth/logout", status_code=204)
def logout(request: Request, db: Session = Depends(get_db)) -> Response:
    token = request.cookies.get(REFRESH_COOKIE)
    if token:
        try:
            _, jti = decode_refresh_token(token)
        except TokenError:
            jti = None
        if jti:
            row = db.get(RefreshToken, jti)
            if row is not None and row.consumed_at is None:
                row.consumed_at = _utcnow()
                db.commit()
    response = Response(status_code=204)
    _clear_refresh_cookie(response)
    return response
