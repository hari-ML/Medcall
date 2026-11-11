"""Phase 3 reminder-engine tests.

Every test gets its own patient (fresh phone) so occurrence counts cannot
leak between tests, and drives the engine with fixed naive-UTC clocks —
never the wall clock — for deterministic timezone math.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func

from conftest import otp_login

from app.channels import ChannelAdapter, ChannelDeliveryError, DeliveryResult
from app.db import SessionLocal
from app.main import app
from app.models import (
    MedicineItem,
    Prescription,
    ReminderOccurrence,
    ReminderSchedule,
)
from app.reminders import dispatch_due, generate_occurrences
from app.schedule import SLOT_DEFAULT_TIMES


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _fresh_phone() -> str:
    return "+9197" + "".join(secrets.choice("0123456789") for _ in range(8))


@pytest.fixture()
def rem_patient():
    """A brand-new logged-in patient with an isolated cookie jar."""
    with TestClient(app) as client:
        phone = _fresh_phone()
        token = otp_login(client, phone, "Reminder Test")
        headers = {"Authorization": f"Bearer {token}"}
        me = client.get("/api/patients/me", headers=headers)
        assert me.status_code == 200
        yield {"client": client, "headers": headers, "id": me.json()["id"], "phone": phone}


@pytest.fixture()
def other_rem_patient():
    """A second, unrelated patient (for isolation assertions)."""
    with TestClient(app) as client:
        phone = _fresh_phone()
        token = otp_login(client, phone, "Other Reminder Patient")
        headers = {"Authorization": f"Bearer {token}"}
        me = client.get("/api/patients/me", headers=headers)
        assert me.status_code == 200
        yield {"client": client, "headers": headers, "id": me.json()["id"], "phone": phone}


def _set_profile(p, *, tz: str = "Asia/Kolkata", lang: str = "en") -> None:
    response = p["client"].patch(
        "/api/patients/me",
        headers=p["headers"],
        json={"timezone": tz, "preferred_lang": lang},
    )
    assert response.status_code == 200, response.text


def _set_consent(p, channel: str, granted: bool) -> None:
    response = p["client"].post(
        "/api/patients/me/consent",
        headers=p["headers"],
        json={"channel": channel, "granted": granted},
    )
    assert response.status_code == 200, response.text


def _revoke_all_consent(p) -> None:
    for channel in ("whatsapp", "sms", "voice"):
        _set_consent(p, channel, False)


def _new_demo(p) -> dict:
    response = p["client"].post("/api/demo", headers=p["headers"])
    assert response.status_code == 201, response.text
    return response.json()


def _enroll(p, prescription_id: int) -> dict:
    response = p["client"].post(
        f"/api/prescriptions/{prescription_id}/reminders/enroll", headers=p["headers"]
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture()
def enrolled(rem_patient):
    _set_profile(rem_patient)
    demo = _new_demo(rem_patient)
    enrollment = _enroll(rem_patient, demo["id"])
    return {**rem_patient, "demo": demo, "enrollment": enrollment}


def _db():
    return SessionLocal()


def _start_day(db, patient_id: int):
    row = (
        db.query(ReminderSchedule.start_date)
        .filter(ReminderSchedule.patient_id == patient_id)
        .order_by(ReminderSchedule.id)
        .first()
    )
    assert row is not None, "no reminder schedules were materialised"
    return row[0]


def _at(day, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute)


def _schedules(db, patient_id: int, prescription_id: int | None = None):
    query = db.query(ReminderSchedule).filter(ReminderSchedule.patient_id == patient_id)
    if prescription_id is not None:
        query = query.filter(ReminderSchedule.prescription_id == prescription_id)
    return query.all()


def _occurrences(db, patient_id: int):
    return (
        db.query(ReminderOccurrence)
        .filter(ReminderOccurrence.patient_id == patient_id)
        .all()
    )


# ---------------------------------------------------------------------------
# Enrollment
# ---------------------------------------------------------------------------


def test_enrollment_only_covers_scheduleable_fixed_slot_items(enrolled):
    items = enrolled["demo"]["items"]
    eligible = [
        item
        for item in items
        if item["status"] in {"clear", "confirmed", "edited"}
        and not item["as_needed"]
        and any(slot in SLOT_DEFAULT_TIMES for slot in (item["slots"] or []))
    ]
    expected_ids = {item["id"] for item in eligible}
    expected_doses = sum(
        len([slot for slot in item["slots"] if slot in SLOT_DEFAULT_TIMES])
        for item in eligible
    )

    assert enrolled["enrollment"]["scheduled_doses"] == expected_doses
    assert {entry["item_id"] for entry in enrolled["enrollment"]["items"]} == expected_ids

    skipped_ids = {entry["item_id"] for entry in enrolled["enrollment"]["skipped"]}
    assert skipped_ids == {item["id"] for item in items} - expected_ids
    assert all(entry["reason"] for entry in enrolled["enrollment"]["skipped"])

    # the unclear line and the SOS line are explicitly skipped
    unclear_ids = {item["id"] for item in items if item["status"] == "unclear"}
    sos_ids = {item["id"] for item in items if item["as_needed"]}
    assert unclear_ids and unclear_ids <= skipped_ids
    assert sos_ids and sos_ids <= skipped_ids

    db = _db()
    try:
        rows = _schedules(db, enrolled["id"], enrolled["demo"]["id"])
        assert {row.item_id for row in rows} == expected_ids
        assert all(row.item_id not in unclear_ids | sos_ids for row in rows)
        assert all(row.active for row in rows)
        assert all(row.time_of_day in SLOT_DEFAULT_TIMES.values() for row in rows)
    finally:
        db.close()


def test_enrollment_is_idempotent(enrolled):
    second = _enroll(enrolled, enrolled["demo"]["id"])
    assert second["scheduled_doses"] == enrolled["enrollment"]["scheduled_doses"]
    assert second["items"] == enrolled["enrollment"]["items"]

    db = _db()
    try:
        rows = _schedules(db, enrolled["id"], enrolled["demo"]["id"])
        assert len(rows) == enrolled["enrollment"]["scheduled_doses"]
    finally:
        db.close()


def test_enrollment_is_ownership_scoped(enrolled, other_headers):
    client = enrolled["client"]
    pid = enrolled["demo"]["id"]
    assert (
        client.post(
            f"/api/prescriptions/{pid}/reminders/enroll", headers=other_headers
        ).status_code
        == 404
    )
    assert (
        client.delete(
            f"/api/prescriptions/{pid}/reminders/enroll", headers=other_headers
        ).status_code
        == 404
    )


def test_unenroll_deactivates_and_cancels_pending(enrolled):
    client = enrolled["client"]
    headers = enrolled["headers"]
    pid = enrolled["demo"]["id"]

    assert client.get("/api/reminders/upcoming?days=2", headers=headers).status_code == 200

    db = _db()
    try:
        assert any(
            occ.status == "pending" for occ in _occurrences(db, enrolled["id"])
        )
    finally:
        db.close()

    response = client.delete(
        f"/api/prescriptions/{pid}/reminders/enroll", headers=headers
    )
    assert response.status_code == 204

    db = _db()
    try:
        rows = _schedules(db, enrolled["id"], pid)
        assert rows and all(not row.active for row in rows)
        assert all(
            occ.status != "pending" for occ in _occurrences(db, enrolled["id"])
        )
    finally:
        db.close()

    assert client.get("/api/reminders/upcoming?days=2", headers=headers).json() == []


def test_enrolling_an_unclear_only_prescription_schedules_nothing(rem_patient):
    _set_profile(rem_patient)
    db = _db()
    try:
        prescription = Prescription(
            patient_id=rem_patient["id"],
            original_filename="manual.png",
            content_type="image/png",
            lang="en",
        )
        db.add(prescription)
        db.flush()
        db.add(
            MedicineItem(
                prescription_id=prescription.id,
                line_number=1,
                source_text="Tab Mystery ?? mg 1-1-1",
                medicine_name="Mystery",
                frequency="1-1-1",
                slots=["morning", "afternoon", "night"],
                status="unclear",
                reason="Dose is unreadable",
            )
        )
        db.commit()
        pid = prescription.id
    finally:
        db.close()

    enrollment = _enroll(rem_patient, pid)
    assert enrollment["scheduled_doses"] == 0
    assert len(enrollment["skipped"]) == 1

    run = rem_patient["client"].post(
        "/api/reminders/run", headers=rem_patient["headers"]
    ).json()
    assert run["sent"] == 0 and run["blocked"] == 0

    db = _db()
    try:
        assert _schedules(db, rem_patient["id"], pid) == []
        assert _occurrences(db, rem_patient["id"]) == []
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Occurrence generation (timezone + horizon + duration)
# ---------------------------------------------------------------------------


def test_occurrences_convert_local_slot_times_to_utc(enrolled):
    db = _db()
    try:
        start = _start_day(db, enrolled["id"])
        now = _at(start, 6)  # 11:30 Asia/Kolkata
        created = generate_occurrences(
            db, now, horizon_hours=24, patient_id=enrolled["id"]
        )
        assert created > 0

        tz = ZoneInfo("Asia/Kolkata")
        expected: list[datetime] = []
        for entry in enrolled["enrollment"]["items"]:
            hours, minutes = map(int, entry["time_of_day"].split(":"))
            for offset in (0, 1):
                local = datetime(
                    start.year, start.month, start.day, hours, minutes, tzinfo=tz
                ) + timedelta(days=offset)
                utc = local.astimezone(timezone.utc).replace(tzinfo=None)
                if now - timedelta(minutes=120) <= utc <= now + timedelta(hours=24):
                    expected.append(utc)

        actual = sorted(
            occ.scheduled_at
            for occ in _occurrences(db, enrolled["id"])
        )
        assert actual == sorted(expected)
    finally:
        db.close()


def test_occurrence_generation_is_idempotent(enrolled):
    db = _db()
    try:
        start = _start_day(db, enrolled["id"])
        now = _at(start, 6)
        first = generate_occurrences(db, now, 48, patient_id=enrolled["id"])
        second = generate_occurrences(db, now, 48, patient_id=enrolled["id"])
        assert first > 0 and second == 0
    finally:
        db.close()


def test_course_duration_caps_occurrences(enrolled):
    db = _db()
    try:
        start = _start_day(db, enrolled["id"])
        now = _at(start, 0)  # 05:30 Asia/Kolkata — whole first day still ahead
        generate_occurrences(db, now, 10 * 24, patient_id=enrolled["id"])

        per_schedule = dict(
            db.query(ReminderOccurrence.schedule_id, func.count(ReminderOccurrence.id))
            .filter(ReminderOccurrence.patient_id == enrolled["id"])
            .group_by(ReminderOccurrence.schedule_id)
            .all()
        )
        assert per_schedule
        assert all(count == 5 for count in per_schedule.values()), per_schedule

        last_local = (
            db.query(func.max(ReminderOccurrence.scheduled_at))
            .filter(ReminderOccurrence.patient_id == enrolled["id"])
            .scalar()
        )
        tz = ZoneInfo("Asia/Kolkata")
        end_of_course_utc = (
            datetime(start.year, start.month, start.day, 23, 59, tzinfo=tz)
            + timedelta(days=4)
        ).astimezone(timezone.utc).replace(tzinfo=None)
        assert last_local <= end_of_course_utc
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Consent gate + delivery
# ---------------------------------------------------------------------------


def test_no_consent_blocks_and_nothing_is_sent(enrolled):
    _revoke_all_consent(enrolled)
    db = _db()
    try:
        start = _start_day(db, enrolled["id"])
        generate_occurrences(db, _at(start, 15, 25), 48, patient_id=enrolled["id"])
        counts = dispatch_due(db, _at(start, 15, 35), patient_id=enrolled["id"])

        assert counts["sent"] == 0
        assert counts["blocked"] >= 1
        blocked = [
            occ for occ in _occurrences(db, enrolled["id"]) if occ.status == "blocked"
        ]
        assert blocked
        assert all(occ.body == "" and occ.provider_message_id == "" for occ in blocked)
        assert all("consent" in occ.error for occ in blocked)
    finally:
        db.close()


def test_granted_consent_sends_fake_message_with_verified_body(enrolled):
    _set_consent(enrolled, "whatsapp", True)
    db = _db()
    try:
        start = _start_day(db, enrolled["id"])
        generate_occurrences(db, _at(start, 15, 25), 48, patient_id=enrolled["id"])
        counts = dispatch_due(db, _at(start, 15, 35), patient_id=enrolled["id"])
        assert counts["sent"] >= 1

        sent = [
            occ for occ in _occurrences(db, enrolled["id"]) if occ.status == "sent"
        ]
        scheduleable_names = {
            entry["medicine"] for entry in enrolled["enrollment"]["items"]
        }
        for occ in sent:
            assert occ.channel == "whatsapp"
            assert occ.provider_message_id.startswith("fake-whatsapp-")
            assert occ.body.startswith("MedRecall:")
            assert occ.sent_at == _at(start, 15, 35)
            assert occ.schedule.item.medicine_name in scheduleable_names
    finally:
        db.close()

    history = enrolled["client"].get(
        "/api/reminders/history", headers=enrolled["headers"]
    ).json()
    assert history
    assert all(entry["status"] in {"sent", "blocked", "failed", "missed", "cancelled"} for entry in history)


def test_consent_channel_preference(enrolled):
    _set_consent(enrolled, "sms", True)
    db = _db()
    try:
        start = _start_day(db, enrolled["id"])
        generate_occurrences(db, _at(start, 15, 25), 48, patient_id=enrolled["id"])
        dispatch_due(db, _at(start, 15, 35), patient_id=enrolled["id"])
        sent = [o for o in _occurrences(db, enrolled["id"]) if o.status == "sent"]
        assert sent and all(occ.channel == "sms" for occ in sent)

        # granting WhatsApp (first in preference order) wins for later sends
        _set_consent(enrolled, "whatsapp", True)
        dispatch_due(db, _at(start + timedelta(days=1), 2, 35), patient_id=enrolled["id"])
        later = [
            occ
            for occ in _occurrences(db, enrolled["id"])
            if occ.status == "sent" and occ.channel == "whatsapp"
        ]
        assert later
    finally:
        db.close()


def test_message_language_follows_patient_profile(enrolled):
    response = enrolled["client"].patch(
        "/api/patients/me",
        headers=enrolled["headers"],
        json={"preferred_lang": "ta"},
    )
    assert response.status_code == 200

    db = _db()
    try:
        rows = _schedules(db, enrolled["id"], enrolled["demo"]["id"])
        assert rows and all(row.lang == "ta" for row in rows)
    finally:
        db.close()

    _set_consent(enrolled, "sms", True)
    db = _db()
    try:
        start = _start_day(db, enrolled["id"])
        generate_occurrences(db, _at(start, 15, 25), 24, patient_id=enrolled["id"])
        dispatch_due(db, _at(start, 15, 35), patient_id=enrolled["id"])
        sent = [o for o in _occurrences(db, enrolled["id"]) if o.status == "sent"]
        assert sent
        assert all(any("\u0b80" <= ch <= "\u0bff" for ch in occ.body) for occ in sent)
    finally:
        db.close()

    # switching back updates future messages too
    enrolled["client"].patch(
        "/api/patients/me", headers=enrolled["headers"], json={"preferred_lang": "en"}
    )
    db = _db()
    try:
        rows = _schedules(db, enrolled["id"], enrolled["demo"]["id"])
        assert all(row.lang == "en" for row in rows)
    finally:
        db.close()


def test_grace_window_marks_missed_instead_of_sending(enrolled):
    _set_consent(enrolled, "sms", True)
    db = _db()
    try:
        start = _start_day(db, enrolled["id"])
        schedule = _schedules(db, enrolled["id"], enrolled["demo"]["id"])[0]
        stale = ReminderOccurrence(
            schedule_id=schedule.id,
            patient_id=enrolled["id"],
            scheduled_at=_at(start, 0, 0),
            status="pending",
        )
        db.add(stale)
        db.commit()

        counts = dispatch_due(db, _at(start, 6), patient_id=enrolled["id"])
        assert counts["missed"] == 1
        assert counts["sent"] == 0
        db.refresh(stale)
        assert stale.status == "missed"
        assert stale.body == "" and stale.provider_message_id == ""
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Safety: confirm/edit transitions keep reminders truthful
# ---------------------------------------------------------------------------


def _item_by_status(demo: dict, status: str) -> dict:
    return next(item for item in demo["items"] if item["status"] == status)


def _fixed_slot_item(demo: dict) -> dict:
    return next(
        item
        for item in demo["items"]
        if item["status"] in {"clear", "confirmed", "edited"}
        and not item["as_needed"]
        and item["slots"]
    )


def test_edit_to_unclear_cancels_schedules_and_pending_occurrences(enrolled):
    item = _fixed_slot_item(enrolled["demo"])
    client = enrolled["client"]
    headers = enrolled["headers"]
    pid = enrolled["demo"]["id"]

    db = _db()
    try:
        start = _start_day(db, enrolled["id"])
        generate_occurrences(db, _at(start, 15, 25), 48, patient_id=enrolled["id"])
        pending_before = [
            occ
            for occ in _occurrences(db, enrolled["id"])
            if occ.status == "pending" and occ.schedule.item_id == item["id"]
        ]
        assert pending_before
    finally:
        db.close()

    response = client.patch(
        f"/api/prescriptions/{pid}/items/{item['id']}",
        headers=headers,
        json={"action": "edit", "fields": {"frequency": "0-0-1"}},  # no dose => unclear
    )
    assert response.status_code == 200
    assert response.json()["status"] == "unclear"

    db = _db()
    try:
        rows = [row for row in _schedules(db, enrolled["id"], pid) if row.item_id == item["id"]]
        assert rows and all(not row.active for row in rows)
        remaining = [
            occ
            for occ in _occurrences(db, enrolled["id"])
            if occ.schedule.item_id == item["id"] and occ.status == "pending"
        ]
        assert remaining == []

        # even a due tick can never send that item now
        _set_consent(enrolled, "sms", True)
        dispatch_due(db, _at(start, 15, 35), patient_id=enrolled["id"])
        assert not [
            occ
            for occ in _occurrences(db, enrolled["id"])
            if occ.status == "sent" and occ.schedule.item_id == item["id"]
        ]
    finally:
        db.close()


def test_edit_to_complete_reschedules_the_item(enrolled):
    item = _fixed_slot_item(enrolled["demo"])
    response = enrolled["client"].patch(
        f"/api/prescriptions/{enrolled['demo']['id']}/items/{item['id']}",
        headers=enrolled["headers"],
        json={
            "action": "edit",
            "fields": {
                "medicine_name": item["medicine"],
                "strength": item["strength"] or "500 mg",
                "form": "tab",
                "frequency": "0-0-1",
                "food_timing": "after food",
            },
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "edited"

    db = _db()
    try:
        rows = [
            row
            for row in _schedules(db, enrolled["id"], enrolled["demo"]["id"])
            if row.item_id == item["id"]
        ]
        assert [row.slot for row in rows if row.active] == ["night"]
    finally:
        db.close()


def test_confirm_after_enrollment_adds_a_schedule(enrolled):
    unclear = _item_by_status(enrolled["demo"], "unclear")
    pid = enrolled["demo"]["id"]

    db = _db()
    try:
        assert not [
            row
            for row in _schedules(db, enrolled["id"], pid)
            if row.item_id == unclear["id"]
        ]
    finally:
        db.close()

    response = enrolled["client"].patch(
        f"/api/prescriptions/{pid}/items/{unclear['id']}",
        headers=enrolled["headers"],
        json={"action": "confirm"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "confirmed"

    db = _db()
    try:
        rows = [
            row
            for row in _schedules(db, enrolled["id"], pid)
            if row.item_id == unclear["id"]
        ]
        expected_slots = set(unclear["slots"]) & set(SLOT_DEFAULT_TIMES)
        assert rows
        assert {row.slot for row in rows if row.active} == expected_slots
    finally:
        db.close()


def test_confirm_without_enrollment_does_not_create_schedules(rem_patient):
    _set_profile(rem_patient)
    demo = _new_demo(rem_patient)
    unclear = _item_by_status(demo, "unclear")

    response = rem_patient["client"].patch(
        f"/api/prescriptions/{demo['id']}/items/{unclear['id']}",
        headers=rem_patient["headers"],
        json={"action": "confirm"},
    )
    assert response.status_code == 200

    db = _db()
    try:
        assert _schedules(db, rem_patient["id"], demo["id"]) == []
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Patient-wide feeds
# ---------------------------------------------------------------------------


def test_upcoming_and_history_are_patient_scoped(enrolled, other_rem_patient):
    _set_consent(enrolled, "sms", True)
    enrolled["client"].post("/api/reminders/run", headers=enrolled["headers"])

    mine = enrolled["client"].get(
        "/api/reminders/upcoming?days=3", headers=enrolled["headers"]
    ).json()
    assert mine
    assert [entry["scheduled_at"] for entry in mine] == sorted(
        entry["scheduled_at"] for entry in mine
    )
    assert all(entry["status"] == "pending" for entry in mine)
    assert all(len(entry["local_time"]) == 5 and entry["local_time"][2] == ":" for entry in mine)

    their_upcoming = other_rem_patient["client"].get(
        "/api/reminders/upcoming?days=3", headers=other_rem_patient["headers"]
    ).json()
    assert their_upcoming == []
    assert other_rem_patient["client"].get(
        "/api/reminders/history", headers=other_rem_patient["headers"]
    ).json() == []

    their_run = other_rem_patient["client"].post(
        "/api/reminders/run", headers=other_rem_patient["headers"]
    ).json()
    assert their_run["generated"] == 0 and their_run["sent"] == 0


def test_run_endpoint_reports_tick_counts(enrolled):
    payload = enrolled["client"].post(
        "/api/reminders/run", headers=enrolled["headers"]
    ).json()
    assert set(payload) == {
        "generated",
        "sent",
        "blocked",
        "failed",
        "missed",
        "cancelled",
    }
    assert all(isinstance(value, int) for value in payload.values())
    assert payload["generated"] >= 0


# ---------------------------------------------------------------------------
# Phase 4: provider retry/backoff (transient vs permanent failures)
# ---------------------------------------------------------------------------


class _StubAdapter(ChannelAdapter):
    """Configured adapter whose first ``failures`` sends raise."""

    name = "sms"

    def __init__(self, failures: int, *, transient: bool = True) -> None:
        self.failures = failures
        self.transient = transient
        self.calls = 0

    @property
    def configured(self) -> bool:
        return True

    def send(
        self,
        to_phone: str,
        body: str,
        *,
        lang: str = "en",
        interactive=None,
    ) -> DeliveryResult:
        self.calls += 1
        if self.calls <= self.failures:
            raise ChannelDeliveryError(
                f"provider failure #{self.calls}", transient=self.transient
            )
        return DeliveryResult(message_id=f"stub-{self.calls}", channel=self.name)


def _use_stub(monkeypatch, stub: _StubAdapter) -> None:
    monkeypatch.setattr("app.reminders.adapter_for", lambda channel: stub)


def _pending(db, patient_id: int):
    return [occ for occ in _occurrences(db, patient_id) if occ.status == "pending"]


def _due_pending(db, patient_id: int, now: datetime):
    """Pending occurrences whose dose time has passed (ignores backoff)."""
    return [
        occ
        for occ in _pending(db, patient_id)
        if occ.scheduled_at <= now
    ]


def test_transient_failure_waits_for_backoff_then_retries(enrolled, monkeypatch):
    _set_consent(enrolled, "sms", True)
    stub = _StubAdapter(failures=1)
    _use_stub(monkeypatch, stub)

    db = _db()
    try:
        start = _start_day(db, enrolled["id"])
        generate_occurrences(db, _at(start, 15, 25), 48, patient_id=enrolled["id"])

        first = dispatch_due(db, _at(start, 15, 35), patient_id=enrolled["id"])
        assert first["sent"] == 1  # the other due dose succeeded
        assert stub.calls == 2

        pending = _due_pending(db, enrolled["id"], _at(start, 15, 35))
        assert len(pending) == 1
        occurrence = pending[0]
        assert occurrence.attempts == 1
        assert occurrence.next_attempt_at == _at(start, 15, 36)
        assert "provider failure" in occurrence.error

        # before the backoff deadline: no retry, still pending
        second = dispatch_due(
            db,
            _at(start, 15, 35) + timedelta(seconds=30),
            patient_id=enrolled["id"],
        )
        assert second["sent"] == 0
        assert stub.calls == 2

        # after the backoff deadline: retried and sent
        third = dispatch_due(
            db,
            _at(start, 15, 36) + timedelta(seconds=1),
            patient_id=enrolled["id"],
        )
        assert third["sent"] == 1
        assert stub.calls == 3

        db.refresh(occurrence)
        assert occurrence.status == "sent"
        assert occurrence.next_attempt_at is None
        assert occurrence.attempts == 1
        assert occurrence.provider_message_id == "stub-3"
    finally:
        db.close()


def test_permanent_failure_fails_immediately_and_is_not_retried(enrolled, monkeypatch):
    _set_consent(enrolled, "sms", True)
    stub = _StubAdapter(failures=1, transient=False)
    _use_stub(monkeypatch, stub)

    db = _db()
    try:
        start = _start_day(db, enrolled["id"])
        generate_occurrences(db, _at(start, 15, 25), 48, patient_id=enrolled["id"])

        first = dispatch_due(db, _at(start, 15, 35), patient_id=enrolled["id"])
        assert first["failed"] == 1
        assert first["sent"] == 1

        failed = [occ for occ in _occurrences(db, enrolled["id"]) if occ.status == "failed"]
        assert len(failed) == 1
        occurrence = failed[0]
        assert occurrence.attempts == 1
        assert occurrence.next_attempt_at is None
        assert "provider failure" in occurrence.error

        calls_before = stub.calls
        dispatch_due(db, _at(start, 16, 30), patient_id=enrolled["id"])
        assert stub.calls == calls_before  # never retried
    finally:
        db.close()


def test_retries_stop_at_max_attempts(enrolled, monkeypatch):
    _set_consent(enrolled, "sms", True)
    stub = _StubAdapter(failures=99)
    _use_stub(monkeypatch, stub)

    db = _db()
    try:
        start = _start_day(db, enrolled["id"])
        generate_occurrences(db, _at(start, 15, 25), 48, patient_id=enrolled["id"])

        first = dispatch_due(db, _at(start, 15, 35), patient_id=enrolled["id"])
        assert first["sent"] == 0 and first["failed"] == 0
        due = _due_pending(db, enrolled["id"], _at(start, 15, 35))
        assert len(due) == 2
        assert {occ.attempts for occ in due} == {1}

        second = dispatch_due(
            db, _at(start, 15, 36) + timedelta(seconds=1), patient_id=enrolled["id"]
        )
        assert second["failed"] == 0
        due = _due_pending(
            db, enrolled["id"], _at(start, 15, 36) + timedelta(seconds=1)
        )
        assert {occ.attempts for occ in due} == {2}
        assert {occ.next_attempt_at for occ in due} == {
            _at(start, 15, 38) + timedelta(seconds=1)
        }

        third = dispatch_due(
            db, _at(start, 15, 38) + timedelta(seconds=2), patient_id=enrolled["id"]
        )
        assert third["failed"] == 2
        assert (
            _due_pending(db, enrolled["id"], _at(start, 15, 38) + timedelta(seconds=2))
            == []
        )
        failed = [occ for occ in _occurrences(db, enrolled["id"]) if occ.status == "failed"]
        assert len(failed) == 2
        assert {occ.attempts for occ in failed} == {3}
        assert all(occ.next_attempt_at is None for occ in failed)
        assert stub.calls == 6
    finally:
        db.close()
