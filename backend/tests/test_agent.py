"""Phase 5 tests: the read-only, grounded AI care agent.

The agent must answer only from the patient's stored, gate-approved data:
unclear items never get a dose or a time, as-needed items never get a fixed
slot, dose changes/interactions/diagnosis are refused, and the optional LLM
cannot smuggle in an unverified number or time.
"""

from __future__ import annotations

import secrets
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from conftest import PRIMARY_PHONE, otp_login

from app.agent import context as agent_context
from app.agent import llm as agent_llm
from app.agent.context import build_context
from app.agent.llm import is_safe_answer
from app.db import SessionLocal
from app.main import app
from app.models import MedicineItem, Patient, Prescription


def _fresh_phone() -> str:
    return "+9198" + "".join(secrets.choice("0123456789") for _ in range(7))


def _ask(client, message: str, lang: str | None = None) -> dict:
    payload: dict = {"message": message}
    if lang:
        payload["lang"] = lang
    response = client.post("/api/agent/chat", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def _context(lang: str = "en"):
    db = SessionLocal()
    try:
        patient = db.query(Patient).filter(Patient.phone == PRIMARY_PHONE).one()
        return build_context(db, patient, lang)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Auth + shape
# ---------------------------------------------------------------------------


def test_agent_requires_authentication():
    with TestClient(app) as anonymous:
        chat = anonymous.post("/api/agent/chat", json={"message": "What medicines do I take?"})
        assert chat.status_code == 401
        suggestions = anonymous.get("/api/agent/suggestions")
        assert suggestions.status_code == 401


def test_agent_response_shape(client, demo_prescription):
    data = _ask(client, "What medicines do I take?")
    assert set(data) == {
        "reply",
        "lang",
        "intent",
        "grounded",
        "escalate",
        "safety_blocked",
        "disclaimer",
        "sources",
    }
    assert data["intent"] == "list_medicines"
    assert data["grounded"] is True
    assert data["disclaimer"]
    assert data["sources"]
    assert all(source["status"] in {"clear", "confirmed", "edited", "unclear"} for source in data["sources"])


# ---------------------------------------------------------------------------
# Grounding: only verified data
# ---------------------------------------------------------------------------


def test_list_medicines_uses_stored_values(client, demo_prescription):
    data = _ask(client, "What medicines do I take?")
    reply = data["reply"]
    assert "Paracetamol" in reply
    assert "Amoxicillin" in reply
    assert "Cough Syrup" in reply
    assert "Cetirizine" in reply
    assert "500 mg" in reply
    assert "250 mg" in reply
    # Unclear item is named but never given a dose/time.
    cetirizine_line = next(line for line in reply.splitlines() if "Cetirizine" in line)
    assert "21:00" not in cetirizine_line
    assert "0-0-1" not in cetirizine_line
    assert "mg" not in cetirizine_line
    assert "??" not in reply


def test_unclear_item_never_gets_dose_or_time(client, demo_prescription):
    for question in ("When should I take Cetirizine?", "What is the dose of Cetirizine?"):
        data = _ask(client, question)
        reply = data["reply"]
        assert "21:00" not in reply
        assert "0-0-1" not in reply
        assert "mg" not in reply.lower()
        assert "confirm" in reply.lower()


def test_as_needed_item_has_no_fixed_time(client, demo_prescription):
    data = _ask(client, "When should I take Cough Syrup?")
    assert data["intent"] == "medicine_time"
    reply = data["reply"].lower()
    assert "as needed" in reply
    assert "no fixed time" in reply
    assert "08:00" not in reply
    assert "21:00" not in reply


def test_timetable_contains_only_verified_fixed_slots(client, demo_prescription):
    data = _ask(client, "What is my timetable today?")
    assert data["intent"] == "schedule_today"
    reply = data["reply"]
    assert "08:00" in reply
    assert "13:00" in reply
    assert "21:00" in reply
    assert "Paracetamol" in reply
    assert "Amoxicillin" in reply
    assert "Cetirizine" not in reply
    assert "Cough Syrup" not in reply


def test_medicine_time_lists_verified_slots(client, demo_prescription):
    data = _ask(client, "When should I take Paracetamol?")
    assert data["intent"] == "medicine_time"
    assert "08:00" in data["reply"]
    assert "21:00" in data["reply"]
    assert "13:00" not in data["reply"]
    assert data["sources"][0]["medicine"] == "Paracetamol"


def test_sources_belong_to_the_caller(client, demo_prescription):
    data = _ask(client, "What medicines do I take?")
    own = {row["id"] for row in client.get("/api/prescriptions").json()}
    assert {source["prescription_id"] for source in data["sources"]} <= own


# ---------------------------------------------------------------------------
# Refusals + escalation
# ---------------------------------------------------------------------------


def test_dose_change_is_refused(client, demo_prescription):
    data = _ask(client, "Can I double my dose?")
    assert data["intent"] == "dose_change"
    assert data["safety_blocked"] is True
    reply = data["reply"].lower()
    assert "cannot" in reply
    assert "doctor" in reply or "pharmacist" in reply
    assert "yes" not in reply.split()


def test_missed_dose_never_suggests_doubling(client, demo_prescription):
    data = _ask(client, "I missed my Paracetamol dose")
    assert data["intent"] == "missed_dose"
    reply = data["reply"]
    assert "Do not take a double dose" in reply
    assert "08:00" in reply
    assert "21:00" in reply


def test_side_effects_escalate_to_a_human(client, demo_prescription):
    data = _ask(client, "I have a rash and dizziness")
    assert data["intent"] == "side_effects"
    assert data["escalate"] is True
    reply = data["reply"].lower()
    assert "doctor" in reply or "pharmacist" in reply
    assert "emergency" in reply


def test_emergency_escalates(client, demo_prescription):
    data = _ask(client, "I have chest pain and cannot breathe")
    assert data["intent"] == "emergency"
    assert data["escalate"] is True
    assert "emergency" in data["reply"].lower()


def test_diagnosis_is_refused(client, demo_prescription):
    data = _ask(client, "What disease do I have?")
    assert data["intent"] == "diagnosis"
    assert data["safety_blocked"] is True
    assert "doctor" in data["reply"].lower()


def test_interaction_is_refused(client, demo_prescription):
    data = _ask(client, "Can I drink alcohol with my medicine?")
    assert data["intent"] == "interaction"
    assert data["safety_blocked"] is True
    assert "pharmacist" in data["reply"].lower() or "doctor" in data["reply"].lower()


# ---------------------------------------------------------------------------
# Languages + suggestions
# ---------------------------------------------------------------------------


def test_tamil_answer(client, demo_prescription):
    data = _ask(client, "என் மருந்துகள் என்ன?", lang="ta")
    assert data["lang"] == "ta"
    assert any("\u0B80" <= ch <= "\u0BFF" for ch in data["reply"])
    assert "Paracetamol" in data["reply"]


def test_hindi_answer(client, demo_prescription):
    data = _ask(client, "मेरी दवाइयाँ क्या हैं?", lang="hi")
    assert data["lang"] == "hi"
    assert any("\u0900" <= ch <= "\u097F" for ch in data["reply"])
    assert "Paracetamol" in data["reply"]


def test_chat_defaults_to_patient_language():
    with TestClient(app) as fresh:
        token = otp_login(fresh, _fresh_phone(), "Language Test")
        headers = {"Authorization": f"Bearer {token}"}
        assert fresh.patch(
            "/api/patients/me", json={"preferred_lang": "ta"}, headers=headers
        ).status_code == 200
        data = fresh.post(
            "/api/agent/chat",
            json={"message": "என் மருந்துகள் என்ன?"},
            headers=headers,
        ).json()
        assert data["lang"] == "ta"


def test_suggestions_are_localized_and_grounded(client, demo_prescription):
    english = client.get("/api/agent/suggestions?lang=en").json()
    assert english["lang"] == "en"
    assert len(english["suggestions"]) >= 4
    assert any("Paracetamol" in question for question in english["suggestions"])

    tamil = client.get("/api/agent/suggestions?lang=ta").json()
    assert tamil["lang"] == "ta"
    assert all(
        any("\u0B80" <= ch <= "\u0BFF" for ch in question)
        for question in tamil["suggestions"]
    )


def test_blank_message_is_rejected(client):
    assert client.post("/api/agent/chat", json={"message": ""}).status_code == 422
    assert client.post("/api/agent/chat", json={"message": "   "}).status_code == 422


# ---------------------------------------------------------------------------
# Patient isolation
# ---------------------------------------------------------------------------


def test_other_patient_has_no_access_to_my_medicines(client, demo_prescription):
    with TestClient(app) as other:
        token = otp_login(other, _fresh_phone(), "Isolation Test")
        response = other.post(
            "/api/agent/chat",
            json={"message": "What medicines do I take?"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        reply = response.json()["reply"]
        assert "Paracetamol" not in reply
        assert "Cetirizine" not in reply


def test_agent_is_read_only(client, demo_prescription):
    db = SessionLocal()
    try:
        before = (
            db.query(MedicineItem).count(),
            db.query(Prescription).count(),
        )
    finally:
        db.close()
    _ask(client, "What medicines do I take?")
    _ask(client, "When should I take Paracetamol?")
    _ask(client, "What is my timetable today?")
    db = SessionLocal()
    try:
        after = (
            db.query(MedicineItem).count(),
            db.query(Prescription).count(),
        )
    finally:
        db.close()
    assert before == after


# ---------------------------------------------------------------------------
# LLM guard
# ---------------------------------------------------------------------------


def _fake_settings(**overrides) -> SimpleNamespace:
    base = dict(
        agent_llm_provider="openai",
        agent_llm_api_key="test-key",
        agent_llm_model="test-model",
        agent_llm_base_url="https://example.invalid/v1",
        agent_llm_timeout_seconds=5.0,
        agent_llm_max_tokens=200,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_llm_is_off_by_default(client, demo_prescription, monkeypatch):
    def _must_not_call(_payload):
        raise AssertionError("LLM must not be called when unconfigured")

    monkeypatch.setattr(agent_llm, "_post_chat", _must_not_call)
    data = _ask(client, "Tell me a joke")
    assert data["intent"] == "unknown"
    assert data["grounded"] is False
    assert "verified" in data["reply"].lower()


def test_llm_safe_answer_is_returned(client, demo_prescription, monkeypatch):
    monkeypatch.setattr(agent_llm, "get_settings", lambda: _fake_settings())
    monkeypatch.setattr(
        agent_llm,
        "_post_chat",
        lambda _payload: {
            "choices": [{"message": {"content": "Ask your doctor or pharmacist about that."}}]
        },
    )
    data = _ask(client, "Tell me a joke")
    assert data["intent"] == "unknown_llm"
    assert data["grounded"] is True
    assert data["reply"] == "Ask your doctor or pharmacist about that."


def test_llm_invented_dose_is_rejected(client, demo_prescription, monkeypatch):
    monkeypatch.setattr(agent_llm, "get_settings", lambda: _fake_settings())
    monkeypatch.setattr(
        agent_llm,
        "_post_chat",
        lambda _payload: {
            "choices": [{"message": {"content": "Take 1000 mg twice a day at 10:00."}}]
        },
    )
    data = _ask(client, "Tell me a joke")
    assert data["intent"] == "unknown"
    assert "1000 mg" not in data["reply"]
    assert "10:00" not in data["reply"]


def test_llm_transport_error_falls_back(client, demo_prescription, monkeypatch):
    monkeypatch.setattr(agent_llm, "get_settings", lambda: _fake_settings())

    def _boom(_payload):
        raise agent_llm.LLMError("down")

    monkeypatch.setattr(agent_llm, "_post_chat", _boom)
    data = _ask(client, "Tell me a joke")
    assert data["intent"] == "unknown"
    assert data["grounded"] is False


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("Paracetamol 500 mg is taken at 08:00.", True),
        ("Take 1000 mg of Paracetamol.", False),
        ("Take it at 09:30.", False),
        ("Take two tablets now.", False),
        ("You should increase your dose.", False),
        ("Cetirizine 5 is fine.", False),
        ("Take 500 mg at 13:00.", True),
    ],
)
def test_is_safe_answer_rules(answer, expected):
    context = _context()
    assert is_safe_answer(answer, context) is expected


def test_is_safe_answer_enforces_language_script():
    assert is_safe_answer("Ask your doctor.", _context("en")) is True
    assert is_safe_answer("மருத்துவரிடம் கேளுங்கள்.", _context("en")) is False
    assert is_safe_answer("மருத்துவரிடம் கேளுங்கள்.", _context("ta")) is True
    assert is_safe_answer("Ask your doctor.", _context("ta")) is False


def test_prompt_has_verified_data_but_no_source_text_or_phone():
    context = _context()
    prompt = context.prompt_text()
    assert "Paracetamol" in prompt
    assert "500 mg" in prompt
    assert "08:00" in prompt
    assert "??" not in prompt
    assert "1-0-1" not in prompt
    assert PRIMARY_PHONE not in prompt
    assert "Tab Paracetamol 500 mg 1-0-1 after food x 5 days" not in prompt
    assert "DO NOT STATE A DOSE" in prompt


def test_context_excluded_entries_have_no_source_text():
    context = _context()
    for entry in context.schedule["excluded"]:
        assert "source_text" not in entry
    unclear = next(item for item in context.items if not item.scheduleable)
    assert unclear.instruction == ""
    assert unclear.times == ()


def test_agent_package_does_not_import_pipeline_modules():
    import ast
    from pathlib import Path

    package = Path(agent_context.__file__).parent
    forbidden = {"parser", "ocr", "seed", "pdf", "extract"}
    for path in package.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                parts = set(node.module.split("."))
                assert not (parts & forbidden), f"{path.name} imports {node.module}"
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not (set(alias.name.split(".")) & forbidden), (
                        f"{path.name} imports {alias.name}"
                    )
