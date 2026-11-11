"""Registration + phone-OTP authentication endpoints (Phase 2, Part 3).

Flow::

    POST /api/auth/register      -> create the account, send the first OTP
    POST /api/auth/otp/request   -> send a fresh OTP to a registered phone
    POST /api/auth/otp/verify    -> access token + refresh cookie

The app no longer silently creates an account on first login: signing in
requires a registered, phone-verified patient (404 ``not_registered``
otherwise), and registering an already-verified phone is a 409. Every auth
failure is a machine-readable object detail::

    {"detail": {"code": "invalid_otp", "message": "...", "attempts_left": 3}}

Non-auth routes keep their plain string ``detail`` (the API contract asserts
that), so the frontend can branch on ``detail.code`` only where it matters.

Security notes:
* Codes are stored as HMAC-SHA256, expire in 10 min, max 5 verify attempts,
  max 5 requests per phone per 15 min (429 with ``retry_after`` seconds).
* Codes are dispatched over the patient's preferred channel (WhatsApp or
  SMS), falling back to the other one. In production an unconfigured provider
  is a 503 ``no_channel`` — never a silent success and never a dev echo.
* The refresh cookie is httpOnly, SameSite=Strict, scoped to /api/auth,
  Secure in production. Rotation consumes the old jti; replaying a consumed
  jti revokes the patient's whole token family (theft response).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..channels.base import ChannelDeliveryError, ChannelNotConfigured
from ..channels.registry import adapter_for
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
from ..db import get_db
from ..models import OtpCode, Patient, RefreshToken
from ..schemas import (
    LoginOut,
    OtpRequestIn,
    OtpRequestOut,
    OtpVerifyIn,
    PatientOut,
    RegisterIn,
    TokenOut,
)

logger = logging.getLogger("medrecall.auth")

router = APIRouter()

REFRESH_COOKIE = "medrecall_refresh"

#: at most this many OTP requests per phone within the window
OTP_REQUESTS_PER_WINDOW = 5
OTP_WINDOW = timedelta(minutes=15)

#: OTP-capable channels (voice reminders exist, but a voice call cannot carry
#: a readable one-time code)
OTP_CHANNELS = ("whatsapp", "sms")


def _utcnow() -> datetime:
    """Naive UTC — SQLite strips tzinfo on round-trip, so every timestamp we
    store and compare must be naive UTC (models.utcnow() behaves the same)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def auth_error(
    status_code: int, code: str, message: str, **extra: Any
) -> HTTPException:
    """An HTTPException whose detail is a structured, frontend-readable object."""
    detail: dict[str, Any] = {"code": code, "message": message}
    detail.update(extra)
    return HTTPException(status_code=status_code, detail=detail)


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


def patient_out(patient: Patient) -> PatientOut:
    """One serializer for every endpoint that returns a patient profile."""
    return PatientOut(
        id=patient.id,
        phone=patient.phone,
        phone_verified=patient.phone_verified,
        full_name=patient.full_name,
        preferred_lang=patient.preferred_lang,
        preferred_channel=patient.preferred_channel,
        timezone=patient.timezone,
        caregiver_name=patient.caregiver_name,
        caregiver_phone=patient.caregiver_phone,
        created_at=patient.created_at,
    )


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
        patient=patient_out(patient),
    )
    response = Response(content=payload.model_dump_json(), media_type="application/json")
    _set_refresh_cookie(response, refresh_jwt, refresh_max_age)
    return response


# ---------------------------------------------------------------------------
# OTP issuing + channel dispatch
# ---------------------------------------------------------------------------


def _rate_limit_retry_after(db: Session, phone: str) -> int:
    """Seconds until the oldest request leaves the 15-minute window (0 = ok)."""
    window_start = _utcnow() - OTP_WINDOW
    rows = (
        db.query(OtpCode.created_at)
        .filter(OtpCode.phone == phone, OtpCode.created_at > window_start)
        .order_by(OtpCode.created_at.asc())
        .all()
    )
    if len(rows) < OTP_REQUESTS_PER_WINDOW:
        return 0
    oldest = rows[0][0]
    return max(1, int((oldest + OTP_WINDOW - _utcnow()).total_seconds()))


def _dispatch_otp(patient: Patient, code: str) -> str:
    """Send the code over the preferred channel, then the other one.

    Returns the channel that delivered it, or ``""`` when no provider could.
    The fake development channel counts as delivery (it records the exact
    body), so local runs work with zero credentials; production never gets
    the fake adapter (see ``Settings.effective_channel_provider``).
    """
    preferred = (patient.preferred_channel or "whatsapp").strip().lower()
    if preferred not in OTP_CHANNELS:
        preferred = "whatsapp"
    order = [preferred] + [c for c in OTP_CHANNELS if c != preferred]

    failures: list[str] = []
    for channel in order:
        try:
            adapter = adapter_for(channel)
            adapter.send_otp(patient.phone, code, lang=patient.preferred_lang)
            return channel
        except (ChannelNotConfigured, ChannelDeliveryError, ValueError) as exc:
            failures.append(f"{channel}: {str(exc)[:160]}")
    logger.warning(
        "OTP dispatch failed for %s (tried %s): %s",
        patient.phone,
        ", ".join(order),
        " | ".join(failures) or "no adapter",
    )
    return ""


def _issue_otp(db: Session, patient: Patient) -> OtpRequestOut:
    """Rate-limit, store a fresh HMAC code and dispatch it.

    Raises 429 ``rate_limited`` and 503 ``no_channel`` as structured errors.
    """
    retry_after = _rate_limit_retry_after(db, patient.phone)
    if retry_after:
        raise auth_error(
            429,
            "rate_limited",
            "Too many codes requested for this number. Try again shortly.",
            retry_after=retry_after,
        )

    code = generate_otp_code()
    db.add(
        OtpCode(
            phone=patient.phone,
            code_hash=hash_otp_code(patient.phone, code),
            expires_at=_utcnow() + OTP_TTL,
        )
    )
    db.commit()

    sent_via = _dispatch_otp(patient, code)
    settings = get_settings()
    if not sent_via and settings.is_production:
        # No provider delivered and the dev echo is forbidden: fail loudly.
        raise auth_error(
            503,
            "no_channel",
            "Verification codes cannot be delivered right now. "
            "WhatsApp/SMS is not configured for this deployment.",
        )

    return OtpRequestOut(
        message=(
            "Verification code sent."
            if sent_via
            else "Verification code generated (development mode)."
        ),
        expires_in=int(OTP_TTL.total_seconds()),
        sent_via=sent_via,
        # Dev only: the echo lets local development and the audit scripts log
        # in without a provider. Production never reaches this branch.
        dev_code=None if settings.is_production else code,
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


@router.post("/api/auth/register", response_model=OtpRequestOut, status_code=201)
def register(body: RegisterIn, db: Session = Depends(get_db)) -> Response:
    """Create an account (or reclaim an unverified one) and send the first OTP.

    201 = a new patient row was created. 200 = an existing *unverified* row
    was updated (e.g. the user closed the app before entering the code).
    409 = the phone is already registered and verified — sign in instead.
    """
    phone = normalize_phone(body.phone)
    full_name = body.full_name.strip()
    if not full_name:
        raise HTTPException(status_code=422, detail="Please enter your full name.")

    caregiver_phone = ""
    if body.caregiver_phone and body.caregiver_phone.strip():
        caregiver_phone = normalize_phone(body.caregiver_phone)

    patient = db.query(Patient).filter(Patient.phone == phone).first()
    created = False
    if patient is None:
        patient = Patient(phone=phone, phone_verified=False)
        db.add(patient)
        created = True
    elif patient.phone_verified:
        raise auth_error(
            409,
            "already_registered",
            "This phone number is already registered. Please sign in instead.",
        )

    patient.full_name = full_name
    patient.preferred_lang = body.preferred_lang
    patient.preferred_channel = body.preferred_channel
    if caregiver_phone:
        patient.caregiver_phone = caregiver_phone
    db.flush()

    payload = _issue_otp(db, patient)
    if created:
        return JSONResponse(status_code=201, content=payload.model_dump())
    return JSONResponse(status_code=200, content=payload.model_dump())


# ---------------------------------------------------------------------------
# OTP request / verify
# ---------------------------------------------------------------------------


@router.post("/api/auth/otp/request", response_model=OtpRequestOut)
def otp_request(body: OtpRequestIn, db: Session = Depends(get_db)) -> OtpRequestOut:
    """Send a fresh code to an already-registered phone.

    Unknown numbers are a 404 ``not_registered`` — sign-in never creates an
    account silently (the frontend offers a "create account" switch).
    """
    phone = normalize_phone(body.phone)
    patient = db.query(Patient).filter(Patient.phone == phone).first()
    if patient is None:
        raise auth_error(
            404,
            "not_registered",
            "This number is not registered yet. Create an account to continue.",
        )
    return _issue_otp(db, patient)


@router.post("/api/auth/otp/verify")
def otp_verify(body: OtpVerifyIn, db: Session = Depends(get_db)) -> Response:
    """Verify the latest code, mark the phone verified and issue tokens."""
    phone = normalize_phone(body.phone)
    now = _utcnow()

    patient = db.query(Patient).filter(Patient.phone == phone).first()
    if patient is None:
        raise auth_error(
            404,
            "not_registered",
            "This number is not registered yet. Create an account to continue.",
        )

    code_row = (
        db.query(OtpCode)
        .filter(OtpCode.phone == phone, OtpCode.consumed_at.is_(None))
        .order_by(OtpCode.created_at.desc())
        .first()
    )
    if code_row is None:
        raise auth_error(
            401,
            "invalid_otp",
            "No active code for this number. Request a new one.",
        )
    if code_row.expires_at <= now:
        raise auth_error(
            401,
            "otp_expired",
            "This code has expired. Request a new one.",
        )
    if code_row.attempts >= OTP_MAX_ATTEMPTS:
        raise auth_error(
            429,
            "too_many_attempts",
            "Too many incorrect attempts. Request a new code.",
        )

    if not otp_hashes_match(code_row.code_hash, phone, body.code):
        code_row.attempts += 1
        db.commit()
        remaining = max(OTP_MAX_ATTEMPTS - code_row.attempts, 0)
        raise auth_error(
            401,
            "invalid_otp",
            "Incorrect code. Please check the digits and try again.",
            attempts_left=remaining,
        )

    # ---- success: consume the code, verify the phone, issue tokens
    code_row.consumed_at = now
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
        raise auth_error(401, "no_session", "Not logged in.")
    try:
        patient_id, jti = decode_refresh_token(token)
    except TokenError:
        raise auth_error(
            401, "session_expired", "Invalid or expired refresh token. Please log in again."
        )

    row = db.get(RefreshToken, jti)
    if row is None or row.patient_id != patient_id:
        raise auth_error(401, "session_expired", "Session not found. Please log in again.")
    if row.consumed_at is not None:
        # A consumed token was replayed -> assume theft, kill the family.
        _revoke_family(db, patient_id)
        db.commit()
        response = Response(status_code=401, media_type="application/json")
        response.set_cookie(REFRESH_COOKIE, "", max_age=0, path="/api/auth")
        response.body = (
            b'{"detail":{"code":"session_reuse","message":'
            b'"Refresh token reuse detected. All sessions revoked."}}'
        )
        return response
    if row.expires_at <= _utcnow():
        db.delete(row)
        db.commit()
        raise auth_error(
            401, "session_expired", "Session expired. Please log in again."
        )

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
