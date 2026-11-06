"""API tests using FastAPI's TestClient, centred on the demo endpoint:
the demo prescription lets every flow be tested without OCR, and one test
uploads a real image through the full OCR pipeline."""

from __future__ import annotations

import pytest


def _unclear_item(prescription: dict) -> dict:
    return next(i for i in prescription["items"] if i["status"] == "unclear")


# ---------------------------------------------------------------------------
# Health + demo
# ---------------------------------------------------------------------------


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("ok", "degraded")
    assert data["version"]


def test_demo_returns_prefilled_prescription(client):
    response = client.post("/api/demo")
    assert response.status_code == 201
    prescription = response.json()
    assert len(prescription["items"]) == 4
    statuses = [i["status"] for i in prescription["items"]]
    assert statuses.count("clear") == 3
    assert statuses.count("unclear") == 1

    unclear = _unclear_item(prescription)
    assert unclear["reason"] == "Dose unreadable"
    assert unclear["medicine"] == "Cetirizine"
    assert unclear["strength"] is None

    # clear items carry full parsed fields
    paracetamol = next(i for i in prescription["items"] if i["medicine"] == "Paracetamol")
    assert paracetamol["strength"] == "500 mg"
    assert paracetamol["frequency"] == "1-0-1"
    assert paracetamol["food_timing"] == "after"
    assert paracetamol["duration_days"] == 5
    assert paracetamol["slots"] == ["morning", "night"]


def test_demo_image_is_served(demo_prescription, client):
    image_url = demo_prescription["image_url"]
    assert image_url and image_url.startswith("/uploads/")
    response = client.get(image_url)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/png")


def test_get_prescription_roundtrip(demo_prescription, client):
    response = client.get(f"/api/prescriptions/{demo_prescription['id']}")
    assert response.status_code == 200
    assert response.json()["id"] == demo_prescription["id"]
    assert len(response.json()["items"]) == 4


def test_prescription_not_found(client):
    assert client.get("/api/prescriptions/999999").status_code == 404
    assert client.post("/api/prescriptions/999999/schedule").status_code == 404
    assert client.get("/api/prescriptions/999999/reminders").status_code == 404
    assert client.get("/api/prescriptions/999999/timetable.pdf").status_code == 404


# ---------------------------------------------------------------------------
# Upload validation
# ---------------------------------------------------------------------------


def test_upload_rejects_wrong_content_type(client):
    response = client.post("/api/prescriptions",
                           files={"file": ("notes.txt", b"hello", "text/plain")})
    assert response.status_code == 415
    assert "JPG" in response.json()["detail"]


def test_upload_rejects_oversized_file(client):
    huge = b"x" * (10 * 1024 * 1024 + 1024)
    response = client.post("/api/prescriptions",
                           files={"file": ("big.png", huge, "image/png")})
    assert response.status_code == 413
    assert "10 MB" in response.json()["detail"]


def test_upload_rejects_empty_file(client):
    response = client.post("/api/prescriptions",
                           files={"file": ("empty.png", b"", "image/png")})
    assert response.status_code == 400


def test_upload_real_image_runs_full_ocr_pipeline(client, prescription_image):
    with open(prescription_image, "rb") as handle:
        response = client.post("/api/prescriptions",
                               files={"file": ("rx.png", handle, "image/png")})
    assert response.status_code == 201, response.text
    prescription = response.json()
    assert len(prescription["items"]) == 4

    statuses = [i["status"] for i in prescription["items"]]
    assert set(statuses) <= {"clear", "unclear"}
    assert statuses.count("unclear") == 1
    unclear = _unclear_item(prescription)
    assert unclear["reason"] == "Dose unreadable"

    # image accessible + schedule works on the OCR result
    assert client.get(prescription["image_url"]).status_code == 200
    schedule = client.post(
        f"/api/prescriptions/{prescription['id']}/schedule",
        params={"lang": "en"},
    ).json()
    assert {e["id"] for e in schedule["excluded"]} == {unclear["id"]}
    assert all(e["medicine"] != unclear["medicine"]
               for lst in schedule["slots"].values() for e in lst)


# ---------------------------------------------------------------------------
# Schedule endpoint
# ---------------------------------------------------------------------------


def test_schedule_excludes_unclear_item(demo_prescription, client):
    unclear = _unclear_item(demo_prescription)
    response = client.post(
        f"/api/prescriptions/{demo_prescription['id']}/schedule",
        params={"lang": "en"},
    )
    assert response.status_code == 200
    schedule = response.json()

    placed_ids = {e["id"] for lst in schedule["slots"].values() for e in lst}
    placed_ids |= {e["id"] for e in schedule["as_needed"]}
    assert unclear["id"] not in placed_ids
    assert [e["id"] for e in schedule["excluded"]] == [unclear["id"]]
    assert schedule["excluded"][0]["reason"] == "Dose unreadable"
    assert schedule["disclaimer"]

    assert schedule["slot_times"] == {
        "morning": "08:00", "afternoon": "13:00", "evening": "18:00", "night": "21:00",
    }
    morning = {e["medicine"] for e in schedule["slots"]["morning"]}
    assert morning == {"Paracetamol", "Amoxicillin"}


@pytest.mark.parametrize("lang", ["en", "ta", "hi"])
def test_schedule_all_languages(demo_prescription, client, lang):
    response = client.post(
        f"/api/prescriptions/{demo_prescription['id']}/schedule",
        params={"lang": lang},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["lang"] == lang
    assert data["title"] and data["disclaimer"]


def test_schedule_rejects_unknown_language(demo_prescription, client):
    response = client.post(
        f"/api/prescriptions/{demo_prescription['id']}/schedule",
        params={"lang": "fr"},
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Reminders
# ---------------------------------------------------------------------------


def test_reminders_exclude_unclear_and_as_needed(demo_prescription, client):
    unclear = _unclear_item(demo_prescription)
    response = client.get(f"/api/prescriptions/{demo_prescription['id']}/reminders")
    assert response.status_code == 200
    reminders = response.json()

    assert len(reminders) == 5  # paracetamol x2 + amoxicillin x3
    assert all(r["medicine"] != unclear["medicine"] for r in reminders)
    assert all(r["medicine"] != "Cough Syrup" for r in reminders)  # SOS has no reminder
    assert {r["time"] for r in reminders} <= {"08:00", "13:00", "18:00", "21:00"}
    assert all(r["instruction"] for r in reminders)


def test_reminders_in_tamil(demo_prescription, client):
    response = client.get(
        f"/api/prescriptions/{demo_prescription['id']}/reminders",
        params={"lang": "ta"},
    )
    assert response.status_code == 200
    assert response.json()


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------


def test_timetable_pdf(demo_prescription, client):
    response = client.get(
        f"/api/prescriptions/{demo_prescription['id']}/timetable.pdf",
        params={"lang": "en"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content[:5] == b"%PDF-"
    assert len(response.content) > 1000


@pytest.mark.parametrize("lang", ["ta", "hi"])
def test_timetable_pdf_indic_languages(demo_prescription, client, lang):
    response = client.get(
        f"/api/prescriptions/{demo_prescription['id']}/timetable.pdf",
        params={"lang": lang},
    )
    assert response.status_code == 200
    assert response.content[:5] == b"%PDF-"


# ---------------------------------------------------------------------------
# Confirm / edit flow (the ONLY path from unclear to scheduleable)
# ---------------------------------------------------------------------------


def test_confirm_flow(demo_prescription, client):
    unclear = _unclear_item(demo_prescription)
    response = client.patch(
        f"/api/prescriptions/{demo_prescription['id']}/items/{unclear['id']}",
        json={"action": "confirm"},
    )
    assert response.status_code == 200
    updated = response.json()
    assert updated["status"] == "confirmed"
    assert updated["reason"] == ""

    # now it may enter the schedule and reminders
    schedule = client.post(
        f"/api/prescriptions/{demo_prescription['id']}/schedule",
        params={"lang": "en"},
    ).json()
    assert schedule["excluded"] == []
    assert unclear["medicine"] in {
        e["medicine"] for lst in schedule["slots"].values() for e in lst
    }
    reminders = client.get(
        f"/api/prescriptions/{demo_prescription['id']}/reminders"
    ).json()
    assert unclear["medicine"] in {r["medicine"] for r in reminders}


def test_edit_incomplete_stays_unclear(demo_prescription, client):
    unclear = _unclear_item(demo_prescription)
    response = client.patch(
        f"/api/prescriptions/{demo_prescription['id']}/items/{unclear['id']}",
        json={"action": "edit", "fields": {"frequency": "0-0-1"}},  # still no dose
    )
    assert response.status_code == 200
    updated = response.json()
    assert updated["status"] == "unclear"       # never auto-promoted
    assert "Dose" in updated["reason"]


def test_edit_complete_becomes_edited(demo_prescription, client):
    unclear = _unclear_item(demo_prescription)
    response = client.patch(
        f"/api/prescriptions/{demo_prescription['id']}/items/{unclear['id']}",
        json={"action": "edit", "fields": {
            "medicine_name": "Cetirizine",
            "strength": "10 mg",
            "form": "tab",
            "frequency": "0-0-1",
            "duration_days": 5,
        }},
    )
    assert response.status_code == 200
    updated = response.json()
    assert updated["status"] == "edited"        # NOT "clear"
    assert updated["reason"] == ""
    assert updated["confidence"] == 100.0       # human input, not OCR
    assert updated["strength"] == "10 mg"
    assert updated["duration_days"] == 5
    assert updated["slots"] == ["night"]

    # edited items are scheduleable everywhere
    schedule = client.post(
        f"/api/prescriptions/{demo_prescription['id']}/schedule",
        params={"lang": "en"},
    ).json()
    assert schedule["excluded"] == []
    assert any(e["medicine"] == "Cetirizine"
               for e in schedule["slots"]["night"])
    pdf = client.get(
        f"/api/prescriptions/{demo_prescription['id']}/timetable.pdf",
        params={"lang": "en"},
    )
    assert pdf.content[:5] == b"%PDF-"


def test_edit_requires_fields(demo_prescription, client):
    unclear = _unclear_item(demo_prescription)
    response = client.patch(
        f"/api/prescriptions/{demo_prescription['id']}/items/{unclear['id']}",
        json={"action": "edit"},
    )
    assert response.status_code == 400


def test_edit_with_explicit_source_text(demo_prescription, client):
    unclear = _unclear_item(demo_prescription)
    response = client.patch(
        f"/api/prescriptions/{demo_prescription['id']}/items/{unclear['id']}",
        json={"action": "edit", "fields": {
            "source_text": "Tab Cetirizine 10 mg 0-0-1 x 5 days",
        }},
    )
    assert response.status_code == 200
    updated = response.json()
    assert updated["status"] == "edited"
    assert updated["medicine"] == "Cetirizine"
    assert updated["source_text"] == "Tab Cetirizine 10 mg 0-0-1 x 5 days"


def test_patch_item_not_found(demo_prescription, client):
    response = client.patch(
        f"/api/prescriptions/{demo_prescription['id']}/items/999999",
        json={"action": "confirm"},
    )
    assert response.status_code == 404


def test_invalid_action_rejected(demo_prescription, client):
    unclear = _unclear_item(demo_prescription)
    response = client.patch(
        f"/api/prescriptions/{demo_prescription['id']}/items/{unclear['id']}",
        json={"action": "delete"},
    )
    assert response.status_code == 422  # pydantic Literal validation


def test_status_never_becomes_clear_through_api(demo_prescription, client):
    """No API action can produce status 'clear' — only the initial gate does."""
    unclear = _unclear_item(demo_prescription)
    item_id = unclear["id"]
    pid = demo_prescription["id"]

    def current_status() -> str:
        items = client.get(f"/api/prescriptions/{pid}").json()["items"]
        return next(i["status"] for i in items if i["id"] == item_id)

    seen = {unclear["status"]}

    client.patch(f"/api/prescriptions/{pid}/items/{item_id}", json={"action": "edit",
               "fields": {"frequency": "0-0-1"}})
    seen.add(current_status())
    client.patch(f"/api/prescriptions/{pid}/items/{item_id}", json={"action": "confirm"})
    seen.add(current_status())

    assert "clear" not in seen, f"API produced 'clear' from an unclear item: {seen}"
