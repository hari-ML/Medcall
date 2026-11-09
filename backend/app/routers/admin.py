"""Admin dashboard endpoints (Phase 6) — read-only ops console.

* ``POST /api/admin/login`` — username + password from env
  (``MEDRECALL_ADMIN_USERNAME``/``MEDRECALL_ADMIN_PASSWORD``); unconfigured →
  503, so the dashboard fails closed.
* ``GET /api/admin/stats`` — patients/prescriptions/items by status, active
  reminder schedules, occurrences by status, consent by channel.
* ``GET /api/admin/patients`` — paginated cross-patient list.
* ``GET /api/admin/patients/{id}`` — one patient with prescriptions/consent.
* ``GET /api/admin/prescriptions/{id}`` — any prescription (admin view).
* ``GET /api/admin/reminders`` — cross-patient occurrence feed.

Security:
* separate credential and token type (``type=admin``); patient tokens are
  rejected here and admin tokens are rejected on patient routes (401 both
  ways, no privilege bleed);
* this module is strictly read-only — it never writes, confirms, edits,
  enrolls or sends anything; the safety rule is untouched.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload, selectinload

from ..core.config import get_settings
from ..core.deps import get_current_admin
from ..core.security import (
    admin_lockout_active,
    clear_admin_failures,
    create_admin_token,
    record_admin_failure,
    verify_admin_credentials,
)
from ..db import get_db
from ..models import (
    ConsentRecord,
    MedicineItem,
    Patient,
    Prescription,
    ReminderOccurrence,
    ReminderSchedule,
)
from ..schemas import (
    AdminLoginIn,
    AdminLoginOut,
    AdminOccurrenceOut,
    AdminPatientDetailOut,
    AdminPatientOut,
    AdminPatientsOut,
    AdminRemindersOut,
    AdminStatsOut,
    ConsentOut,
    PrescriptionOut,
)
from .serializers import _patient_out, _prescription_out

router = APIRouter()


def _require_configured() -> None:
    if not get_settings().admin_configured:
        raise HTTPException(
            status_code=503,
            detail="Admin access is not configured. Set MEDRECALL_ADMIN_USERNAME "
            "and MEDRECALL_ADMIN_PASSWORD.",
        )


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


@router.post("/api/admin/login", response_model=AdminLoginOut)
def admin_login(payload: AdminLoginIn) -> AdminLoginOut:
    settings = get_settings()
    _require_configured()

    username = payload.username.strip()
    if admin_lockout_active(username):
        raise HTTPException(
            status_code=429,
            detail="Too many failed login attempts. Try again in 15 minutes.",
        )
    if not verify_admin_credentials(
        username,
        payload.password,
        settings.admin_username.strip(),
        settings.admin_password.strip(),
    ):
        record_admin_failure(username)
        raise HTTPException(status_code=401, detail="Invalid credentials.")

    clear_admin_failures(username)
    token, expires_in = create_admin_token()
    return AdminLoginOut(access_token=token, expires_in=expires_in)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


@router.get("/api/admin/stats", response_model=AdminStatsOut)
def admin_stats(
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> AdminStatsOut:
    items_by_status = dict(
        db.query(MedicineItem.status, func.count(MedicineItem.id))
        .group_by(MedicineItem.status)
        .all()
    )
    occurrences_by_status = dict(
        db.query(ReminderOccurrence.status, func.count(ReminderOccurrence.id))
        .group_by(ReminderOccurrence.status)
        .all()
    )
    consent_by_channel = dict(
        db.query(ConsentRecord.channel, func.count(func.distinct(ConsentRecord.patient_id)))
        .filter(ConsentRecord.granted.is_(True))
        .group_by(ConsentRecord.channel)
        .all()
    )
    return AdminStatsOut(
        patients=db.query(func.count(Patient.id)).scalar(),
        prescriptions=db.query(func.count(Prescription.id)).scalar(),
        items_by_status=items_by_status,
        active_reminder_schedules=db.query(func.count(ReminderSchedule.id)).filter(
            ReminderSchedule.active.is_(True)
        ).scalar(),
        occurrences_by_status=occurrences_by_status,
        consent_by_channel=consent_by_channel,
    )


def _patient_summary(db: Session, patient: Patient) -> AdminPatientOut:
    prescription_count = (
        db.query(func.count(Prescription.id))
        .filter(Prescription.patient_id == patient.id)
        .scalar()
    )
    item_count = (
        db.query(func.count(MedicineItem.id))
        .join(Prescription, MedicineItem.prescription_id == Prescription.id)
        .filter(Prescription.patient_id == patient.id)
        .scalar()
    )
    active_schedules = (
        db.query(func.count(ReminderSchedule.id))
        .filter(
            ReminderSchedule.patient_id == patient.id,
            ReminderSchedule.active.is_(True),
        )
        .scalar()
    )
    return AdminPatientOut(
        id=patient.id,
        phone=patient.phone,
        full_name=patient.full_name,
        preferred_lang=patient.preferred_lang,
        timezone=patient.timezone,
        created_at=patient.created_at,
        prescriptions=prescription_count,
        items=item_count,
        active_schedules=active_schedules,
    )


@router.get("/api/admin/patients", response_model=AdminPatientsOut)
def admin_patients(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> AdminPatientsOut:
    total = db.query(func.count(Patient.id)).scalar()
    rows = (
        db.query(Patient)
        .order_by(Patient.created_at.desc(), Patient.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return AdminPatientsOut(
        total=total,
        page=page,
        page_size=page_size,
        items=[_patient_summary(db, patient) for patient in rows],
    )


@router.get("/api/admin/patients/{patient_id}", response_model=AdminPatientDetailOut)
def admin_patient_detail(
    patient_id: int,
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> AdminPatientDetailOut:
    patient = db.get(Patient, patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found.")
    prescriptions = (
        db.query(Prescription)
        .options(selectinload(Prescription.items))
        .filter(Prescription.patient_id == patient_id)
        .order_by(Prescription.created_at.desc(), Prescription.id.desc())
        .all()
    )
    consent = (
        db.query(ConsentRecord)
        .filter(ConsentRecord.patient_id == patient_id)
        .order_by(ConsentRecord.channel)
        .all()
    )
    active_schedules = (
        db.query(func.count(ReminderSchedule.id))
        .filter(
            ReminderSchedule.patient_id == patient_id,
            ReminderSchedule.active.is_(True),
        )
        .scalar()
    )
    return AdminPatientDetailOut(
        patient=_patient_out(patient),
        prescriptions=[_prescription_out(rx) for rx in prescriptions],
        consent=[
            ConsentOut(
                channel=row.channel,
                granted=bool(row.granted),
                updated_at=row.updated_at,
            )
            for row in consent
        ],
        active_schedules=active_schedules,
    )


@router.get("/api/admin/prescriptions/{prescription_id}", response_model=PrescriptionOut)
def admin_prescription_detail(
    prescription_id: int,
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> PrescriptionOut:
    prescription = db.get(Prescription, prescription_id)
    if prescription is None:
        raise HTTPException(status_code=404, detail="Prescription not found.")
    return _prescription_out(prescription)


@router.get("/api/admin/reminders", response_model=AdminRemindersOut)
def admin_reminders(
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> AdminRemindersOut:
    query = (
        db.query(ReminderOccurrence)
        .options(
            joinedload(ReminderOccurrence.schedule)
            .joinedload(ReminderSchedule.patient),
            joinedload(ReminderOccurrence.schedule)
            .joinedload(ReminderSchedule.item),
        )
        .order_by(ReminderOccurrence.scheduled_at.desc(), ReminderOccurrence.id.desc())
    )
    if status:
        query = query.filter(ReminderOccurrence.status == status)
    rows = query.limit(limit).all()
    items = []
    for occurrence in rows:
        schedule = occurrence.schedule
        patient = schedule.patient if schedule is not None else None
        item = schedule.item if schedule is not None else None
        items.append(
            AdminOccurrenceOut(
                id=occurrence.id,
                patient_id=occurrence.patient_id,
                patient_phone=patient.phone if patient is not None else "",
                medicine=item.medicine_name if item is not None else "",
                slot=schedule.slot if schedule is not None else "",
                time_of_day=schedule.time_of_day if schedule is not None else "",
                scheduled_at=occurrence.scheduled_at,
                status=occurrence.status,
                channel=occurrence.channel,
                attempts=occurrence.attempts,
                sent_at=occurrence.sent_at,
            )
        )
    return AdminRemindersOut(limit=limit, items=items)
