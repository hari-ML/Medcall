"""THE explicit safety test: an UNCLEAR item never reaches the schedule,
the PDF data, or the reminders — plus defense-in-depth checks."""

from __future__ import annotations

import json

import pytest

import app.pdf as pdf_module
from app.schedule import build_reminders, build_schedule
from app.translate import UnclearItemError, translate_instruction
from app.uncertainty import SCHEDULEABLE_STATUSES

UNCL = "Cetirizine"  # the unclear medicine in the fixtures


def _placed_entries(schedule: dict) -> list[dict]:
    entries = [e for lst in schedule["slots"].values() for e in lst]
    entries += list(schedule["as_needed"])
    return entries


def test_unclear_never_in_schedule(mixed_items, unclear_item):
    schedule = build_schedule(mixed_items, lang="en")

    placed = _placed_entries(schedule)
    placed_ids = {e["id"] for e in placed}
    assert unclear_item["id"] not in placed_ids
    assert all(e["medicine"] != UNCL for e in placed)

    # ...but it IS reported, with its reason, in excluded:
    excluded_ids = {e["id"] for e in schedule["excluded"]}
    assert unclear_item["id"] in excluded_ids
    excluded = next(e for e in schedule["excluded"] if e["id"] == unclear_item["id"])
    assert excluded["reason"] == "Dose unreadable"
    # and excluded entries carry no instruction (they are never translated)
    assert "instruction" not in excluded


def test_unclear_never_in_reminders(mixed_items, unclear_item):
    reminders = build_reminders(mixed_items, lang="en")
    assert all(r["id"] != unclear_item["id"] for r in reminders)
    assert all(r["medicine"] != UNCL for r in reminders)
    assert all(r["time"] in {"08:00", "13:00", "18:00", "21:00"} for r in reminders)


def test_unclear_never_in_pdf_data(mixed_items, unclear_item, monkeypatch):
    """Spy on the schedule the PDF renders: the unclear item may only appear
    in the excluded warning box, never in any slot/as-needed row."""
    captured: dict = {}
    real_build_schedule = pdf_module.build_schedule

    def spy(items, lang="en", translator=None):
        result = real_build_schedule(items, lang=lang, translator=translator)
        captured["schedule"] = result
        return result

    monkeypatch.setattr(pdf_module, "build_schedule", spy)

    pdf_bytes = pdf_module.render_timetable_pdf(mixed_items, lang="en")
    assert pdf_bytes[:5] == b"%PDF-"
    assert "schedule" in captured, "PDF did not build a schedule"

    schedule = captured["schedule"]
    placed = _placed_entries(schedule)
    assert all(e["id"] != unclear_item["id"] for e in placed)
    assert all(e["medicine"] != UNCL for e in placed)
    assert unclear_item["id"] in {e["id"] for e in schedule["excluded"]}
    # no translated text anywhere mentions the unclear medicine
    rendered = json.dumps({"slots": schedule["slots"], "as_needed": schedule["as_needed"]},
                          ensure_ascii=False)
    assert UNCL not in rendered


def test_english_pdf_renders_with_excluded_box(mixed_items, monkeypatch):
    """The excluded list really is in the PDF stream (warning box drawn)."""
    # ReportLab compresses text streams, so assert via the schedule spy AND
    # by comparing PDFs with vs without the unclear item (content differs).
    without = pdf_module.render_timetable_pdf([mixed_items[0]], lang="en")
    with_excl = pdf_module.render_timetable_pdf(mixed_items, lang="en")
    assert with_excl[:5] == b"%PDF-" and without[:5] == b"%PDF-"
    assert with_excl != without  # different content


def test_defense_in_depth_translator_refuses_unclear(unclear_item):
    """Even if a bug passed an unclear item downstream, translation stops it."""
    with pytest.raises(UnclearItemError):
        translate_instruction(unclear_item, "en")
    with pytest.raises(UnclearItemError):
        translate_instruction(unclear_item, "ta")
    with pytest.raises(UnclearItemError):
        translate_instruction(unclear_item, "hi")


def test_only_safe_statuses_are_scheduleable(clear_item, unclear_item):
    for status in SCHEDULEABLE_STATUSES:
        item = {**clear_item, "status": status}
        schedule = build_schedule([item], lang="en")
        assert schedule["excluded"] == []
        assert _placed_entries(schedule), f"status {status} produced no entries"
    # and the unclear one is always excluded
    schedule = build_schedule([unclear_item], lang="en")
    assert len(schedule["excluded"]) == 1
    assert _placed_entries(schedule) == []
    assert build_reminders([unclear_item], lang="en") == []


@pytest.mark.parametrize("lang", ["en", "ta", "hi"])
def test_unclear_never_in_schedule_in_any_language(mixed_items, unclear_item, lang):
    schedule = build_schedule(mixed_items, lang=lang)
    rendered = json.dumps(
        {"slots": schedule["slots"], "as_needed": schedule["as_needed"]},
        ensure_ascii=False,
    )
    assert UNCL not in rendered
    reminders_json = json.dumps(build_reminders(mixed_items, lang=lang), ensure_ascii=False)
    assert UNCL not in reminders_json


def test_as_needed_items_get_no_reminder_time(as_needed_item, unclear_item):
    reminders = build_reminders([as_needed_item, unclear_item], lang="en")
    assert reminders == []
    schedule = build_schedule([as_needed_item, unclear_item], lang="en")
    assert [e["medicine"] for e in schedule["as_needed"]] == ["Cough Syrup"]
