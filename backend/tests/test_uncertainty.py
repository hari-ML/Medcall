"""Uncertainty gate tests: every failure case + safety invariants."""

from __future__ import annotations

import pytest

from app.parser import parse_line
from app.uncertainty import (
    MIN_OCR_CONFIDENCE,
    REASON_DOSE_MISSING,
    REASON_DOSE_UNREADABLE,
    REASON_FREQUENCY_AMBIGUOUS,
    REASON_FREQUENCY_MISSING,
    REASON_LOW_CONFIDENCE,
    REASON_NAME_UNCLEAR,
    SCHEDULEABLE_STATUSES,
    STATUS_CLEAR,
    STATUS_UNCLEAR,
    gate,
    gate_source_text,
)


@pytest.mark.parametrize("line,confidence,reason", [
    # 1. OCR confidence < 70
    ("Tab Paracetamol 500 mg 1-0-1", 69, REASON_LOW_CONFIDENCE),
    ("Tab Paracetamol 500 mg 1-0-1", 0, REASON_LOW_CONFIDENCE),
    # 2. dose problems
    ("Tab Paracetamol 1-0-1", 95, REASON_DOSE_MISSING),
    ("Tab Cetirizine ?? mg 0-0-1", 95, REASON_DOSE_UNREADABLE),
    ("Tab Cetirizine ___ mg 0-0-1", 95, REASON_DOSE_UNREADABLE),
    # 3. frequency problems
    ("Tab Paracetamol 500 mg", 95, REASON_FREQUENCY_MISSING),
    ("Tab Paracetamol 500 mg 1-?-1", 95, REASON_FREQUENCY_AMBIGUOUS),
    # 4. medicine name problems
    ("Tab X 500 mg 1-0-1", 95, REASON_NAME_UNCLEAR),
    ("Tab 500 mg 1-0-1", 95, REASON_NAME_UNCLEAR),
    ("Tab 99x## 500 mg 1-0-1", 95, REASON_NAME_UNCLEAR),
    # 5. conflicting values in the same line
    ("Tab Paracetamol 500 mg OD TDS", 95, "Conflicting values"),
    ("Tab Paracetamol 500 mg 250 mg OD", 95, "Conflicting values"),
    ("Tab Paracetamol 500 mg OD before food after food", 95, "Conflicting values"),
])
def test_every_gate_failure_case(line, confidence, reason):
    result = gate(parse_line(line, confidence))
    assert result.status == STATUS_UNCLEAR, f"{line!r} should be unclear"
    assert any(reason in r for r in result.reasons), (
        f"expected reason containing {reason!r}, got {result.reasons}"
    )
    assert result.reason  # human-readable string is non-empty


@pytest.mark.parametrize("line,confidence", [
    ("Tab Paracetamol 500 mg 1-0-1 after food x 5 days", 95),
    ("Cap Amoxicillin 250 mg 1-1-1 x 5 days", 95),
    ("Syp Cough Syrup 5 ml TDS SOS", 95),
    ("Tab Paracetamol 500 mg 1-0-1", 70),  # exactly at the threshold
])
def test_clean_lines_are_clear(line, confidence):
    assert gate(parse_line(line, confidence)).status == STATUS_CLEAR


def test_confidence_boundary():
    assert gate(parse_line("Tab Paracetamol 500 mg 1-0-1", 69.9)).status == STATUS_UNCLEAR
    assert gate(parse_line("Tab Paracetamol 500 mg 1-0-1", 70.0)).status == STATUS_CLEAR


def test_threshold_is_70():
    assert MIN_OCR_CONFIDENCE == 70


def test_multiple_reasons_are_all_reported():
    # low OCR confidence + unreadable dose + missing frequency value
    result = gate(parse_line("Tab ???", 50))
    assert result.status == STATUS_UNCLEAR
    assert len(result.reasons) >= 2, result.reasons


# ---------------------------------------------------------------------------
# Safety invariants
# ---------------------------------------------------------------------------


def test_gate_only_ever_returns_clear_or_unclear():
    samples = [
        "", "???", "Tab A 500 mg 1-0-1", "Tab A 500 mg",
        "Tab Cetirizine ?? mg 0-0-1", "Date: 14/11/2026", "\x00",
        "Tab A 500 mg OD TDS", "Rx",
    ]
    statuses = {gate(parse_line(text, 95)).status for text in samples}
    assert statuses <= {STATUS_CLEAR, STATUS_UNCLEAR}, statuses


def test_unclear_is_not_scheduleable():
    assert STATUS_UNCLEAR not in SCHEDULEABLE_STATUSES


def test_scheduleable_set_is_exactly_the_safe_statuses():
    assert SCHEDULEABLE_STATUSES == {"clear", "confirmed", "edited"}


def test_gate_source_text_convenience():
    assert gate_source_text("Tab Paracetamol 500 mg 1-0-1", 95).status == STATUS_CLEAR
    assert gate_source_text("Tab Cetirizine ?? mg 0-0-1", 95).status == STATUS_UNCLEAR


def test_gate_result_helpers():
    clear = gate_source_text("Tab Paracetamol 500 mg 1-0-1", 95)
    unclear = gate_source_text("Tab Paracetamol 1-0-1", 95)
    assert bool(clear) is True
    assert bool(unclear) is False
    assert clear.reason == ""
    assert unclear.reason


def test_single_letter_medicine_name_is_unclear():
    # "Tab A 500 mg OD" — a one-letter name is too short to trust (spec rule)
    assert gate_source_text("Tab A 500 mg OD", 95).status == STATUS_UNCLEAR
    assert REASON_NAME_UNCLEAR in gate_source_text("Tab A 500 mg OD", 95).reasons
