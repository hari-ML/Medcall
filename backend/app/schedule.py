"""Timetable + reminder building for MedRecall.

THE SAFETY RULE, enforced here:
    only items with status in ``SCHEDULEABLE_STATUSES``
    (clear | confirmed | edited) are translated and scheduled.
    Every other item lands in ``excluded`` — never translated, never given a
    time, never used for a reminder.

Reminders use the four default dose times 08:00 / 13:00 / 18:00 / 21:00.
As-needed (SOS/PRN) medicines get NO fixed slot and NO reminder.
"""

from __future__ import annotations

from datetime import date as _date
from typing import Any, Iterable, Mapping

from .parser import slots_for_frequency
from .translate import Translator, get_translator
from .uncertainty import SCHEDULEABLE_STATUSES

#: Fixed slot order for display.
SLOT_ORDER = ("morning", "afternoon", "evening", "night")

#: Default reminder time per slot (also drives the Home "NEXT DOSE" card).
SLOT_DEFAULT_TIMES: dict[str, str] = {
    "morning": "08:00",
    "afternoon": "13:00",
    "evening": "18:00",
    "night": "21:00",
}


def is_scheduleable(item: Mapping[str, Any]) -> bool:
    """Single choke point used by schedule, PDF and reminders."""
    return item.get("status") in SCHEDULEABLE_STATUSES


def is_as_needed(item: Mapping[str, Any]) -> bool:
    return bool(item.get("as_needed")) or item.get("frequency") == "SOS"


def _slot_entries_for(item: Mapping[str, Any]) -> list[str]:
    """Stored slots if present, otherwise derived from the frequency code."""
    stored = item.get("slots")
    if stored:
        return list(stored)
    return slots_for_frequency(item.get("frequency"))


def build_schedule(
    items: Iterable[Mapping[str, Any]],
    lang: str = "en",
    translator: Translator | None = None,
) -> dict[str, Any]:
    """Build the four-slot timetable + as-needed + excluded lists.

    ``items`` are dicts shaped like the API payload (medicine, strength,
    form, frequency, food_timing, duration_days, as_needed, status, reason,
    source_text, line_number, id).
    """
    translator = translator or get_translator(lang)

    slots: dict[str, list[dict[str, Any]]] = {s: [] for s in SLOT_ORDER}
    as_needed: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []

    for item in items:
        base = {
            "id": item.get("id"),
            "medicine": item.get("medicine") or "",
            "status": item.get("status") or "",
        }
        if not is_scheduleable(item):
            # --- the safety rule: excluded, never translated ----------------
            excluded.append(
                {
                    **base,
                    "reason": item.get("reason") or "Needs confirmation",
                    "source_text": item.get("source_text") or "",
                    "line_number": item.get("line_number"),
                }
            )
            continue

        instruction = translator.instruction(item)  # validated again inside

        if is_as_needed(item):
            as_needed.append({**base, "instruction": instruction})
            continue

        entry = {
            **base,
            "instruction": instruction,
            "time": None,
            "slot": None,
        }
        placed = False
        for slot in _slot_entries_for(item):
            if slot in slots:
                slots[slot].append({**entry, "time": SLOT_DEFAULT_TIMES[slot], "slot": slot})
                placed = True
        if not placed:
            # scheduleable but no derivable slot (should not happen for
            # clear items) — surface it as as-needed rather than dropping it.
            as_needed.append({**base, "instruction": instruction})

    return {
        "lang": lang,
        "date": _date.today().isoformat(),
        "title": translator.title(),
        "disclaimer": translator.disclaimer(),
        "as_needed_heading": translator.as_needed_heading(),
        "excluded_heading": translator.excluded_heading(),
        "empty_slot_note": translator.empty_slot_note(),
        "slots": slots,
        "as_needed": as_needed,
        "excluded": excluded,
        "slot_times": dict(SLOT_DEFAULT_TIMES),
    }


def build_reminders(
    items: Iterable[Mapping[str, Any]],
    lang: str = "en",
) -> list[dict[str, Any]]:
    """Reminder feed: scheduleable, fixed-slot items only.

    Unclear items and as-needed (SOS/PRN) medicines are never included.
    Sorted by time of day.
    """
    translator = get_translator(lang)
    reminders: list[dict[str, Any]] = []
    for item in items:
        if not is_scheduleable(item) or is_as_needed(item):
            continue
        instruction = translator.instruction(item)
        for slot in _slot_entries_for(item):
            if slot not in SLOT_DEFAULT_TIMES:
                continue
            reminders.append(
                {
                    "time": SLOT_DEFAULT_TIMES[slot],
                    "medicine": item.get("medicine") or "",
                    "instruction": instruction,
                    "slot": slot,
                    "id": item.get("id"),
                }
            )
    reminders.sort(key=lambda r: (r["time"], r["medicine"]))
    return reminders
