"""Reminder engine (Phase 3).

Flow
----
1. ``materialize_schedules`` — the patient enrolls a prescription; only items
   with status in ``SCHEDULEABLE_STATUSES`` and NOT as-needed (SOS/PRN) get
   a ``ReminderSchedule`` (one row per daily slot, local HH:MM in the
   patient's IANA timezone). Re-enrolling is idempotent; items that became
   unclear are deactivated and their pending occurrences cancelled.
2. ``generate_occurrences`` — lazily creates ``ReminderOccurrence`` rows from
   now (minus the grace window) up to a horizon, converting local slot times
   to naive UTC.
3. ``dispatch_due`` — sends each due occurrence through the patient's first
   consented channel. RIGHT BEFORE EVERY SEND it re-checks, in order:
      a) the schedule is still active,
      b) the item is still scheduleable and not as-needed (defense in depth
         — an item edited to ``unclear`` can never produce a message),
      c) the occurrence is inside the grace window (old doses are marked
         ``missed``, never sent late),
      d) the patient granted explicit consent for the channel.

THE SAFETY RULE: unclear items are never translated, scheduled, or sent —
``is_scheduleable`` and the translator's own ``UnclearItemError`` guard
every message. The message body is built only from the stored, verified
timetable fields; the engine never invents a dose or a time.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from datetime import date, datetime, time as dtime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import or_
from sqlalchemy.orm import Session

from .channels import (
    REMINDER_CHANNELS,
    ChannelDeliveryError,
    ChannelNotConfigured,
    InteractiveButton,
    InteractiveMessage,
    adapter_for,
)
from .core.config import get_settings
from .db import SessionLocal
from .models import (
    ConsentRecord,
    MedicineItem,
    Patient,
    Prescription,
    ReminderOccurrence,
    ReminderSchedule,
)
from .parser import slots_for_frequency
from .schedule import SLOT_DEFAULT_TIMES, is_as_needed, is_scheduleable
from .translate import get_translator, reply_hint

logger = logging.getLogger("medrecall.reminders")

#: statuses a reminder occurrence can be in
OCCURRENCE_STATUSES = (
    "pending",
    "sent",
    "failed",
    "blocked",
    "missed",
    "cancelled",
)


# ---------------------------------------------------------------------------
# Time helpers (the app-wide convention is naive UTC)
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _as_naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def patient_timezone(patient: Patient) -> ZoneInfo:
    try:
        return ZoneInfo(patient.timezone or "UTC")
    except (ValueError, KeyError):  # ZoneInfoNotFoundError is a KeyError
        logger.warning(
            "Patient %s has unknown timezone %r — falling back to UTC",
            patient.id,
            patient.timezone,
        )
        return ZoneInfo("UTC")


def _local_now(now_utc: datetime, patient: Patient) -> datetime:
    return now_utc.replace(tzinfo=timezone.utc).astimezone(patient_timezone(patient))


# ---------------------------------------------------------------------------
# Item state (same shape the scheduler/translator consume)
# ---------------------------------------------------------------------------


def _item_state(item: MedicineItem) -> dict:
    return {
        "id": item.id,
        "line_number": item.line_number,
        "medicine": item.medicine_name,
        "strength": item.strength,
        "form": item.form,
        "frequency": item.frequency,
        "food_timing": item.food_timing,
        "duration_days": item.duration_days,
        "as_needed": item.as_needed,
        "status": item.status,
        "reason": item.reason,
        "slots": list(item.slots or []),
        "source_text": item.source_text,
    }


def _slots_for(state: dict) -> list[str]:
    """Stored slots if present, else derived; only known fixed slots survive."""
    stored = state.get("slots") or []
    slots = stored if stored else slots_for_frequency(state.get("frequency"))
    return [slot for slot in slots if slot in SLOT_DEFAULT_TIMES]


def _end_date(start: date | None, duration_days: int | None) -> date | None:
    if start is None or not duration_days or duration_days < 1:
        return None
    return start + timedelta(days=duration_days - 1)


def _parse_hhmm(value: str) -> tuple[int, int]:
    try:
        hours, minutes = value.strip().split(":")
        return int(hours), int(minutes)
    except (ValueError, AttributeError):
        return 8, 0  # defensive: never invented at runtime — validated on write


# ---------------------------------------------------------------------------
# Enrollment / synchronization
# ---------------------------------------------------------------------------


def _cancel_pending(db: Session, schedule: ReminderSchedule, reason: str) -> int:
    """Cancel every pending occurrence of a schedule (never touches history)."""
    return (
        db.query(ReminderOccurrence)
        .filter(
            ReminderOccurrence.schedule_id == schedule.id,
            ReminderOccurrence.status == "pending",
        )
        .update(
            {"status": "cancelled", "error": reason, "next_attempt_at": None},
            synchronize_session=False,
        )
    )


def _cancel_outside_course(db: Session, schedule: ReminderSchedule, patient: Patient) -> int:
    """Cancel pending occurrences that now fall after the course's last day."""
    if schedule.end_date is None:
        return 0
    cutoff_local = datetime.combine(
        schedule.end_date + timedelta(days=1), dtime(0, 0), tzinfo=patient_timezone(patient)
    )
    cutoff_utc = cutoff_local.astimezone(timezone.utc).replace(tzinfo=None)
    return (
        db.query(ReminderOccurrence)
        .filter(
            ReminderOccurrence.schedule_id == schedule.id,
            ReminderOccurrence.status == "pending",
            ReminderOccurrence.scheduled_at >= cutoff_utc,
        )
        .update(
            {
                "status": "cancelled",
                "error": "outside the prescribed course",
                "next_attempt_at": None,
            },
            synchronize_session=False,
        )
    )


def materialize_schedules(db: Session, prescription: Prescription, patient: Patient) -> dict:
    """Build/refresh reminder schedules from the prescription's timetable.

    Returns a JSON-able summary: ``scheduled_doses``, ``items`` (what was
    enrolled), ``skipped`` (unclear / as-needed / no-slot items, with why).
    """
    today_local = _local_now(_now(), patient).date()
    existing = {
        (row.item_id, row.slot): row
        for row in db.query(ReminderSchedule)
        .filter(ReminderSchedule.prescription_id == prescription.id)
        .all()
    }
    desired: set[tuple[int, str]] = set()
    enrolled_items: list[dict] = []
    skipped: list[dict] = []

    for item in prescription.items:
        state = _item_state(item)
        reason = ""
        if not is_scheduleable(state):
            reason = "Unclear items are never scheduled — confirm or edit the line first."
        elif is_as_needed(state):
            reason = "As-needed (SOS/PRN) medicines never get fixed-time reminders."
        else:
            slots = _slots_for(state)
            if not slots:
                reason = "No fixed daily slot could be derived from this line."

        if reason:
            skipped.append(
                {"item_id": item.id, "medicine": state["medicine"] or "", "reason": reason}
            )
            continue

        for slot in _slots_for(state):
            key = (item.id, slot)
            desired.add(key)
            row = existing.get(key)
            if row is None:
                row = ReminderSchedule(
                    patient_id=patient.id,
                    prescription_id=prescription.id,
                    item_id=item.id,
                    slot=slot,
                    time_of_day=SLOT_DEFAULT_TIMES[slot],
                    lang=patient.preferred_lang,
                    start_date=today_local,
                    active=True,
                )
                db.add(row)
            else:
                if not row.active or row.start_date is None:
                    row.start_date = today_local
                row.active = True
                row.lang = patient.preferred_lang
                row.time_of_day = SLOT_DEFAULT_TIMES[slot]
            row.end_date = _end_date(row.start_date, item.duration_days)
            enrolled_items.append(
                {
                    "item_id": item.id,
                    "medicine": state["medicine"] or "",
                    "slot": slot,
                    "time_of_day": SLOT_DEFAULT_TIMES[slot],
                }
            )

    # Slots that disappeared (frequency edited, item became unclear, ...).
    for key, row in existing.items():
        if key not in desired and row.active:
            row.active = False
            _cancel_pending(db, row, "reminder schedule changed")

    db.commit()
    return {
        "scheduled_doses": len(enrolled_items),
        "items": enrolled_items,
        "skipped": skipped,
    }


def deactivate_prescription_schedules(db: Session, prescription: Prescription) -> int:
    """Stop all reminders for a prescription (history is kept)."""
    rows = (
        db.query(ReminderSchedule)
        .filter(
            ReminderSchedule.prescription_id == prescription.id,
            ReminderSchedule.active.is_(True),
        )
        .all()
    )
    for row in rows:
        row.active = False
        _cancel_pending(db, row, "reminders were turned off")
    db.commit()
    return len(rows)


def sync_item_schedules(db: Session, item: MedicineItem, patient: Patient) -> None:
    """Keep schedules truthful after a confirm/edit re-gated an item.

    No-op when the prescription was never enrolled (no schedule rows for the
    prescription) — a confirmation does not silently opt the patient into
    reminders. If the prescription IS enrolled, confirming/editing an item
    adds missing slots and edits that make it unclear remove its schedules.
    """
    rows = db.query(ReminderSchedule).filter(ReminderSchedule.item_id == item.id).all()
    if not rows:
        enrolled = (
            db.query(ReminderSchedule.id)
            .filter(ReminderSchedule.prescription_id == item.prescription_id)
            .first()
        )
        if enrolled is None:
            return

    state = _item_state(item)
    if not is_scheduleable(state) or is_as_needed(state) or not _slots_for(state):
        for row in rows:
            if row.active:
                row.active = False
            _cancel_pending(db, row, "item is no longer scheduleable (safety stop)")
        db.commit()
        return

    desired = set(_slots_for(state))
    existing = {row.slot: row for row in rows}
    for slot, row in existing.items():
        if slot not in desired and row.active:
            row.active = False
            _cancel_pending(db, row, "reminder schedule changed")

    today_local = _local_now(_now(), patient).date()
    for slot in desired:
        row = existing.get(slot)
        if row is None:
            row = ReminderSchedule(
                patient_id=patient.id,
                prescription_id=item.prescription_id,
                item_id=item.id,
                slot=slot,
                time_of_day=SLOT_DEFAULT_TIMES[slot],
                lang=patient.preferred_lang,
                start_date=today_local,
                active=True,
            )
            db.add(row)
        else:
            if not row.active or row.start_date is None:
                row.start_date = today_local
            row.active = True
            row.lang = patient.preferred_lang
            row.time_of_day = SLOT_DEFAULT_TIMES[slot]
        row.end_date = _end_date(row.start_date, item.duration_days)
        _cancel_outside_course(db, row, patient)

    db.commit()


def update_language(db: Session, patient: Patient) -> None:
    """Future messages follow the patient's current preferred language."""
    db.query(ReminderSchedule).filter(
        ReminderSchedule.patient_id == patient.id,
        ReminderSchedule.active.is_(True),
    ).update({"lang": patient.preferred_lang}, synchronize_session=False)
    db.commit()


# ---------------------------------------------------------------------------
# Occurrence generation
# ---------------------------------------------------------------------------


def generate_occurrences(
    db: Session,
    now_utc: datetime | None = None,
    horizon_hours: int | None = None,
    *,
    patient_id: int | None = None,
) -> int:
    """Create missing occurrences from (now - grace) to now + horizon.

    Idempotent: the unique (schedule_id, scheduled_at) constraint plus an
    existence check make repeated ticks safe. Returns how many were created.
    """
    settings = get_settings()
    now = _as_naive_utc(now_utc or _now())
    horizon = horizon_hours if horizon_hours is not None else settings.reminder_horizon_hours
    grace_cutoff = now - timedelta(minutes=settings.reminder_grace_minutes)
    horizon_end = now + timedelta(hours=horizon)

    query = db.query(ReminderSchedule).filter(ReminderSchedule.active.is_(True))
    if patient_id is not None:
        query = query.filter(ReminderSchedule.patient_id == patient_id)

    created = 0
    for schedule in query.all():
        patient = schedule.patient
        if patient is None:
            continue
        tz = patient_timezone(patient)
        first_day = max(
            _local_now(grace_cutoff, patient).date(),
            schedule.start_date or _local_now(grace_cutoff, patient).date(),
        )
        last_day = _local_now(horizon_end, patient).date()
        if schedule.end_date is not None:
            last_day = min(last_day, schedule.end_date)
        if last_day < first_day:
            continue

        existing_times = {
            row[0]
            for row in db.query(ReminderOccurrence.scheduled_at)
            .filter(
                ReminderOccurrence.schedule_id == schedule.id,
                ReminderOccurrence.scheduled_at >= grace_cutoff,
                ReminderOccurrence.scheduled_at <= horizon_end,
            )
            .all()
        }

        hours, minutes = _parse_hhmm(schedule.time_of_day)
        day = first_day
        while day <= last_day:
            local_dt = datetime(day.year, day.month, day.day, hours, minutes, tzinfo=tz)
            scheduled_at = local_dt.astimezone(timezone.utc).replace(tzinfo=None)
            if (
                grace_cutoff <= scheduled_at <= horizon_end
                and scheduled_at not in existing_times
            ):
                db.add(
                    ReminderOccurrence(
                        schedule_id=schedule.id,
                        patient_id=schedule.patient_id,
                        scheduled_at=scheduled_at,
                        status="pending",
                    )
                )
                existing_times.add(scheduled_at)
                created += 1
            day += timedelta(days=1)

    db.commit()
    return created


# ---------------------------------------------------------------------------
# Dispatch (consent is a hard pre-send gate)
# ---------------------------------------------------------------------------


def _granted_channel(db: Session, patient_id: int) -> str | None:
    """First consented channel in preference order, or None (no consent)."""
    granted = {
        row.channel
        for row in db.query(ConsentRecord)
        .filter(
            ConsentRecord.patient_id == patient_id,
            ConsentRecord.granted.is_(True),
        )
        .all()
    }
    for channel in REMINDER_CHANNELS:
        if channel in granted:
            return channel
    return None


def build_message(schedule: ReminderSchedule, state: dict) -> str:
    """The exact reminder text — built only from verified timetable fields.

    Raises ``UnclearItemError`` (via the translator) if the item somehow is
    not scheduleable — the dispatcher treats that as a cancellation.
    """
    translator = get_translator(schedule.lang or "en")
    instruction = translator.instruction(state)
    name = " ".join(
        part for part in (state.get("medicine") or "", state.get("strength") or "") if part
    )
    if name:
        return f"MedRecall: {name} — {instruction}"
    return f"MedRecall: {instruction}"


def retry_delay_seconds(attempts: int) -> int:
    """Exponential backoff after the ``attempts``-th transient failure.

    ``base * 2**(attempts-1)`` capped at ``reminder_retry_max_seconds``. The
    grace window still bounds the whole retry chain — a retry that would fall
    outside it is marked ``missed`` instead of being sent late.
    """
    settings = get_settings()
    base = max(1, settings.reminder_retry_base_seconds)
    cap = max(base, settings.reminder_retry_max_seconds)
    return min(base * (2 ** max(0, attempts - 1)), cap)


def dispatch_due(
    db: Session,
    now_utc: datetime | None = None,
    *,
    patient_id: int | None = None,
    limit: int = 500,
) -> dict:
    """Deliver due occurrences; returns per-outcome counts."""
    settings = get_settings()
    now = _as_naive_utc(now_utc or _now())
    grace_cutoff = now - timedelta(minutes=settings.reminder_grace_minutes)

    query = db.query(ReminderOccurrence).filter(
        ReminderOccurrence.status == "pending",
        ReminderOccurrence.scheduled_at <= now,
        or_(
            ReminderOccurrence.next_attempt_at.is_(None),
            ReminderOccurrence.next_attempt_at <= now,
        ),
    )
    if patient_id is not None:
        query = query.filter(ReminderOccurrence.patient_id == patient_id)

    counts = {status: 0 for status in ("sent", "blocked", "failed", "missed", "cancelled")}

    for occurrence in query.order_by(ReminderOccurrence.scheduled_at).limit(limit).all():
        schedule = occurrence.schedule
        item = schedule.item if schedule is not None else None
        patient = schedule.patient if schedule is not None else None

        # (a) the schedule must still be active and belong to this patient
        if (
            schedule is None
            or not schedule.active
            or item is None
            or patient is None
            or schedule.patient_id != occurrence.patient_id
        ):
            occurrence.status = "cancelled"
            occurrence.error = "reminder schedule is no longer active"
            occurrence.next_attempt_at = None
            counts["cancelled"] += 1
            continue

        # (b) safety stop: the item must still be scheduleable, not SOS/PRN
        state = _item_state(item)
        if not is_scheduleable(state) or is_as_needed(state):
            occurrence.status = "cancelled"
            occurrence.error = "item is not scheduleable (safety stop)"
            occurrence.next_attempt_at = None
            counts["cancelled"] += 1
            continue

        # (c) never send a stale dose outside the grace window
        if occurrence.scheduled_at < grace_cutoff:
            occurrence.status = "missed"
            occurrence.error = "past the reminder grace window"
            occurrence.next_attempt_at = None
            counts["missed"] += 1
            continue

        # (d) explicit per-channel consent, re-checked on every send
        channel = _granted_channel(db, occurrence.patient_id)
        if channel is None:
            occurrence.status = "blocked"
            occurrence.error = "no consent granted for any reminder channel"
            occurrence.next_attempt_at = None
            counts["blocked"] += 1
            continue

        adapter = adapter_for(channel)
        if not adapter.configured:
            occurrence.status = "failed"
            occurrence.error = f"{channel} channel is not configured"
            occurrence.next_attempt_at = None
            counts["failed"] += 1
            continue

        try:
            body = build_message(schedule, state)
            lang = schedule.lang or "en"
            interactive = None
            if channel == "whatsapp":
                # Real reply buttons; the ids come back through the inbound
                # webhook and only ever reference this occurrence — they never
                # carry a dose or a time of their own.
                interactive = InteractiveMessage(
                    buttons=[
                        InteractiveButton(id=f"TAKEN_{occurrence.id}", title="Taken"),
                        InteractiveButton(id=f"SNOOZE_{occurrence.id}", title="Snooze 30m"),
                        InteractiveButton(id=f"HELP_{occurrence.id}", title="Help"),
                    ]
                )
            elif channel == "sms":
                # Plain SMS has no buttons: append the keyword instructions.
                body = f"{body}\n{reply_hint(lang)}"
            result = adapter.send(patient.phone, body, lang=lang, interactive=interactive)
        except ChannelNotConfigured as exc:
            occurrence.status = "failed"
            occurrence.error = str(exc)
            occurrence.next_attempt_at = None
            counts["failed"] += 1
            continue
        except ChannelDeliveryError as exc:
            occurrence.attempts += 1
            occurrence.error = str(exc)[:500]
            if not exc.transient or occurrence.attempts >= settings.reminder_max_attempts:
                occurrence.status = "failed"
                occurrence.next_attempt_at = None
                counts["failed"] += 1
            else:
                delay = retry_delay_seconds(occurrence.attempts)
                occurrence.next_attempt_at = now + timedelta(seconds=delay)
                logger.info(
                    "Reminder %s via %s failed (attempt %s/%s), retrying in %ss",
                    occurrence.id,
                    channel,
                    occurrence.attempts,
                    settings.reminder_max_attempts,
                    delay,
                )
            continue
        except Exception as exc:  # noqa: BLE001 - one bad send must not stop the batch
            # Unknown failures are treated as transient (conservative) and
            # bounded by the same attempt limit.
            occurrence.attempts += 1
            occurrence.error = str(exc)[:500]
            if occurrence.attempts >= settings.reminder_max_attempts:
                occurrence.status = "failed"
                occurrence.next_attempt_at = None
                counts["failed"] += 1
            else:
                delay = retry_delay_seconds(occurrence.attempts)
                occurrence.next_attempt_at = now + timedelta(seconds=delay)
            continue

        occurrence.status = "sent"
        occurrence.channel = result.channel
        occurrence.body = body
        occurrence.provider_message_id = result.message_id
        occurrence.sent_at = now
        occurrence.next_attempt_at = None
        occurrence.error = ""
        counts["sent"] += 1

    db.commit()
    return counts


# ---------------------------------------------------------------------------
# Inbound reply actions (WhatsApp / SMS webhooks, Part 3)
# ---------------------------------------------------------------------------


def recent_occurrence(
    db: Session, patient_id: int, occurrence_id: int | None = None
) -> ReminderOccurrence | None:
    """The occurrence an inbound reply refers to, or None.

    Button ids carry the exact occurrence (``TAKEN_123``). Plain SMS keywords
    have no id, so they target the patient's most recent occurrence from the
    last 24 hours — never an arbitrary or future dose.
    """
    query = db.query(ReminderOccurrence).filter(
        ReminderOccurrence.patient_id == patient_id
    )
    if occurrence_id is not None:
        return query.filter(ReminderOccurrence.id == occurrence_id).first()
    cutoff = _now() - timedelta(hours=24)
    return (
        query.filter(ReminderOccurrence.scheduled_at >= cutoff)
        .order_by(ReminderOccurrence.scheduled_at.desc())
        .first()
    )


def record_patient_action(
    db: Session, occurrence: ReminderOccurrence, action: str
) -> None:
    """Record what the patient answered; never changes the delivery status.

    ``taken`` / ``snooze`` / ``skip`` / ``help`` are audit facts about the
    patient's response, not medical decisions — the timetable is unchanged.
    """
    occurrence.patient_action = action[:16]
    occurrence.patient_action_at = _now()
    db.commit()


def snooze_occurrence(
    db: Session, occurrence: ReminderOccurrence, minutes: int
) -> ReminderOccurrence | None:
    """Create a one-off pending occurrence ``minutes`` after the original.

    The snooze reuses the original schedule (and therefore the same verified
    item); no body is copied. The dispatcher re-checks every safety gate
    before the new occurrence can be sent. Returns None when an occurrence
    already exists at that exact time (idempotent webhook retries).
    """
    if occurrence.schedule_id is None:
        return None
    target = occurrence.scheduled_at + timedelta(minutes=max(1, minutes))
    exists = (
        db.query(ReminderOccurrence.id)
        .filter(
            ReminderOccurrence.schedule_id == occurrence.schedule_id,
            ReminderOccurrence.scheduled_at == target,
        )
        .first()
    )
    if exists is not None:
        return None
    snoozed = ReminderOccurrence(
        schedule_id=occurrence.schedule_id,
        patient_id=occurrence.patient_id,
        scheduled_at=target,
        status="pending",
    )
    db.add(snoozed)
    db.commit()
    db.refresh(snoozed)
    return snoozed


# ---------------------------------------------------------------------------
# One tick + the background loop + CLI
# ---------------------------------------------------------------------------


def tick(
    db: Session,
    now_utc: datetime | None = None,
    *,
    patient_id: int | None = None,
) -> dict:
    """Generate due occurrences and dispatch them once."""
    settings = get_settings()
    now = _as_naive_utc(now_utc or _now())
    generated = generate_occurrences(
        db,
        now,
        settings.reminder_horizon_hours,
        patient_id=patient_id,
    )
    counts = dispatch_due(db, now, patient_id=patient_id)
    return {"generated": generated, **counts}


def run_tick_once() -> dict:
    """A tick with its own DB session (used by the loop and the CLI)."""
    db = SessionLocal()
    try:
        counts = tick(db)
        if any(counts.get(key) for key in ("generated", "sent", "blocked", "failed", "missed")):
            logger.info("reminder tick: %s", counts)
        return counts
    finally:
        db.close()


async def dispatcher_loop(interval_seconds: int) -> None:
    """Foreground background task: tick every ``interval_seconds``."""
    logger.info("Reminder dispatcher started (every %ss)", interval_seconds)
    while True:
        try:
            await asyncio.to_thread(run_tick_once)
        except asyncio.CancelledError:
            logger.info("Reminder dispatcher stopped")
            raise
        except Exception:  # noqa: BLE001 - a broken tick must not kill the app
            logger.exception("Reminder dispatcher tick failed")
        await asyncio.sleep(interval_seconds)


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MedRecall reminder engine")
    parser.add_argument(
        "--tick",
        action="store_true",
        help="generate + dispatch due reminders once (cron-style deployment)",
    )
    args = parser.parse_args(argv)
    if not args.tick:
        parser.print_help()
        return 1
    print(json.dumps(run_tick_once(), sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(_main())
