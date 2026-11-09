"""FastAPI dependencies: current-patient authentication + phone normalisation."""

from __future__ import annotations

import re
import unicodedata

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Patient
from .security import TokenError, decode_access_token, decode_admin_token

_bearer = HTTPBearer(auto_error=False)  # we raise 401 (not the default 403) ourselves

#: loose E.164 check — 7 to 15 digits, optional leading +
_PHONE_RE = re.compile(r"^\+?[0-9]{7,15}$")


def normalize_phone(raw: str) -> str:
    """Normalise a phone number: strip spaces/dashes/dots, keep an optional +."""
    phone = unicodedata.normalize("NFKC", raw or "").strip()
    phone = re.sub(r"[\s\-().]", "", phone)
    if phone.startswith("00"):
        phone = "+" + phone[2:]
    if not _PHONE_RE.match(phone):
        raise HTTPException(status_code=422, detail="Phone number looks invalid.")
    return phone


def get_current_patient(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> Patient:
    """Resolve the Bearer access token to a live patient row (else 401)."""
    if credentials is None or not credentials.credentials.strip():
        raise HTTPException(status_code=401, detail="Authentication required.")
    try:
        patient_id = decode_access_token(credentials.credentials)
    except TokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired token. Please log in again.")
    patient = db.get(Patient, patient_id)
    if patient is None:
        raise HTTPException(status_code=401, detail="Account not found.")
    return patient


def get_current_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    """Resolve the Bearer token to the admin role (else 401).

    Patient access tokens are rejected: ``decode_admin_token`` requires
    ``type=admin``/``sub=admin``, and ``decode_access_token`` requires an
    integer subject — so the two token families cannot be used across the
    patient/admin boundary in either direction.
    """
    if credentials is None or not credentials.credentials.strip():
        raise HTTPException(status_code=401, detail="Authentication required.")
    try:
        decode_admin_token(credentials.credentials)
    except TokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired token. Please log in again.")
    return "admin"
