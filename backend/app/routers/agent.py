"""AI care agent endpoints (Phase 5).

* ``POST /api/agent/chat`` — one grounded answer about the caller's own
  verified medicines, timetable, unclear items or reminders.
* ``GET /api/agent/suggestions`` — localized starter questions.

Both routes require a Bearer access token and are scoped to the caller via
``get_current_patient``; the agent layer itself only reads the caller's rows.
The agent is read-only: it cannot confirm, edit, enroll, schedule or send.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..agent import chat as agent_chat
from ..agent import suggestions as agent_suggestions
from ..core.deps import get_current_patient
from ..db import get_db
from ..models import Patient
from ..schemas import (
    AgentChatIn,
    AgentChatOut,
    AgentSourceOut,
    AgentSuggestionsOut,
    LangCode,
)

router = APIRouter()


def _lang(requested: Optional[str], patient: Patient) -> str:
    return requested or (patient.preferred_lang or "en")


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
