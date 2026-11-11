"""AI care agent endpoints + inbound delivery webhooks (Phase 5, Part 3).

* ``POST /api/agent/chat`` — one grounded answer about the caller's own
  verified medicines, timetable, unclear items or reminders.
* ``GET /api/agent/suggestions`` — localized starter questions.
* ``GET/POST /api/webhooks/whatsapp`` — Meta verification + inbound button
  replies (TAKEN / SNOOZE / HELP) and free-text questions.
* ``POST /api/webhooks/sms`` — Twilio inbound SMS (TAKEN / SNOOZE / SKIP /
  SCHEDULE / HELP or a natural-language question) answered with TwiML.

Patient routes require a Bearer access token and are scoped to the caller via
``get_current_patient``; the agent layer itself only reads the caller's rows.
Webhooks authenticate with the provider's own signature (Meta
``X-Hub-Signature-256`` / Twilio ``X-Twilio-Signature``) when the secret is
configured, fail closed for WhatsApp verification, and never return medical
data for an unknown number.

The agent is read-only: it cannot confirm, edit, enroll, schedule or send.
The webhooks only record the patient's own reply on an existing occurrence
(``patient_action``) and, for SNOOZE, create one follow-up pending occurrence
through the reminder engine — every safety gate is re-checked at dispatch.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import re
from typing import Any, Optional
from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from ..agent import chat as agent_chat
from ..agent import suggestions as agent_suggestions
from ..channels import ChannelDeliveryError, ChannelNotConfigured, adapter_for
from ..core.config import get_settings
from ..core.deps import get_current_patient
from ..db import get_db
from ..models import Patient
from ..reminders import recent_occurrence, record_patient_action, snooze_occurrence
from ..schemas import (
    AgentChatIn,
    AgentChatOut,
    AgentSourceOut,
    AgentSuggestionsOut,
    LangCode,
)
from ..translate import webhook_ack

logger = logging.getLogger("medrecall.webhooks")

router = APIRouter()

#: TAKEN / TAKEN_123 / "snooze 42" — the id is optional for plain SMS.
_ACTION_RE = re.compile(r"^(TAKEN|SNOOZE|SKIP|HELP)(?:[_\s:#-]+(\d+))?$", re.IGNORECASE)


def _lang(requested: Optional[str], patient: Patient) -> str:
    return requested or (patient.preferred_lang or "en")


# ---------------------------------------------------------------------------
# Patient agent routes
# ---------------------------------------------------------------------------


@router.post("/api/agent/chat", response_model=AgentChatOut)
def chat(
    payload: AgentChatIn,
    patient: Patient = Depends(get_current_patient),
    db: Session = Depends(get_db),
) -> AgentChatOut:
    reply = agent_chat(db, patient, payload.message, _lang(payload.lang, patient))
    return AgentChatOut(
        reply=reply.reply,
        lang=reply.lang,
        intent=reply.intent,
        grounded=reply.grounded,
        escalate=reply.escalate,
        safety_blocked=reply.safety_blocked,
        disclaimer=reply.disclaimer,
        sources=[
            AgentSourceOut(
                prescription_id=source.prescription_id,
                item_id=source.item_id,
                medicine=source.medicine,
                status=source.status,
            )
            for source in reply.sources
        ],
    )


@router.get("/api/agent/suggestions", response_model=AgentSuggestionsOut)
def suggestions(
    lang: Optional[LangCode] = Query(default=None),
    patient: Patient = Depends(get_current_patient),
    db: Session = Depends(get_db),
) -> AgentSuggestionsOut:
    resolved = _lang(lang, patient)
    return AgentSuggestionsOut(
        lang=resolved,
        suggestions=agent_suggestions(db, patient, resolved),
    )


# ---------------------------------------------------------------------------
# Shared inbound helpers
# ---------------------------------------------------------------------------


def _digits(raw: str) -> str:
    return re.sub(r"\D", "", raw or "")


def _patient_by_phone(db: Session, raw: str) -> Patient | None:
    """Match a provider's phone format to the stored normalised number."""
    digits = _digits(raw)
    if not digits:
        return None
    candidates = ["+" + digits, digits]
    if len(digits) >= 10:
        candidates.append("+" + digits[-10:])
    for candidate in candidates:
        patient = db.query(Patient).filter(Patient.phone == candidate).first()
        if patient is not None:
            return patient
    if len(digits) >= 10:
        # Stored numbers may omit the country code; compare the last 10 digits.
        return (
            db.query(Patient)
            .filter(Patient.phone.endswith(digits[-10:]))
            .first()
        )
    return None


def _parse_action(text: str) -> tuple[str, int | None] | None:
    match = _ACTION_RE.match((text or "").strip())
    if not match:
        return None
    occurrence_id = int(match.group(2)) if match.group(2) else None
    return match.group(1).lower(), occurrence_id


def _handle_action(
    db: Session, patient: Patient, action: str, occurrence_id: int | None
) -> str:
    """Record TAKEN/SNOOZE/SKIP on an existing occurrence and build the ack.

    The reply only repeats the stored medicine name; it never adds a dose or
    a time. A snooze creates a new pending occurrence through the engine,
    which re-checks every gate before any send.
    """
    lang = patient.preferred_lang or "en"
    occurrence = recent_occurrence(db, patient.id, occurrence_id)
    if occurrence is None:
        key = "no_recent" if occurrence_id is None else "not_found"
        return webhook_ack(key, lang)

    schedule = occurrence.schedule
    item = schedule.item if schedule is not None else None
    medicine = (item.medicine_name if item is not None else "") or "your medicine"

    record_patient_action(db, occurrence, action)
    if action == "snooze":
        minutes = max(1, get_settings().webhook_snooze_minutes)
        snooze_occurrence(db, occurrence, minutes)
        return webhook_ack("snooze", lang, medicine=medicine, minutes=minutes)
    return webhook_ack(action, lang, medicine=medicine)


def _help_reply(db: Session, patient: Patient) -> str:
    """Grounded help text from the care agent (never a dose of its own)."""
    return agent_chat(db, patient, "help", patient.preferred_lang or "en").reply


def _answer_text(db: Session, patient: Patient, text: str) -> str:
    """Route an inbound free-text message through the grounded agent."""
    action = _parse_action(text)
    if action is not None:
        name, occurrence_id = action
        if name == "help":
            return _help_reply(db, patient)
        return _handle_action(db, patient, name, occurrence_id)
    return agent_chat(db, patient, text, patient.preferred_lang or "en").reply


def _send_whatsapp_reply(patient: Patient, text: str) -> None:
    """Best-effort reply on the channel the message arrived on."""
    try:
        adapter = adapter_for("whatsapp")
        adapter.send(patient.phone, text, lang=patient.preferred_lang or "en")
    except (ChannelNotConfigured, ChannelDeliveryError, ValueError) as exc:
        logger.warning(
            "WhatsApp webhook reply to patient %s failed: %s", patient.id, str(exc)[:200]
        )


def _twiml(message: str) -> Response:
    body = escape(message or "")
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f"<Response><Message>{body}</Message></Response>"
    )
    return Response(content=xml, media_type="application/xml")


def _whatsapp_messages(payload: Any) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    if not isinstance(payload, dict):
        return messages
    for entry in payload.get("entry") or []:
        if not isinstance(entry, dict):
            continue
        for change in entry.get("changes") or []:
            if not isinstance(change, dict):
                continue
            value = change.get("value") or {}
            for message in value.get("messages") or []:
                if isinstance(message, dict):
                    messages.append(message)
    return messages


def _message_text(message: dict[str, Any]) -> str:
    """The button payload / button id / plain text of an inbound message."""
    kind = message.get("type")
    if kind == "button":
        button = message.get("button") or {}
        return str(button.get("payload") or button.get("text") or "")
    if kind == "interactive":
        interactive = message.get("interactive") or {}
        reply = interactive.get("button_reply") or interactive.get("list_reply") or {}
        return str(reply.get("id") or reply.get("title") or "")
    text = message.get("text")
    if isinstance(text, dict):
        return str(text.get("body") or "")
    return ""


def _valid_whatsapp_signature(request: Request, raw_body: bytes) -> bool:
    """Verify Meta's X-Hub-Signature-256 when an app secret is configured."""
    secret = get_settings().whatsapp_app_secret.strip()
    if not secret:
        return True
    header = request.headers.get("x-hub-signature-256", "")
    expected = "sha256=" + hmac.new(
        secret.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()
    return bool(header) and hmac.compare_digest(expected, header)


def _valid_twilio_signature(request: Request, form: dict[str, str]) -> bool:
    """Verify Twilio's X-Twilio-Signature when token + public URL are set."""
    settings = get_settings()
    token = settings.sms_auth_token.strip()
    base = settings.public_base_url.strip()
    if not token or not base:
        return True
    header = request.headers.get("x-twilio-signature", "")
    if not header:
        return False
    url = base.rstrip("/") + request.url.path
    if request.url.query:
        url += "?" + request.url.query
    payload = url + "".join(key + form[key] for key in sorted(form))
    digest = hmac.new(token.encode("utf-8"), payload.encode("utf-8"), hashlib.sha1).digest()
    expected = base64.b64encode(digest).decode("ascii")
    return hmac.compare_digest(expected, header)


# ---------------------------------------------------------------------------
# WhatsApp webhook (Meta Cloud API)
# ---------------------------------------------------------------------------


@router.get("/api/webhooks/whatsapp", response_class=PlainTextResponse)
def verify_whatsapp(request: Request) -> Response:
    """Meta's subscription handshake — fail closed without a verify token."""
    settings = get_settings()
    expected = settings.whatsapp_verify_token.strip()
    mode = request.query_params.get("hub.mode", "")
    token = request.query_params.get("hub.verify_token", "")
    challenge = request.query_params.get("hub.challenge", "")
    if not expected or mode != "subscribe" or not hmac.compare_digest(expected, token):
        raise HTTPException(status_code=403, detail="Webhook verification failed.")
    return PlainTextResponse(challenge)


@router.post("/api/webhooks/whatsapp")
async def whatsapp_webhook(request: Request, db: Session = Depends(get_db)) -> dict:
    """Inbound button replies and free-text questions from WhatsApp.

    Always answers 200 for well-formed Meta callbacks (Meta retries on
    non-2xx). Unknown numbers and malformed messages are logged and ignored —
    no medical data is ever returned to an unverified caller.
    """
    raw_body = await request.body()
    if not _valid_whatsapp_signature(request, raw_body):
        raise HTTPException(status_code=403, detail="Invalid webhook signature.")
    try:
        payload = json.loads(raw_body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(status_code=400, detail="Malformed webhook payload.")

    for message in _whatsapp_messages(payload):
        phone = str(message.get("from") or "")
        patient = _patient_by_phone(db, phone)
        if patient is None:
            logger.info("WhatsApp webhook from unregistered number (ignored)")
            continue
        text = _message_text(message)
        if not text.strip():
            continue
        try:
            reply = _answer_text(db, patient, text)
        except Exception:  # noqa: BLE001 - one bad reply must not break the webhook
            logger.exception("WhatsApp webhook reply failed for patient %s", patient.id)
            continue
        _send_whatsapp_reply(patient, reply)

    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Twilio SMS webhook
# ---------------------------------------------------------------------------


@router.post("/api/webhooks/sms")
async def sms_webhook(request: Request, db: Session = Depends(get_db)) -> Response:
    """Inbound SMS: TAKEN / SNOOZE / SKIP / SCHEDULE / HELP or a question.

    Responds with TwiML so Twilio delivers the acknowledgement as a reply.
    Signature validation is enforced when ``MEDRECALL_PUBLIC_BASE_URL`` and
    the Twilio auth token are configured.
    """
    form = dict(await request.form())
    if not _valid_twilio_signature(request, form):
        raise HTTPException(status_code=403, detail="Invalid webhook signature.")

    patient = _patient_by_phone(db, str(form.get("From") or ""))
    if patient is None:
        logger.info("SMS webhook from unregistered number (ignored)")
        return _twiml(
            "This number is not registered with MedRecall. "
            "Please create an account in the app first."
        )

    body = str(form.get("Body") or "").strip()
    if not body:
        return _twiml(_help_reply(db, patient))

    upper = body.upper()
    if upper.startswith("SCHEDULE"):
        reply = agent_chat(db, patient, "schedule", patient.preferred_lang or "en").reply
    elif upper.startswith("HELP"):
        reply = _help_reply(db, patient)
    else:
        try:
            reply = _answer_text(db, patient, body)
        except Exception:  # noqa: BLE001 - Twilio still needs valid TwiML
            logger.exception("SMS webhook reply failed for patient %s", patient.id)
            reply = webhook_ack("no_recent", patient.preferred_lang or "en")

    return _twiml(reply)
