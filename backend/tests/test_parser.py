"""Parser tests: every frequency format, food timing, duration, names, forms."""

from __future__ import annotations

import pytest

from app.parser import (
    ABBREVIATIONS,
    SLOT_MAP,
    describe_frequency,
    expand_abbreviations,
    parse_line,
    slots_for_frequency,
)

# ---------------------------------------------------------------------------
# Frequency formats
# ---------------------------------------------------------------------------

FREQUENCY_CASES = [
    # (line, expected frequency code, expected slots)
    ("Tab Paracetamol 500 mg 1-0-1", "1-0-1", ["morning", "night"]),
    ("Tab Paracetamol 500 mg 1-1-1", "1-1-1", ["morning", "afternoon", "night"]),
    ("Tab Paracetamol 500 mg 0-0-1", "0-0-1", ["night"]),
    ("Tab Paracetamol 500 mg 1-1-0", "1-1-0", ["morning", "afternoon"]),
    ("Tab Paracetamol 500 mg OD", "OD", ["morning"]),
    ("Tab Paracetamol 500 mg BD", "BD", ["morning", "night"]),
    ("Tab Paracetamol 500 mg BID", "BD", ["morning", "night"]),
    ("Tab Paracetamol 500 mg TDS", "TDS", ["morning", "afternoon", "night"]),
    ("Tab Paracetamol 500 mg TID", "TDS", ["morning", "afternoon", "night"]),
    ("Tab Paracetamol 500 mg QID", "QID", ["morning", "afternoon", "evening", "night"]),
    ("Tab Paracetamol 500 mg HS", "HS", ["night"]),
    ("Tab Paracetamol 500 mg SOS", "SOS", []),
    ("Tab Paracetamol 500 mg PRN", "SOS", []),
    ("Tab Paracetamol 500 mg once a day", "OD", ["morning"]),
    ("Tab Paracetamol 500 mg twice daily", "BD", ["morning", "night"]),
    ("Tab Paracetamol 500 mg three times a day", "TDS", ["morning", "afternoon", "night"]),
    ("Tab Paracetamol 500 mg four times a day", "QID", ["morning", "afternoon", "evening", "night"]),
    ("Tab Paracetamol 500 mg at bedtime", "HS", ["night"]),
    ("Tab Paracetamol 500 mg 2 times a day", "BD", ["morning", "night"]),
]


@pytest.mark.parametrize("text,code,slots", FREQUENCY_CASES)
def test_frequency_formats(text, code, slots):
    parsed = parse_line(text, ocr_confidence=95)
    assert parsed.frequency.value == code, f"{text!r} -> {parsed.frequency.value}"
    assert parsed.slots == slots, f"{text!r} slots -> {parsed.slots}"


@pytest.mark.parametrize("text", ["Tab A 100 mg SOS", "Tab A 100 mg PRN", "Tab A 100 mg as needed"])
def test_as_needed_flag(text):
    assert parse_line(text, 95).as_needed is True


def test_sos_alone_has_no_fixed_slot_and_no_reminder_slot():
    parsed = parse_line("Tab A 100 mg SOS", 95)
    assert parsed.slots == []
    assert slots_for_frequency(parsed.frequency.value) == []


def test_tds_with_sos_is_marked_as_needed_but_keeps_tds():
    parsed = parse_line("Syp Cough Syrup 5 ml TDS SOS", 95)
    assert parsed.frequency.value == "TDS"
    assert parsed.as_needed is True


def test_ambiguous_frequency_1_q_1_has_no_value():
    parsed = parse_line("Tab A 500 mg 1-?-1", 95)
    assert parsed.frequency.value is None
    assert "1-?-1" in parsed.frequency.raw
    assert parsed.slots == []


def test_conflicting_frequencies_are_reported():
    parsed = parse_line("Tab A 500 mg OD TDS", 95)
    assert any("Conflicting values" in c for c in parsed.conflicts)


def test_zero_dose_pattern_is_ambiguous():
    parsed = parse_line("Tab A 500 mg 0-0-0", 95)
    assert parsed.frequency.value is None
    assert parsed.slots == []


# ---------------------------------------------------------------------------
# Slot mapping helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("code,slots", [
    ("OD", ["morning"]),
    ("BD", ["morning", "night"]),
    ("TDS", ["morning", "afternoon", "night"]),
    ("QID", ["morning", "afternoon", "evening", "night"]),
    ("HS", ["night"]),
    ("SOS", []),
    ("1-0-1", ["morning", "night"]),
    ("0-0-1", ["night"]),
    (None, []),
    ("", []),
])
def test_slots_for_frequency(code, slots):
    assert slots_for_frequency(code) == slots


def test_slot_map_covers_all_codes():
    assert set(SLOT_MAP) == {"OD", "BD", "TDS", "QID", "HS", "SOS"}


# ---------------------------------------------------------------------------
# Food timing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text,expected", [
    ("Tab A 100 mg OD AC", "before"),
    ("Tab A 100 mg OD before food", "before"),
    ("Tab A 100 mg OD before meals", "before"),
    ("Tab A 100 mg OD PC", "after"),
    ("Tab A 100 mg OD after food", "after"),
    ("Tab A 100 mg OD after meals", "after"),
    ("Tab A 100 mg OD with food", "with"),
    ("Tab A 100 mg OD empty stomach", "empty_stomach"),
    ("Tab A 100 mg OD", None),
])
def test_food_timing(text, expected):
    assert parse_line(text, 95).food_timing.value == expected


def test_conflicting_food_timing_reported():
    parsed = parse_line("Tab A 100 mg OD before food after food", 95)
    assert any("Conflicting values" in c for c in parsed.conflicts)


# ---------------------------------------------------------------------------
# Duration
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text,expected", [
    ("Tab A 100 mg OD x 5 days", "5"),
    ("Tab A 100 mg OD x 5 days", "5"),
    ("Tab A 100 mg OD for 1 week", "7"),
    ("Tab A 100 mg OD for 2 weeks", "14"),
    ("Tab A 100 mg OD for 10 days", "10"),
    ("Tab A 100 mg OD for 1 month", "30"),
    ("Tab A 100 mg OD", None),
])
def test_duration_parsing(text, expected):
    assert parse_line(text, 95).duration_days.value == expected


def test_conflicting_durations_reported():
    parsed = parse_line("Tab A 100 mg OD for 5 days x 10 days", 95)
    assert any("Conflicting values" in c for c in parsed.conflicts)


# ---------------------------------------------------------------------------
# Medicine name, strength, form
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text,name", [
    ("Tab Paracetamol 500 mg 1-0-1", "Paracetamol"),
    ("Cap Amoxicillin 250 mg 1-1-1", "Amoxicillin"),
    ("Syp Cough Syrup 5 ml TDS", "Cough Syrup"),
    ("Paracetamol 500 mg OD", "Paracetamol"),
    ("1 tab Paracetamol 500 mg OD", "Paracetamol"),
])
def test_medicine_name_extraction(text, name):
    assert parse_line(text, 95).medicine_name.value == name


@pytest.mark.parametrize("text,form", [
    ("Tab A 100 mg OD", "tab"),
    ("Capsule A 100 mg OD", "cap"),
    ("Syp Syrup 5 ml TDS", "syrup"),
    ("Inj A 100 mg OD", "inj"),
])
def test_form_extraction(text, form):
    assert parse_line(text, 95).form.value == form


@pytest.mark.parametrize("text,strength", [
    ("Tab A 500 mg OD", "500 mg"),
    ("Tab A 250 mg OD", "250 mg"),
    ("Syp Syrup 5 ml TDS", "5 ml"),
    ("Tab A 1000 mg OD", "1000 mg"),
    ("Tab A 1.5 g OD", "1.5 g"),
])
def test_strength_extraction(text, strength):
    assert parse_line(text, 95).strength.value == strength


def test_unreadable_dose_has_no_value_but_raw_present():
    parsed = parse_line("Tab Cetirizine ?? mg 0-0-1", 95)
    assert parsed.strength.value is None
    assert parsed.strength.raw == "?? mg"


def test_missing_dose_has_empty_raw():
    parsed = parse_line("Tab Cetirizine 0-0-1", 95)
    assert parsed.strength.value is None
    assert parsed.strength.raw == ""


def test_two_different_doses_conflict():
    parsed = parse_line("Tab A 500 mg 250 mg OD", 95)
    assert any("Conflicting values" in c for c in parsed.conflicts)


# ---------------------------------------------------------------------------
# Abbreviation glossary + descriptions
# ---------------------------------------------------------------------------

REQUIRED_ABBREVIATIONS = ["BD", "TDS", "QID", "OD", "HS", "SOS", "AC", "PC",
                          "tab", "cap", "syp", "inj"]


@pytest.mark.parametrize("abbr", REQUIRED_ABBREVIATIONS)
def test_abbreviation_dictionary_complete(abbr):
    assert abbr in ABBREVIATIONS
    assert len(ABBREVIATIONS[abbr]) > 3  # plain-English expansion, not empty


def test_expand_abbreviations_lists_all_found():
    text = "OD BD TDS QID HS SOS AC PC tab cap syp inj"
    expansions = expand_abbreviations(text)
    for abbr in REQUIRED_ABBREVIATIONS:
        assert any(e.startswith(abbr.upper() + ":") for e in expansions), abbr


def test_describe_frequency_plain_english():
    assert describe_frequency("OD") == "once a day"
    assert describe_frequency("TDS") == "three times a day"
    assert "morning" in describe_frequency("1-0-1")
    assert "as needed" in describe_frequency("BD", as_needed=True)
    assert describe_frequency(None) == ""


# ---------------------------------------------------------------------------
# Robustness: never raise on garbage
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["", "???", "###", "\x00\x01", "Rx",
                                  "12-34-56", "500 mg only", "Date: 14/11/2026"])
def test_parse_never_raises_on_garbage(text):
    parsed = parse_line(text, 50)
    assert parsed.source_text is not None
    assert parsed.medicine_name.confidence <= 1.0
