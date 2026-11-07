"""Patient profile + communication-consent endpoints (Phase 2).

All routes require a valid access token (``get_current_patient``) and only
ever touch the caller's own row — there is no patient-id in the path.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..core.deps import get_current_patient
from ..db import get_db
from ..models import ConsentRecord, Patient
from ..schemas import ConsentIn, ConsentOut, PatientOut, PatientUpdateIn
from .serializers import _patient_out

router = APIRouter()

#: the three reminder channels Phase 3+ will check before sending
ALL_CHANNELS: tuple[str, ...] = ("whatsapp", "sms", "voice")


def _consent_list(db: Session, patient_id: int) -> list[ConsentOut]:
    """All three channels, in a stable order (missing row = granted False)."""
    rows = {
        record.channel: record
        for record in db.query(ConsentRecord)
        .filter(ConsentRecord.patient_id == patient_id)
        .all()
    }
    return [
        ConsentOut(
            channel=channel,
            granted=bool(rows[channel].granted) if channel in rows else False,
            updated_at=rows[channel].updated_at if channel in rows else None,
        )
        for channel in ALL_CHANNELS
    ]


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------


@router.get("/api/patients/me", response_model=PatientOut)
def get_me(patient: Patient = Depends(get_current_patient)) -> PatientOut:
    return _patient_out(patient)


@router.patch("/api/patients/me", response_model=PatientOut)
def update_me(
    body: PatientUpdateIn,
    patient: Patient = Depends(get_current_patient),
    db: Session = Depends(get_db),
) -> PatientOut:
    data = body.model_dump(exclude_unset=True)

    if data.get("timezone") is not None:
        tz = str(data["timezone"]).strip()
        try:
            ZoneInfo(tz)
        except (ValueError, KeyError):  # ZoneInfoNotFoundError is a KeyError
            raise HTTPException(
                status_code=422, detail=f"Unknown IANA timezone: {tz!r}"
            ) from None
        patient.timezone = tz

    for field in ("full_name", "preferred_lang", "caregiver_name", "caregiver_phone"):
        if data.get(field) is not None:
            setattr(patient, field, str(data[field]).strip())

    db.commit()
    db.refresh(patient)
    return _patient_out(patient)


# ---------------------------------------------------------------------------
# Communication consent (hard pre-send gate for Phase 3+)
# ---------------------------------------------------------------------------


@router.get("/api/patients/me/consent", response_model=list[ConsentOut])
def get_consent(
    patient: Patient = Depends(get_current_patient),
    db: Session = Depends(get_db),
) -> list[ConsentOut]:
    return _consent_list(db, patient.id)


@router.post("/api/patients/me/consent", response_model=list[ConsentOut])
def set_consent(
    body: ConsentIn,
    patient: Patient = Depends(get_current_patient),
    db: Session = Depends(get_db),
) -> list[ConsentOut]:
    record = (
        db.query(ConsentRecord)
        .filter(
            ConsentRecord.patient_id == patient.id,
            ConsentRecord.channel == body.channel,
        )
        .first()
    )
    if record is None:
        record = ConsentRecord(patient_id=patient.id, channel=body.channel, granted=body.granted)
        db.add(record)
    else:
        record.granted = body.granted
    db.commit()
    return _consent_list(db, patient.id)
