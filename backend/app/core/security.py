"""Authentication primitives: JWT access/refresh tokens + OTP code handling.

Security properties:
* Access tokens: HS256 JWT, 15-minute TTL, ``type=access``. The frontend keeps
  these in memory only (Phase 7) — never in localStorage.
* Refresh tokens: HS256 JWT, 30-day TTL, ``type=refresh`` + a ``jti`` that is
  recorded in the ``refresh_tokens`` table. Rotation consumes the old jti;
  presenting a consumed jti again means the token family was stolen, so the
  patient's entire family is revoked.
* OTP codes: 6 random digits, stored only as HMAC-SHA256(secret, phone:code),
  10-minute expiry, max 5 attempts per code.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import jwt

from .config import get_secret_key

ALGORITHM = "HS256"
ACCESS_TOKEN_TTL = timedelta(minutes=15)
REFRESH_TOKEN_TTL = timedelta(days=30)
ADMIN_TOKEN_TTL = timedelta(hours=8)
OTP_TTL = timedelta(minutes=10)
OTP_MAX_ATTEMPTS = 5


class TokenError(Exception):
    """Raised when a token is missing, malformed, expired or the wrong type."""


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_access_token(patient_id: int) -> tuple[str, int]:
    """Returns (token, expires_in_seconds)."""
    now = _now()
    exp = now + ACCESS_TOKEN_TTL
    payload = {
        "sub": str(patient_id),
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, get_secret_key(), algorithm=ALGORITHM), int(ACCESS_TOKEN_TTL.total_seconds())


def decode_access_token(token: str) -> int:
    """Returns the patient id, or raises :class:`TokenError`."""
    try:
        payload = jwt.decode(token, get_secret_key(), algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("Token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("Invalid token") from exc
    if payload.get("type") != "access":
        raise TokenError("Wrong token type")
    try:
        return int(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise TokenError("Invalid token subject") from exc


def create_refresh_token(patient_id: int) -> tuple[str, str, int]:
    """Returns (token, jti, expires_in_seconds)."""
    now = _now()
    exp = now + REFRESH_TOKEN_TTL
    jti = uuid.uuid4().hex
    payload = {
        "sub": str(patient_id),
        "type": "refresh",
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "jti": jti,
    }
    token = jwt.encode(payload, get_secret_key(), algorithm=ALGORITHM)
    return token, jti, int(REFRESH_TOKEN_TTL.total_seconds())


def decode_refresh_token(token: str) -> tuple[int, str]:
    """Returns (patient_id, jti), or raises :class:`TokenError`."""
    try:
        payload = jwt.decode(token, get_secret_key(), algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("Refresh token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("Invalid refresh token") from exc
    if payload.get("type") != "refresh":
        raise TokenError("Wrong token type")
    try:
        return int(payload["sub"]), str(payload["jti"])
    except (KeyError, ValueError) as exc:
        raise TokenError("Invalid refresh token") from exc


# ---------------------------------------------------------------------------
# Admin (Phase 6): separate credential, separate token type
# ---------------------------------------------------------------------------


def create_admin_token() -> tuple[str, int]:
    """Admin access token (no refresh cookie): 8 h TTL, ``type=admin``."""
    now = _now()
    exp = now + ADMIN_TOKEN_TTL
    payload = {
        "sub": "admin",
        "type": "admin",
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, get_secret_key(), algorithm=ALGORITHM), int(
        ADMIN_TOKEN_TTL.total_seconds()
    )


def decode_admin_token(token: str) -> None:
    """Validate an admin token. Raises :class:`TokenError` on any mismatch —
    including patient/refresh tokens presented to admin routes."""
    try:
        payload = jwt.decode(token, get_secret_key(), algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("Admin token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("Invalid admin token") from exc
    if payload.get("type") != "admin" or payload.get("sub") != "admin":
        raise TokenError("Wrong token type")


def _admin_hash(username: str, password: str) -> str:
    return hmac.new(
        get_secret_key().encode(), f"admin:{username}:{password}".encode(), hashlib.sha256
    ).hexdigest()


def verify_admin_credentials(username: str, password: str, configured_username: str, configured_password: str) -> bool:
    """Constant-time check against the env-configured admin account.

    Always hashes both sides (even when credentials are empty) so response
    timing does not reveal which of username/password was wrong.
    """
    expected = _admin_hash(configured_username, configured_password)
    return hmac.compare_digest(_admin_hash(username, password), expected)


#: failed-admin-login lockout: N failures per window (in-memory, per process)
ADMIN_MAX_FAILURES = 5
ADMIN_FAILURE_WINDOW = timedelta(minutes=15)

_admin_failures: dict[str, list[datetime]] = {}


def admin_lockout_active(username: str) -> bool:
    window_start = _now() - ADMIN_FAILURE_WINDOW
    stamps = [s for s in _admin_failures.get(username, []) if s > window_start]
    _admin_failures[username] = stamps
    return len(stamps) >= ADMIN_MAX_FAILURES


def record_admin_failure(username: str) -> None:
    _admin_failures.setdefault(username, []).append(_now())


def clear_admin_failures(username: str) -> None:
    _admin_failures.pop(username, None)


def reset_admin_failures() -> None:
    """Test helper: clear the in-memory lockout table."""
    _admin_failures.clear()


# ---------------------------------------------------------------------------
# OTP codes
# ---------------------------------------------------------------------------


def generate_otp_code() -> str:
    """Six random digits (secrets-based, not predictable)."""
    return "".join(secrets.choice("0123456789") for _ in range(6))


def hash_otp_code(phone: str, code: str) -> str:
    """HMAC-SHA256 keyed by the app secret — codes are never stored in clear."""
    return hmac.new(get_secret_key().encode(), f"{phone}:{code}".encode(), hashlib.sha256).hexdigest()


def otp_hashes_match(stored_hash: str, phone: str, code: str) -> bool:
    """Constant-time comparison of an entered code against the stored hash."""
    return hmac.compare_digest(hash_otp_code(phone, code), stored_hash)


# ---------------------------------------------------------------------------
# Signed, expiring image URLs (Phase 2: the public /uploads mount is gone)
# ---------------------------------------------------------------------------

#: how long a signed /uploads/ URL stays valid
IMAGE_URL_TTL = timedelta(minutes=15)


def sign_image_url(prescription_id: int, filename: str, exp: int) -> str:
    """HMAC-SHA256 over ``"<prescription_id>:<filename>:<exp>"``.

    Binding the signature to the prescription row (not just the filename)
    means a URL cannot be reused across rows that share a file name, and a
    forged ``exp`` changes the payload and fails verification.
    """
    payload = f"{prescription_id}:{filename}:{exp}".encode()
    return hmac.new(get_secret_key().encode(), payload, hashlib.sha256).hexdigest()


def signed_image_url(prescription) -> str:
    """A short-lived signed URL for ``<img src>``: ``/uploads/<file>?exp=..&sig=..``"""
    exp = int(_now().timestamp()) + int(IMAGE_URL_TTL.total_seconds())
    return (
        f"/uploads/{prescription.image_filename}"
        f"?exp={exp}&sig={sign_image_url(prescription.id, prescription.image_filename, exp)}"
    )
