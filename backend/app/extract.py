"""Candidate medicine line extraction for MedRecall.

Takes raw OCR lines and selects the ones that plausibly describe a medicine,
while skipping prescription headers: clinic/hospital name, doctor and
pharmacist names, date, patient name/age, "Rx", advice lines, bill totals,
etc.

Heuristics (a line is a candidate when ANY holds):
  * it starts with a dosage-form word (Tab/Cap/Syp/Inj/...), or
  * it contains an N-N-N frequency pattern (1-0-1), or
  * it contains both a dose (500 mg / 5 ml / ...) AND a frequency
    (OD/BD/TDS/QID/HS/SOS/PRN or a "twice daily" style phrase).

Everything else is skipped — being conservative here is safe: a skipped
header line can never leak medicine advice, and a real medicine line almost
always carries a dose + frequency.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .ocr import OcrLine
from .parser import _FREQ_PHRASES, _NNN_RE, _STRENGTH_RE, _TIMES_A_DAY_RE, _TIMES_DAILY_RE, _CODE_PATTERNS

# ---------------------------------------------------------------------------
# Header / non-medicine line detection
# ---------------------------------------------------------------------------

_HEADER_PATTERNS: list[re.Pattern] = [
    re.compile(r"^(date|dob|patient|age|sex|gender|diagnosis|advice|note|notes|"
               r"clinic|hospital|ward|opd|ipd|bill|invoice|total|amount|page|phone|"
               r"mobile|reg\.? no)\b", re.IGNORECASE),
    re.compile(r"^(dr\.?|doctor|pharmacist|prescriber|md\b)\b", re.IGNORECASE),
    re.compile(r"^(rx|℞|prescription)\b", re.IGNORECASE),
    re.compile(r"^\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}$"),  # bare date
    re.compile(r"^(thank|finish the|complete the|take care|stay hydrated|"
               r"drink plenty|avoid|review after|review in)", re.IGNORECASE),
    re.compile(r"^\d+$"),  # bare number (page number, quantity alone)
]

#: Lines that are obviously NOT medicine lines even if they look structured.
_ADVICE_START_RE = re.compile(r"^(advice|instruction|note)\s*:", re.IGNORECASE)

#: Dosage-form words anywhere in a line (used to avoid silently dropping a
#: line whose beginning the OCR garbled while the form word survived).
_FORM_WORD_ANY_RE = re.compile(
    r"\b(d/cap|tabs?|tablets?|caps?|capsules?|syp|syr|syrup|inj|injection|"
    r"susp|drops?|ointment|inhaler|supp|cream|gel|sachet|vial)\b",
    re.IGNORECASE,
)


def is_header_line(text: str) -> bool:
    """True if the line looks like prescription header/noise, not a medicine."""
    stripped = text.strip()
    if not stripped:
        return True
    if _ADVICE_START_RE.match(stripped):
        return True
    return any(rx.match(stripped) for rx in _HEADER_PATTERNS)


def looks_like_medicine_line(text: str) -> bool:
    """True if the line plausibly describes a medicine."""
    stripped = text.strip()
    if not stripped or len(stripped) < 5:
        return False

    # 1) starts with a dosage form
    if re.match(
        r"^\s*(d/cap|tab|tabs|tablet|tablets|cap|caps|capsule|capsules|syp|syr|syrup|"
        r"inj|injection|susp|suspension|drops|drop|oint|ointment|inhaler|supp|"
        r"suppository|cream|gel|sachet|vial)[\.\s]",
        stripped,
        re.IGNORECASE,
    ):
        return True

    # 2) contains an N-N-N pattern
    if _NNN_RE.search(stripped):
        return True

    # 3) dose + frequency together
    has_dose = bool(_STRENGTH_RE.search(stripped))
    has_frequency = bool(
        any(rx.search(stripped) for rx, _ in _CODE_PATTERNS)
        or any(rx.search(stripped) for rx, _ in _FREQ_PHRASES)
        or _TIMES_A_DAY_RE.search(stripped)
        or _TIMES_DAILY_RE.search(stripped)
        or re.search(r"\b(?:SOS|PRN)\b", stripped)
        or re.search(r"\bas\s+needed\b", stripped, re.IGNORECASE)
    )
    if has_dose and has_frequency:
        return True

    # 4) dosage form mentioned ANYWHERE + at least one structured hint.
    #    Safety: OCR sometimes mangles the start of a line ("Syp" -> "59५7")
    #    while leaving "Cough Syrup ... TDS SOS". Such a line must become an
    #    UNCLEAR candidate (user confirms/edits it) — never be silently dropped.
    if _FORM_WORD_ANY_RE.search(stripped) and (has_dose or has_frequency or _NNN_RE.search(stripped)):
        return True

    return False


@dataclass
class CandidateLine:
    """A line that probably describes a medicine, with its position in the
    original document (1-based, for the "Line 3" display in the review UI)."""

    text: str
    confidence: float
    line_number: int


def extract_medicine_lines(ocr_lines: list[OcrLine]) -> list[CandidateLine]:
    """Filter OCR lines down to candidate medicine lines."""
    candidates: list[CandidateLine] = []
    for index, ocr_line in enumerate(ocr_lines, start=1):
        text = ocr_line.text.strip()
        if not text:
            continue
        if is_header_line(text):
            continue
        if looks_like_medicine_line(text):
            candidates.append(CandidateLine(text=text, confidence=ocr_line.confidence, line_number=index))
    return candidates
