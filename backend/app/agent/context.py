"""Verified, patient-scoped context for the care agent (Phase 5).

The agent never queries the parser, OCR, seed or PDF code. It reads the
stored gate output, runs the *same* ``build_schedule`` used by the timetable
screen/PDF, and keeps unclear items separate: their dose, frequency and
timing are never copied into the context (or into an LLM prompt).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session, selectinload

from ..models import (
    ConsentRecord,
    MedicineItem,
    Patient,
    Prescription,
    ReminderSchedule,
)
from ..schedule import build_schedule, is_as_needed, is_scheduleable
from ..translate import LANG_NAMES, get_translator

#: caps keep a single chat turn (and a possible LLM prompt) bounded
MAX_PRESCRIPTIONS = 10
MAX_ITEMS = 100


@dataclass(frozen=True)
class ContextItem:
    item_id: int
    prescription_id: int
    prescription_date: str
    medicine: str
    strength: str
    form: str
    frequency: str
    food_timing: str
    duration_days: int | None
    as_needed: bool
    status: str
    reason: str
    instruction: str
    times: tuple[tuple[str, str], ...]
    scheduleable: bool


@dataclass(frozen=True)
class AgentContext:
    patient_id: int
    lang: str
    language_name: str
    timezone: str
    today: str
    caregiver_name: str
    caregiver_phone: str
    items: tuple[ContextItem, ...]
    schedule: dict
    active_schedules: int
    consent_channels: tuple[str, ...]
    truncated: bool

    def items_by_prescription(self) -> list[tuple[str, list[ContextItem]]]:
        groups: dict[tuple[str, int], list[ContextItem]] = {}
        for item in self.items:
            groups.setdefault(
                (item.prescription_date, item.prescription_id), []
            ).append(item)
        return [(date, items) for (date, _pid), items in groups.items()]

    def safety_text(self) -> str:
        """Only verified clinical values; used to validate LLM output.

        Unclear items contribute only their name — never a strength, source
        text, reason, instruction, or time.
        """
        parts: list[str] = []
        for item in self.items:
            parts.append(item.medicine)
            if not item.scheduleable:
                continue
            parts.extend(
                [item.strength, item.form, item.frequency, item.instruction]
            )
            if item.duration_days:
                parts.append(str(item.duration_days))
            parts.extend(f"{slot} {time}" for slot, time in item.times)
        return "\n".join(part for part in parts if part)

    def prompt_text(self) -> str:
        """A compact verified-data prompt; no phone, image, or source text."""
        lines = [
            f"PATIENT LANGUAGE: {self.lang}",
            f"TIMEZONE: {self.timezone}",
            "VERIFIED PRESCRIPTION DATA (the only source of truth):",
        ]
        for date, items in self.items_by_prescription():
            lines.append(f"Prescription {date or 'unknown date'}:")
            for item in items:
                if item.scheduleable:
                    name = " ".join(
                        part for part in (item.medicine, item.strength) if part
                    )
                else:
                    name = item.medicine or "Unnamed item"
                if not item.scheduleable:
                    lines.append(
                        f"- {name} | status={item.status} | "
                        f"reason={item.reason or 'needs confirmation'} | "
                        "DO NOT STATE A DOSE, FREQUENCY, OR TIME"
                    )
                elif item.as_needed:
                    lines.append(
                        f"- {name} | status={item.status} | "
                        f"{item.instruction} | "
                        "AS NEEDED: no fixed time, no reminder"
                    )
                else:
                    times = (
                        ", ".join(f"{slot} {time}" for slot, time in item.times)
                        or "no fixed time"
                    )
                    lines.append(
                        f"- {name} | status={item.status} | "
                        f"{item.instruction} | times: {times}"
                    )
        channels = ", ".join(self.consent_channels) or "none"
        lines.append(
            f"REMINDERS: active_schedules={self.active_schedules}; "
            f"consented_channels={channels}"
        )
        lines.append("END OF VERIFIED DATA.")
        return "\n".join(lines)


def _patient_timezone(patient: Patient) -> tuple[ZoneInfo, str]:
    name = (patient.timezone or "UTC").strip() or "UTC"
    try:
        return ZoneInfo(name), name
    except (ValueError, KeyError):
        return ZoneInfo("UTC"), "UTC"


def _date_str(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d") if value else ""


def _state(item: MedicineItem) -> dict:
    return {
        "id": item.id,
        "line_number": item.line_number,
        "medicine": item.medicine_name,
        "strength": item.strength,
        "form": item.form,
        "frequency": item.frequency,
        "food_timing": item.food_timing,
        "duration_days": item.duration_days,
        "as_needed": bool(item.as_needed),
        "status": item.status,
        "reason": item.reason,
        "slots": list(item.slots or []),
        "source_text": item.source_text,
    }


def build_context(
    db: Session, patient: Patient, lang: str = "en"
) -> AgentContext:
    translator = get_translator(lang)
    tz, tz_name = _patient_timezone(patient)
    now_local = datetime.now(timezone.utc).astimezone(tz)

    prescriptions = (
        db.query(Prescription)
        .options(selectinload(Prescription.items))
        .filter(Prescription.patient_id == patient.id)
        .order_by(Prescription.created_at.desc(), Prescription.id.desc())
        .limit(MAX_PRESCRIPTIONS + 1)
        .all()
    )
    truncated = len(prescriptions) > MAX_PRESCRIPTIONS
    prescriptions = prescriptions[:MAX_PRESCRIPTIONS]

    triples: list[tuple[Prescription, MedicineItem, dict]] = []
    for prescription in prescriptions:
        for item in prescription.items:
            triples.append((prescription, item, _state(item)))
            if len(triples) >= MAX_ITEMS:
                truncated = True
                break
        if len(triples) >= MAX_ITEMS:
            break

    schedule = build_schedule(
        [state for _p, _i, state in triples], lang, translator=translator
    )
    # The excluded list is for display only; source_text can contain an
    # unverified dose, so it never enters the agent context or a prompt.
    for entry in schedule.get("excluded", []):
        entry.pop("source_text", None)

    instruction_by_id: dict[int, str] = {}
    times_by_id: dict[int, list[tuple[str, str]]] = {}
    for entries in schedule.get("slots", {}).values():
        for entry in entries:
            item_id = entry.get("id")
            if item_id is None:
                continue
            instruction_by_id.setdefault(item_id, entry.get("instruction", ""))
            slot = entry.get("slot")
            time = entry.get("time")
            if slot and time:
                times_by_id.setdefault(item_id, []).append((slot, time))
    for entry in schedule.get("as_needed", []):
        item_id = entry.get("id")
        if item_id is not None:
            instruction_by_id.setdefault(item_id, entry.get("instruction", ""))

    items: list[ContextItem] = []
    for prescription, item, state in triples:
        scheduleable = is_scheduleable(state)
        items.append(
            ContextItem(
                item_id=item.id,
                prescription_id=prescription.id,
                prescription_date=_date_str(prescription.created_at),
                medicine=item.medicine_name or "",
                strength=item.strength or "",
                form=item.form or "",
                frequency=item.frequency or "",
                food_timing=item.food_timing or "",
                duration_days=item.duration_days,
                as_needed=is_as_needed(state),
                status=item.status,
                reason=item.reason or "",
                instruction=(
                    instruction_by_id.get(item.id, "") if scheduleable else ""
                ),
                times=(
                    tuple(times_by_id.get(item.id, ())) if scheduleable else ()
                ),
                scheduleable=scheduleable,
            )
        )

    active_schedules = (
        db.query(ReminderSchedule)
        .filter(
            ReminderSchedule.patient_id == patient.id,
            ReminderSchedule.active.is_(True),
        )
        .count()
    )
    consent_channels = tuple(
        row.channel
        for row in db.query(ConsentRecord)
        .filter(
            ConsentRecord.patient_id == patient.id,
            ConsentRecord.granted.is_(True),
        )
        .order_by(ConsentRecord.channel)
        .all()
    )

    return AgentContext(
        patient_id=patient.id,
        lang=lang,
        language_name=LANG_NAMES.get(lang, lang),
        timezone=tz_name,
        today=now_local.strftime("%Y-%m-%d"),
        caregiver_name=patient.caregiver_name or "",
        caregiver_phone=patient.caregiver_phone or "",
        items=tuple(items),
        schedule=schedule,
        active_schedules=active_schedules,
        consent_channels=consent_channels,
        truncated=truncated,
    )
