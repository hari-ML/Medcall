"""Uncertainty gate for MedRecall — THE safety rule.

Every parsed prescription line passes through :func:`gate` exactly once.
The gate marks a line ``"unclear"`` (with human-readable reasons) if ANY of
these hold:

* OCR confidence < 70
* dose/strength missing, or contains "?" / garbage characters
* frequency missing or ambiguous (e.g. "1-?-1")
* medicine name too short, mostly non-alphabetic, or unresolved characters
* conflicting values in the same line (two doses, two frequencies, ...)

Status lifecycle:
    clear | unclear   <- produced ONLY by this module (from parsing)
    confirmed | edited <- produced ONLY by the confirm/edit API endpoint
                          (after the user acted on an unclear line)

There is NO code path that promotes ``unclear`` to ``clear`` automatically.
Only items whose status is in :data:`SCHEDULEABLE_STATUSES` may be translated,
scheduled, printed to PDF, or used for reminders.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .parser import ParsedLine

# ---------------------------------------------------------------------------
# Status vocabulary (single source of truth for the whole backend)
# ---------------------------------------------------------------------------

STATUS_CLEAR = "clear"
STATUS_UNCLEAR = "unclear"
STATUS_CONFIRMED = "confirmed"
STATUS_EDITED = "edited"

#: The ONLY statuses allowed into translation / schedule / PDF / reminders.
SCHEDULEABLE_STATUSES = frozenset({STATUS_CLEAR, STATUS_CONFIRMED, STATUS_EDITED})

#: OCR confidence threshold (0-100) below which a line is unclear.
MIN_OCR_CONFIDENCE = 70.0

# ---------------------------------------------------------------------------
# Human-readable reason constants
# ---------------------------------------------------------------------------

REASON_LOW_CONFIDENCE = "Low OCR confidence"
REASON_DOSE_MISSING = "Dose missing"
REASON_DOSE_UNREADABLE = "Dose unreadable"
REASON_FREQUENCY_MISSING = "Frequency missing"
REASON_FREQUENCY_AMBIGUOUS = "Frequency ambiguous"
REASON_NAME_UNCLEAR = "Medicine name unclear"


@dataclass
class GateResult:
    status: str
    reasons: list[str] = field(default_factory=list)

    @property
    def reason(self) -> str:
        """Combined human-readable reason (empty when status is 'clear')."""
        return "; ".join(self.reasons)

    def __bool__(self) -> bool:
        return self.status == STATUS_CLEAR


def gate(line: ParsedLine) -> GateResult:
    """Run the uncertainty gate on a parsed line.

    Returns ``GateResult(status="clear")`` or ``GateResult(status="unclear",
    reasons=[...])``. Never raises on malformed input.
    """
    reasons: list[str] = []

    # 1. OCR confidence -----------------------------------------------------
    if line.ocr_confidence < MIN_OCR_CONFIDENCE:
        reasons.append(f"{REASON_LOW_CONFIDENCE} ({int(line.ocr_confidence)} < {int(MIN_OCR_CONFIDENCE)})")

    # 2. Dose / strength ----------------------------------------------------
    if line.strength.value is None:
        if line.strength.raw:
            reasons.append(REASON_DOSE_UNREADABLE)  # e.g. "?? mg"
        else:
            reasons.append(REASON_DOSE_MISSING)

    # 3. Frequency ----------------------------------------------------------
    if line.frequency.value is None:
        if line.frequency.raw:
            reasons.append(f"{REASON_FREQUENCY_AMBIGUOUS} ({line.frequency.raw})")
        else:
            reasons.append(REASON_FREQUENCY_MISSING)

    # 4. Medicine name ------------------------------------------------------
    if not line.medicine_name.value or line.medicine_name.confidence < 0.6:
        reasons.append(REASON_NAME_UNCLEAR)

    # 5. Conflicting values reported by the parser ---------------------------
    reasons.extend(line.conflicts)

    if reasons:
        return GateResult(status=STATUS_UNCLEAR, reasons=reasons)
    return GateResult(status=STATUS_CLEAR)


def gate_source_text(source_text: str, ocr_confidence: float = 100.0) -> GateResult:
    """Convenience: parse raw text and gate it in one call.

    Used by the edit endpoint: user-edited lines are re-parsed and re-gated,
    so an edit can never bypass the safety rule.
    """
    from .parser import parse_line  # local import to avoid a cycle

    return gate(parse_line(source_text, ocr_confidence=ocr_confidence))
