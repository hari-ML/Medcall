"""Instruction parsing for MedRecall.

Turns one OCR text line into structured medicine fields:

    medicine_name, strength, form, frequency, food_timing, duration_days

Each field is a :class:`ParsedField` carrying a 0-1 confidence score and the
source fragment it was extracted from.

The parser is deliberately conservative: anything it cannot read with
confidence is left as ``None`` (with a low confidence) so that the
uncertainty gate (``uncertainty.py``) can flag the line as "unclear".
The parser NEVER invents values, NEVER makes medical decisions, and NEVER
decides safety — the gate is the only module that assigns a status.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

#: The four fixed daily slots (QID also uses "evening").
SLOTS = ("morning", "afternoon", "evening", "night")

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

#: Plain-English expansions for the abbreviation glossary shown in the UI.
ABBREVIATIONS: dict[str, str] = {
    "OD": "once a day",
    "QD": "once a day",
    "BD": "twice a day",
    "BID": "twice a day",
    "TDS": "three times a day",
    "TID": "three times a day",
    "QID": "four times a day",
    "HS": "at bedtime",
    "QHS": "at bedtime (every night)",
    "SOS": "as needed (symptom relief)",
    "PRN": "as needed (when required)",
    "AC": "before food",
    "PC": "after food",
    "tab": "tablet",
    "tabs": "tablets",
    "cap": "capsule",
    "caps": "capsules",
    "syp": "syrup",
    "syr": "syrup",
    "inj": "injection",
    "susp": "suspension",
    "d/cap": "dissolving capsule",
}

#: raw token (lowercase) -> normalized form.
FORMS: dict[str, str] = {
    "tab": "tab", "tabs": "tab", "tablet": "tab", "tablets": "tab", "tab.": "tab",
    "cap": "cap", "caps": "cap", "capsule": "cap", "capsules": "cap", "cap.": "cap",
    "d/cap": "cap",
    "syp": "syrup", "syr": "syrup", "syrup": "syrup",
    "susp": "syrup", "suspension": "syrup",
    "inj": "inj", "injection": "inj", "inje": "inj",
    "drops": "drops", "drop": "drops",
    "oint": "ointment", "ointment": "ointment",
    "inhaler": "inhaler", "inhalation": "inhaler",
    "supp": "suppository", "suppository": "suppository",
    "cream": "cream",
    "gel": "gel",
    "sachet": "sachet",
    "vial": "vial",
}

_FORM_START_RE = re.compile(
    r"^\s*(d/cap|tab|tabs|tablet|tablets|cap|caps|capsule|capsules|syp|syr|syrup|"
    r"inj|injection|susp|suspension|drops|drop|oint|ointment|inhaler|supp|"
    r"suppository|cream|gel|sachet|vial)[\.\s]",
    re.IGNORECASE,
)

#: A leading dose quantity such as "1 tab ..." or "2 caps ...".
_LEADING_QUANTITY_RE = re.compile(
    r"^\s*\d+\s*(d/cap|tab|tabs|cap|caps|syp|syrup|inj|inj|susp|drops|ointment|inhaler|supp|cream|gel|sachet|vial)\b[\.\s]",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Frequency
# ---------------------------------------------------------------------------

_CODE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bQD\b"), "OD"),
    (re.compile(r"\bOD\b"), "OD"),
    (re.compile(r"\b(?:BD|BID)\b"), "BD"),
    (re.compile(r"\b(?:TDS|TID)\b"), "TDS"),
    (re.compile(r"\bQID\b"), "QID"),
    (re.compile(r"\bQHS\b"), "HS"),
    (re.compile(r"\bHS\b"), "HS"),
]

_ASNEEDED_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(?:SOS|PRN)\b"),
    re.compile(r"\bas\s+needed\b", re.IGNORECASE),
    re.compile(r"\bwhen\s+required\b", re.IGNORECASE),
]

# "1-0-1" / "1 / 1 / 1" / "1–1–1"; a "?" component marks an ambiguous count.
_NNN_RE = re.compile(r"(?<!\d)(\d|\?)\s*[-\u2013/]\s*(\d|\?)\s*[-\u2013/]\s*(\d|\?)(?!\d)")

_FREQ_PHRASES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bonce\s+(?:a|the)\s+day\b", re.IGNORECASE), "OD"),
    (re.compile(r"\bonce\s+daily\b", re.IGNORECASE), "OD"),
    (re.compile(r"\btwice\s+(?:a|the)\s+day\b", re.IGNORECASE), "BD"),
    (re.compile(r"\btwice\s+daily\b", re.IGNORECASE), "BD"),
    (re.compile(r"\bthree\s+times\s+(?:a|the)\s+day\b", re.IGNORECASE), "TDS"),
    (re.compile(r"\bthree\s+times\s+daily\b", re.IGNORECASE), "TDS"),
    (re.compile(r"\bfour\s+times\s+(?:a|the)\s+day\b", re.IGNORECASE), "QID"),
    (re.compile(r"\bfour\s+times\s+daily\b", re.IGNORECASE), "QID"),
    (re.compile(r"\b(?:at\s+)?bedtime\b", re.IGNORECASE), "HS"),
    (re.compile(r"\b(?:at\s+)?nightly\b", re.IGNORECASE), "HS"),
    (re.compile(r"\b(?:at\s+)?night\b", re.IGNORECASE), "HS"),
]

_TIMES_A_DAY_RE = re.compile(r"\b(\d{1,2})\s+times\s+(?:a|the)\s+day\b", re.IGNORECASE)
_TIMES_DAILY_RE = re.compile(r"\b(\d{1,2})\s+times\s+daily\b", re.IGNORECASE)

_TIMES_TO_CODE = {1: "OD", 2: "BD", 3: "TDS", 4: "QID"}

#: Normalized frequency code -> fixed daily slots.
#: SOS has no fixed slot (as-needed medicines are never on a fixed schedule).
SLOT_MAP: dict[str, list[str]] = {
    "OD": ["morning"],
    "BD": ["morning", "night"],
    "TDS": ["morning", "afternoon", "night"],
    "QID": ["morning", "afternoon", "evening", "night"],
    "HS": ["night"],
    "SOS": [],
}


def _nnn_slots(components: tuple[str, str, str]) -> list[str]:
    """Slots implied by an N-N-N pattern (component index -> slot)."""
    slot_names = ("morning", "afternoon", "night")
    slots: list[str] = []
    for value, slot in zip(components, slot_names):
        if value.isdigit() and int(value) > 0:
            slots.append(slot)
    return slots


# ---------------------------------------------------------------------------
# Food timing
# ---------------------------------------------------------------------------

_FOOD_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bAC\b"), "before"),
    (re.compile(r"\bbefore\s+(?:food|meals?|dinner|lunch|breakfast)\b", re.IGNORECASE), "before"),
    (re.compile(r"\b(?:on\s+an\s+)?empty\s+stomach\b", re.IGNORECASE), "empty_stomach"),
    (re.compile(r"\bPC\b"), "after"),
    (re.compile(r"\bafter\s+(?:food|meals?|dinner|lunch|breakfast)\b", re.IGNORECASE), "after"),
    (re.compile(r"\bwith\s+(?:food|meals?)\b", re.IGNORECASE), "with"),
]

FOOD_EXPANSIONS: dict[str, str] = {
    "before": "take before food",
    "empty_stomach": "take on an empty stomach",
    "after": "take after food",
    "with": "take with food",
}


# ---------------------------------------------------------------------------
# Strength / dose
# ---------------------------------------------------------------------------

_STRENGTH_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(mg|mcg|\u00b5g|ug|international units|iu|g|kg|ml|%)",
    re.IGNORECASE,
)

#: A dose position that is clearly illegible: "?? mg", "___ mg", "** ml" ...
_UNREADABLE_DOSE_RE = re.compile(r"(?:(\?{1,3})|(_{2,})|(\*{2,}))\s*(mg|mcg|g|ml|iu|%)", re.IGNORECASE)

_UNIT_LABELS = {
    "mg": "mg", "mcg": "mcg", "\u00b5g": "mcg", "ug": "mcg",
    "international units": "IU", "iu": "IU", "g": "g", "kg": "kg", "ml": "ml", "%": "%",
}


# ---------------------------------------------------------------------------
# Duration
# ---------------------------------------------------------------------------

_DUR_RE = re.compile(r"\b(?:for\s+)?(\d+)\s+(days?|nights?|weeks?|months?)\b", re.IGNORECASE)
_DUR_X_RE = re.compile(r"\bx\s*(\d+)\s*(?:days?|nights?|d)\b", re.IGNORECASE)

_UNIT_DAYS = {"day": 1, "night": 1, "week": 7, "month": 30}


def _to_days(number: str, unit: str) -> int:
    key = unit.strip().lower().rstrip("s")
    return int(number) * _UNIT_DAYS[key]


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class ParsedField:
    """One extracted field: value, 0-1 confidence, and the source fragment."""

    value: str | None = None
    confidence: float = 0.0
    raw: str = ""


@dataclass
class ParsedLine:
    """Structured result of parsing one OCR line.

    ``conflicts`` holds human-readable notes about contradictory values found
    in the same line; the uncertainty gate turns them into "unclear".
    """

    source_text: str
    ocr_confidence: float = 100.0
    medicine_name: ParsedField = field(default_factory=ParsedField)
    strength: ParsedField = field(default_factory=ParsedField)
    form: ParsedField = field(default_factory=ParsedField)
    frequency: ParsedField = field(default_factory=ParsedField)
    food_timing: ParsedField = field(default_factory=ParsedField)
    duration_days: ParsedField = field(default_factory=ParsedField)
    conflicts: list[str] = field(default_factory=list)
    as_needed: bool = False
    slots: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _overlaps(span_a: tuple[int, int], span_b: tuple[int, int]) -> bool:
    return span_a[0] < span_b[1] and span_b[0] < span_a[1]


def slots_for_frequency(code: str | None) -> list[str]:
    """Fixed daily slots for a normalized frequency code ('1-0-1', 'TDS', ...).

    Public helper used by schedule.py and pdf.py. Returns [] for missing
    codes and for SOS (as-needed medicines never get a fixed slot/reminder).
    """
    if not code:
        return []
    if re.fullmatch(r"\d-\d-\d", code):
        return _nnn_slots(tuple(code.split("-")))
    return list(SLOT_MAP.get(code, []))


def _name_quality(name: str) -> float:
    """0-1 confidence that ``name`` is a plausible medicine name."""
    if not name:
        return 0.0
    if re.search(r"\?|_{2,}", name):
        return 0.2
    letters = sum(c.isalpha() for c in name)
    significant = len(name.replace(" ", "").replace("-", "").replace(".", ""))
    if significant == 0:
        return 0.2
    if letters / significant < 0.6:
        return 0.4
    if len(name) < 3:
        return 0.3
    return 0.9


def expand_abbreviations(text: str) -> list[str]:
    """Return glossary entries like ['TDS: three times a day'] found in text."""
    found: list[str] = []
    for abbr, expansion in ABBREVIATIONS.items():
        pattern = r"(?<![A-Za-z])" + re.escape(abbr) + r"(?![A-Za-z])"
        if re.search(pattern, text, flags=re.IGNORECASE):
            found.append(f"{abbr.upper()}: {expansion}")
    return found


def describe_frequency(code: str | None, as_needed: bool = False) -> str:
    """Plain-English description of a normalized frequency code."""
    if not code:
        return ""
    if code in ABBREVIATIONS:
        text = ABBREVIATIONS[code]
    elif re.fullmatch(r"\d-\d-\d", code):
        morning, afternoon, night = (int(p) for p in code.split("-"))
        parts = []
        if morning:
            parts.append(f"{morning} in the morning")
        if afternoon:
            parts.append(f"{afternoon} in the afternoon")
        if night:
            parts.append(f"{night} at night")
        text = "take " + ", ".join(parts) if parts else code
    else:
        text = code
    if as_needed:
        text += " — as needed"
    return text


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def parse_line(text: str, ocr_confidence: float = 100.0) -> ParsedLine:
    """Parse one OCR line into structured fields.

    Never raises on odd input: unknown/garbled values simply end up as
    ``value=None`` with low confidence, for the gate to judge.
    """
    line = ParsedLine(source_text=text.strip(), ocr_confidence=float(ocr_confidence))
    conflicts = line.conflicts

    # ------------------------------------------------------------------ form
    form_match = _FORM_START_RE.match(text)
    if form_match:
        raw_form = form_match.group(1).lower().rstrip(".")
        normalized = FORMS.get(raw_form)
        if normalized:
            line.form = ParsedField(value=normalized, confidence=0.9, raw=form_match.group(1))

    # --------------------------------------------------------------- strength
    strengths: list[tuple[int, int, str, str, float]] = []
    for m in _STRENGTH_RE.finditer(text):
        unit = _UNIT_LABELS[m.group(2).lower()]
        strengths.append((m.start(), m.end(), f"{m.group(1)} {unit}", m.group(0), 0.9))
    unreadable_doses = [m for m in _UNREADABLE_DOSE_RE.finditer(text)]

    distinct_strengths = {(s, u) for _, _, s, u, _ in strengths}
    if len(distinct_strengths) > 1:
        conflicts.append(
            "Conflicting values: two different doses found ("
            + ", ".join(sorted(f"{s} {u}" for s, u in distinct_strengths)) + ")"
        )
    if strengths:
        strengths.sort()
        _, _, value, raw, conf = strengths[0]
        line.strength = ParsedField(value=value, confidence=conf, raw=raw)
    elif unreadable_doses:
        # "?? mg" — there IS a dose position, but it is illegible.
        line.strength = ParsedField(value=None, confidence=0.2, raw=unreadable_doses[0].group(0))

    # -------------------------------------------------------------- frequency
    scheduled: list[tuple[int, str, str, float]] = []  # (start, code, raw, conf)
    for rx, code in _CODE_PATTERNS:
        for m in rx.finditer(text):
            scheduled.append((m.start(), code, m.group(0), 0.95))
    for rx, code in _FREQ_PHRASES:
        for m in rx.finditer(text):
            scheduled.append((m.start(), code, m.group(0), 0.85))
    for rx in (_TIMES_A_DAY_RE, _TIMES_DAILY_RE):
        for m in rx.finditer(text):
            code = _TIMES_TO_CODE.get(int(m.group(1)))
            if code:
                scheduled.append((m.start(), code, m.group(0), 0.85))
    for m in _NNN_RE.finditer(text):
        comps = (m.group(1), m.group(2), m.group(3))
        if any(c == "?" for c in comps):
            # Ambiguous pattern such as "1-?-1": report, do not choose slots.
            scheduled.append((m.start(), None, m.group(0), 0.2))
        elif all(c == "0" for c in comps):
            scheduled.append((m.start(), None, m.group(0), 0.2))  # zero doses — nonsensical
        else:
            normalized = "-".join(comps)
            scheduled.append((m.start(), normalized, m.group(0), 0.9))

    scheduled.sort(key=lambda item: item[0])
    # De-duplicate overlapping matches (e.g. phrase + contained code).
    deduped: list[tuple[int, str | None, str, float]] = []
    for start, code, raw, conf in scheduled:
        span = (start, start + len(raw))
        if any(_overlaps(span, (d[0], d[0] + len(d[2]))) for d in deduped):
            continue
        deduped.append((start, code, raw, conf))

    as_needed_match = next(
        (m for rx in _ASNEEDED_PATTERNS if (m := rx.search(text))), None
    )
    if as_needed_match:
        line.as_needed = True

    resolved_codes = {code for _, code, _, _ in deduped if code}
    if len(resolved_codes) > 1:
        conflicts.append(
            "Conflicting values: contradictory frequencies found ("
            + ", ".join(sorted(resolved_codes)) + ")"
        )
    if deduped:
        _, code, raw, conf = deduped[0]
        line.frequency = ParsedField(value=code, confidence=conf, raw=raw)
        if code and re.fullmatch(r"\d-\d-\d", code):
            line.slots = _nnn_slots(tuple(code.split("-")))
        elif code:
            line.slots = list(SLOT_MAP.get(code, []))
    elif as_needed_match:
        # SOS / PRN with no scheduled frequency: a valid frequency ("as needed")
        # with no fixed slot and therefore no reminder.
        line.frequency = ParsedField(
            value="SOS", confidence=0.9, raw=as_needed_match.group(0)
        )
        line.slots = []

    # ------------------------------------------------------------- food timing
    foods: list[tuple[int, str, str]] = []
    for rx, value in _FOOD_PATTERNS:
        for m in rx.finditer(text):
            foods.append((m.start(), value, m.group(0)))
    foods.sort(key=lambda item: item[0])
    food_values = {value for _, value, _ in foods}
    if "before" in food_values and ("after" in food_values or "with" in food_values):
        conflicts.append("Conflicting values: both before-food and after-food timing found")
    if foods:
        _, value, raw = foods[0]
        line.food_timing = ParsedField(value=value, confidence=0.9, raw=raw)

    # ---------------------------------------------------------------- duration
    durations: list[tuple[int, int, str]] = []  # (start, days, raw)
    for m in _DUR_RE.finditer(text):
        days = _to_days(m.group(1), m.group(2))
        durations.append((m.start(), days, m.group(0)))
    for m in _DUR_X_RE.finditer(text):
        days = int(m.group(1))
        if any(_overlaps((m.start(), m.end()), (d[0], d[0] + len(d[2]))) for d in durations):
            continue
        durations.append((m.start(), days, m.group(0)))
    durations.sort(key=lambda item: item[0])
    deduped_durations: list[tuple[int, int, str]] = []
    for start, days, raw in durations:
        span = (start, start + len(raw))
        if any(_overlaps(span, (d[0], d[0] + len(d[2]))) for d in deduped_durations):
            continue
        deduped_durations.append((start, days, raw))
    if deduped_durations:
        first_days = deduped_durations[0][1]
        if any(d[1] != first_days for d in deduped_durations):
            conflicts.append(
                "Conflicting values: two different durations found ("
                + ", ".join(str(d[1]) for d in deduped_durations) + " days)"
            )
        _, days, raw = deduped_durations[0]
        line.duration_days = ParsedField(value=str(days), confidence=0.9, raw=raw)

    # ------------------------------------------------------------ medicine name
    # The name is everything between a leading form word and the earliest
    # structured anchor (strength / frequency / food / duration).
    name_start = form_match.end() if form_match else 0
    anchors: list[int] = []
    if strengths:
        anchors.append(strengths[0][0])
    elif unreadable_doses:
        # "?? mg" occupies the dose position — keep the name from swallowing it.
        anchors.append(min(m.start() for m in unreadable_doses))
    if deduped:
        anchors.append(deduped[0][0])
    if foods:
        anchors.append(foods[0][0])
    if deduped_durations:
        anchors.append(deduped_durations[0][0])
    name_end = min(anchors) if anchors else len(text)

    name = text[name_start:name_end].strip(" \t,;:")
    name = re.sub(r"\s+", " ", name)
    qty = _LEADING_QUANTITY_RE.match(name)
    if qty:
        name = name[qty.end():].strip(" \t,;:")
    line.medicine_name = ParsedField(
        value=name or None, confidence=_name_quality(name), raw=name
    )

    return line


# ---------------------------------------------------------------------------
# Structured medicine synthesis (Gemini Vision path, Part 3)
# ---------------------------------------------------------------------------

#: Local clock windows -> fixed daily slot (night wraps past midnight).
_SLOT_HOURS: tuple[tuple[str, int, int], ...] = (
    ("morning", 5, 11),
    ("afternoon", 11, 16),
    ("evening", 16, 21),
    ("night", 21, 5),
)


def _clock_hour(value: object) -> int | None:
    """Best-effort hour (0-23) from '08:00', '8 am', '21.30' … or None."""
    text = str(value or "").strip().lower()
    if not text:
        return None
    match = re.search(r"\b(\d{1,2})(?::|\.)(\d{2})\b", text)
    if match:
        hour = int(match.group(1)) % 24
        if re.search(r"\bpm\b", text) and hour < 12:
            hour += 12
        if re.search(r"\bam\b", text) and hour == 12:
            hour = 0
        return hour % 24
    match = re.search(r"\b(\d{1,2})\s*(am|pm)\b", text)
    if match:
        hour = int(match.group(1)) % 12
        if match.group(2) == "pm":
            hour += 12
        return hour % 24
    return None


def _slot_for_hour(hour: int) -> str:
    for slot, start, end in _SLOT_HOURS:
        if start <= end:
            if start <= hour < end:
                return slot
        elif hour >= start or hour < end:  # night wraps midnight
            return slot
    return "morning"


def _frequency_token(frequency: object, times: object) -> str | None:
    """Normalized frequency code for a structured medicine (or None).

    Prefers the model's own frequency text when it maps onto the parser's
    vocabulary; otherwise derives a code from the explicit intake times.
    Returning None is deliberate — a missing frequency makes the gate mark
    the line unclear instead of inventing a schedule.
    """
    text = str(frequency or "").strip()
    if text:
        if re.fullmatch(r"\d-\d-\d", text):
            return text
        for rx, code in _CODE_PATTERNS:
            if rx.search(text):
                return code
        for rx, code in _FREQ_PHRASES:
            if rx.search(text):
                return code
        if re.search(r"\b(?:SOS|PRN)\b", text, re.IGNORECASE) or re.search(
            r"\bas\s+needed\b|\bwhen\s+required\b", text, re.IGNORECASE
        ):
            return "SOS"
        match = _TIMES_A_DAY_RE.search(text) or _TIMES_DAILY_RE.search(text)
        if match:
            code = _TIMES_TO_CODE.get(int(match.group(1)))
            if code:
                return code
        lowered = text.lower()
        for word, count in (("once", 1), ("twice", 2), ("thrice", 3)):
            if word in lowered:
                return _TIMES_TO_CODE.get(count)
        match = re.search(r"\b(\d{1,2})\s*(?:x|times)\b", text, re.IGNORECASE)
        if match:
            return _TIMES_TO_CODE.get(int(match.group(1)))
        # unrecognized free-form frequency -> fall through to explicit times

    if isinstance(times, str):
        times = re.split(r"[,;/\s]+", times)
    slots: list[str] = []
    for value in times or []:
        hour = _clock_hour(value)
        if hour is None:
            continue
        slot = _slot_for_hour(hour)
        if slot not in slots:
            slots.append(slot)
    if not slots:
        return None
    if len(slots) == 1:
        return "HS" if slots[0] == "night" else "OD"
    return _TIMES_TO_CODE.get(len(slots))


def _meal_token(meal: object) -> str:
    """Food-timing phrase the parser recognizes, from free-form model text."""
    text = str(meal or "").strip().lower()
    if not text:
        return ""
    if "empty" in text:
        return "on an empty stomach"
    if "before" in text:
        return "before food"
    if "after" in text:
        return "after food"
    if "with" in text:
        return "with food"
    return ""


def _form_token(form: object) -> str:
    return FORMS.get(str(form or "").strip().lower().rstrip("."), "") or ""


def _dosage_token(dosage: object) -> str:
    """The dosage string only when it contains a real strength ('500 mg')."""
    text = str(dosage or "").strip()
    if not text or not _STRENGTH_RE.search(text):
        return ""
    return text


def synthesize_medicine_line(medicine: Mapping[str, Any]) -> str | None:
    """One parseable prescription line from a structured medicine row.

    The Gemini Vision path produces structured JSON; this turns each row
    back into the same line format Tesseract output uses, so it flows
    through the identical extract -> parse -> gate pipeline. The gate — not
    the model — still decides clear/unclear. Returns None when the row has
    no usable medicine name (nothing a human could review).
    """
    name = str(medicine.get("name") or "").strip()
    if not name:
        return None
    parts: list[str] = []
    form = _form_token(medicine.get("form"))
    if form:
        parts.append(form)
    parts.append(name)
    dosage = _dosage_token(medicine.get("dosage"))
    if dosage:
        parts.append(dosage)
    frequency = _frequency_token(medicine.get("frequency"), medicine.get("times"))
    if frequency:
        parts.append(frequency)
    meal = _meal_token(medicine.get("meal_instruction"))
    if meal:
        parts.append(meal)
    try:
        duration = int(medicine.get("duration_days") or 0)
    except (TypeError, ValueError):
        duration = 0
    if duration > 0:
        parts.append(f"x {duration} days")
    return " ".join(parts)


def synthesize_medicine_lines(
    medicines: Iterable[Mapping[str, Any]],
) -> list[tuple[str, float]]:
    """(line, confidence 0-100) pairs for structured medicine rows.

    A row the model flagged (``uncertainty_reason``) is capped below the
    gate's 70% threshold, so it is surfaced for human confirmation instead
    of being trusted — the model's confidence can never promote a line.
    """
    lines: list[tuple[str, float]] = []
    for medicine in medicines:
        line = synthesize_medicine_line(medicine)
        if line is None:
            continue
        try:
            confidence = float(medicine.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = min(max(confidence, 0.0), 1.0)
        if medicine.get("uncertainty_reason"):
            confidence = min(confidence, 0.69)
        lines.append((line, round(confidence * 100, 1)))
    return lines
