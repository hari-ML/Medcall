"""Reminder engine endpoints (Phase 3).

* ``POST/DELETE /api/prescriptions/{id}/reminders/enroll`` — start/stop
  reminders for a prescription's verified timetable.
* ``GET /api/reminders/upcoming`` — the next occurrences (patient-local
  times), generating the horizon on demand.
* ``POST /api/reminders/run`` — one manual tick for the caller (dev / app
  "refresh now"; cron-style deployments use ``python -m app.reminders --tick``).
* ``GET /api/reminders/history`` — what was sent / blocked / missed.

Every route is scoped to the authenticated patient. Nothing here can create
a reminder for an unclear or as-needed item — see ``app.reminders``.
"""

from __future__ import annotations

from datetime import timedelta, timezone

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..core.deps import get_current_patient
from ..db import get_db
from ..models import Patient, ReminderOccurrence
from ..reminders import (
    _now,
    deactivate_prescription_schedules,
    generate_occurrences,
    materialize_schedules,
    patient_timezone,
    tick,
)
from ..schemas import EnrollmentOut, OccurrenceOut, ReminderRunOut
from .serializers import _get_owned_prescription

router = APIRouter()

#: statuses that belong in the history feed (pending stays in "upcoming")
_HISTORY_STATUSES = ("sent", "blocked", "failed", "missed", "cancelled")


def _occurrence_out(row: ReminderOccurrence, patient: Patient) -> OccurrenceOut:
    schedule = row.schedule
    item = schedule.item if schedule is not None else None
    local = row.scheduled_at.replace(tzinfo=timezone.utc).astimezone(
        patient_timezone(patient)
    )
    return OccurrenceOut(
        id=row.id,
        item_id=schedule.item_id if schedule is not None else 0,
        medicine=(item.medicine_name if item is not None else ""),
        slot=schedule.slot if schedule is not None else "",
        scheduled_at=row.scheduled_at,
        local_time=local.strftime("%H:%M"),
        status=row.status,
        channel=row.channel,
        body=row.body,
        error=row.error,
        sent_at=row.sent_at,
    )


# ---------------------------------------------------------------------------
# Enrollment (per prescription)
# ---------------------------------------------------------------------------


@router.post(
    "/api/prescriptions/{prescription_id}/reminders/enroll",
    response_model=EnrollmentOut,
)
def enroll_reminders(
    prescription_id: int,
    patient: Patient = Depends(get_current_patient),
    db: Session = Depends(get_db),
) -> EnrollmentOut:
    prescription = _get_owned_prescription(db, prescription_id, patient)
    return EnrollmentOut(**materialize_schedules(db, prescription, patient))


@router.delete("/api/prescriptions/{prescription_id}/reminders/enroll", status_code=204)
def unenroll_reminders(
    prescription_id: int,
    patient: Patient = Depends(get_current_patient),
    db: Session = Depends(get_db),
) -> Response:
    prescription = _get_owned_prescription(db, prescription_id, patient)
    deactivate_prescription_schedules(db, prescription)
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Patient-wide reminder feeds
# ---------------------------------------------------------------------------


@router.get("/api/reminders/upcoming", response_model=list[OccurrenceOut])
def get_upcoming(
    days: int = Query(3, ge=1, le=14),
    patient: Patient = Depends(get_current_patient),
    db: Session = Depends(get_db),
) -> list[OccurrenceOut]:
    """Pending occurrences from (now - grace) to now + ``days``, UTC-sorted."""
    now = _now()
    generate_occurrences(
        db, now, horizon_hours=days * 24, patient_id=patient.id
    )
    grace = timedelta(minutes=get_settings().reminder_grace_minutes)
    rows = (
        db.query(ReminderOccurrence)
        .filter(
            ReminderOccurrence.patient_id == patient.id,
            ReminderOccurrence.status == "pending",
            ReminderOccurrence.scheduled_at >= now - grace,
            ReminderOccurrence.scheduled_at <= now + timedelta(days=days),
        )
        .order_by(ReminderOccurrence.scheduled_at)
        .limit(500)
        .all()
    )
    return [_occurrence_out(row, patient) for row in rows]


@router.post("/api/reminders/run", response_model=ReminderRunOut)
def run_reminders(
    patient: Patient = Depends(get_current_patient),
    db: Session = Depends(get_db),
) -> ReminderRunOut:
    """Generate + dispatch the caller's due reminders once."""
    return ReminderRunOut(**tick(db, patient_id=patient.id))


@router.get("/api/reminders/history", response_model=list[OccurrenceOut])
def get_history(
    limit: int = Query(50, ge=1, le=200),
    patient: Patient = Depends(get_current_patient),
    db: Session = Depends(get_db),
) -> list[OccurrenceOut]:
    rows = (
        db.query(ReminderOccurrence)
        .filter(
            ReminderOccurrence.patient_id == patient.id,
            ReminderOccurrence.status.in_(_HISTORY_STATUSES),
        )
        .order_by(ReminderOccurrence.scheduled_at.desc())
        .limit(limit)
        .all()
    )
    return [_occurrence_out(row, patient) for row in rows]
