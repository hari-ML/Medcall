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

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from ..channels import ChannelDeliveryError, ChannelNotConfigured, adapter_for
from ..core.config import get_settings
from ..core.deps import get_current_patient
from ..db import get_db
from ..models import ConsentRecord, Patient, ReminderOccurrence
from ..reminders import (
    _now,
    deactivate_prescription_schedules,
    generate_occurrences,
    materialize_schedules,
    patient_timezone,
    tick,
)
from ..schemas import (
    EnrollmentOut,
    OccurrenceOut,
    ReminderRunOut,
    ReminderTestIn,
    ReminderTestOut,
)
from ..translate import reply_hint
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
        attempts=row.attempts,
        next_attempt_at=row.next_attempt_at,
        patient_action=row.patient_action,
        patient_action_at=row.patient_action_at,
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


@router.post("/api/reminders/test", response_model=ReminderTestOut)
def send_test_reminder(
    body: ReminderTestIn | None = None,
    patient: Patient = Depends(get_current_patient),
    db: Session = Depends(get_db),
) -> ReminderTestOut:
    """Send one real test message over a consented channel.

    The test message contains no medical content. It still obeys the hard
    consent gate: without an explicit grant for the channel the request is a
    403 ``consent_required`` (default deny stays default deny). An
    unconfigured provider is a 502 — a test can never pretend to succeed.
    """
    requested = ((body.channel if body else None) or patient.preferred_channel).strip().lower()
    if requested not in ("whatsapp", "sms", "voice"):
        raise HTTPException(status_code=422, detail="Unknown reminder channel.")

    consent = (
        db.query(ConsentRecord)
        .filter(
            ConsentRecord.patient_id == patient.id,
            ConsentRecord.channel == requested,
            ConsentRecord.granted.is_(True),
        )
        .first()
    )
    if consent is None:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "consent_required",
                "message": f"Grant {requested} consent before sending a test message.",
            },
        )

    adapter = adapter_for(requested)
    if not adapter.configured:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "channel_unavailable",
                "message": f"The {requested} provider is not configured for this deployment.",
            },
        )

    text = "MedRecall test message: your reminder channel is connected. Reply HELP for help."
    if requested == "sms":
        text = f"{text}\n{reply_hint(patient.preferred_lang)}"
    try:
        result = adapter.send(patient.phone, text, lang=patient.preferred_lang)
    except ChannelNotConfigured as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": "channel_unavailable", "message": str(exc)},
        ) from exc
    except ChannelDeliveryError as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": "delivery_failed", "message": str(exc)},
        ) from exc

    return ReminderTestOut(
        channel=result.channel, sent=True, message_id=result.message_id
    )


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
