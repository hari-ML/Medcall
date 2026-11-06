"""Extract tests: headers skipped, medicine lines kept — and garbled lines
are NEVER silently dropped (they must become unclear candidates)."""

from __future__ import annotations

import pytest

from app.extract import extract_medicine_lines, is_header_line, looks_like_medicine_line
from app.ocr import OcrLine
from app.parser import parse_line
from app.uncertainty import STATUS_UNCLEAR, gate


def _lines(*texts: str, confidence: float = 92.0) -> list[OcrLine]:
    return [OcrLine(text=t, confidence=confidence) for t in texts]


FULL_PRESCRIPTION = """City General Hospital
Dr. Meera Raghavan
Date: 15/11/2026
Patient: Ramanathan S. (68)

Rx
Tab Paracetamol 500 mg 1-0-1 after food x 5 days
Cap Amoxicillin 250 mg 1-1-1 x 5 days
Tab Cetirizine ?? mg 0-0-1
Syp Cough Syrup 5 ml TDS SOS
Advice: Complete the full course"""


def test_extracts_only_medicine_lines_with_positions():
    lines = _lines(*FULL_PRESCRIPTION.splitlines())
    candidates = extract_medicine_lines(lines)
    assert len(candidates) == 4
    # 1-based positions within the OCR output (the blank line is present here,
    # unlike real Tesseract output which omits empty lines)
    assert [c.text.split()[1] for c in candidates] == ["Paracetamol", "Amoxicillin",
                                                       "Cetirizine", "Cough"]
    assert [c.line_number for c in candidates] == [7, 8, 9, 10]


@pytest.mark.parametrize("text", [
    "City General Hospital",
    "Dr. Meera Raghavan",
    "Date: 15/11/2026",
    "Patient: Ramanathan S. (68)",
    "Rx",
    "Advice: Complete the full course",
    "Pharmacist: R. Iyer",
    "",
])
def test_headers_and_noise_skipped(text):
    assert is_header_line(text) or not looks_like_medicine_line(text)


@pytest.mark.parametrize("text", [
    "Tab Paracetamol 500 mg 1-0-1 after food x 5 days",
    "Cap Amoxicillin 250 mg 1-1-1 x 5 days",
    "Syp Cough Syrup 5 ml TDS SOS",
    "Paracetamol 625 mg OD",              # no form word, but dose + frequency
    "1 tab Pantoprazole 40 mg BD",        # leading quantity
])
def test_medicine_lines_detected(text):
    assert looks_like_medicine_line(text)


def test_mangled_line_is_never_dropped():
    """Real OCR artifact (observed on a 26 px render): the line opening is
    garbled ('Syp' -> '59५7', '5 ml' -> '57') but the form word, medicine and
    frequency survive. It must surface as an UNCLEAR candidate so the user
    confirms/edits it — silent omission would hide a real medicine."""
    garbled = "59५7 Cough Syrup 57 TDS SOS"
    assert looks_like_medicine_line(garbled), "garbled line was silently dropped"

    candidates = extract_medicine_lines(_lines("x", "y", garbled))
    assert len(candidates) == 1
    assert candidates[0].line_number == 3

    parsed = parse_line(candidates[0].text, candidates[0].confidence)
    result = gate(parsed)
    assert result.status == STATUS_UNCLEAR, "garbled line must be gated as unclear"
    assert result.reason


def test_noise_with_form_word_but_no_hint_still_skipped():
    # a form word in the MIDDLE of a prose line (no dose/frequency hint) is not
    # enough to create a candidate (a form word at line START is rule 1)
    assert not looks_like_medicine_line("Patients can collect their Syrup from the pharmacy")
    # ...while a line starting with a form word IS a candidate (rule 1) and the
    # uncertainty gate will mark it unclear if the dose/frequency are absent
    assert looks_like_medicine_line("Syrup is available at the counter today")
