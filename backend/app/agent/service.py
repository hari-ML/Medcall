"""Care-agent orchestration (Phase 5).

Flow for one chat turn:

1. Build the patient-scoped verified context (:func:`build_context`).
2. Detect the intent with multilingual keyword tables (deterministic).
3. Answer deterministically — the default and the only path for every
   medication/dose/reminder/safety question.
4. Only for an unmatched ``unknown`` question, optionally ask the LLM to
   rephrase an answer from the same context; a rejected/failed answer keeps
   the deterministic fallback.

Read-only: this module never writes to the database and never touches the
parser, OCR, gate, seed data, PDF or reminder engine.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import Patient
from .context import AgentContext, build_context
from .intents import detect_intent
from .llm import answer_with_llm
from .responder import respond, suggestions as build_suggestions
from .types import AgentReply, AgentSource


def _context(db: Session, patient: Patient, lang: str) -> AgentContext:
    return build_context(db, patient, lang or "en")


def chat(db: Session, patient: Patient, message: str, lang: str = "en") -> AgentReply:
    """One grounded answer for one question. Never raises for LLM failures."""
    context = _context(db, patient, lang)
    match = detect_intent(message, context)

    if match.intent == "unknown":
        answer = answer_with_llm(message, context)
        if answer:
            sources: tuple[AgentSource, ...] = tuple(
                AgentSource(
                    prescription_id=item.prescription_id,
                    item_id=item.item_id,
                    medicine=item.medicine,
                    status=item.status,
                )
                for item in context.items[:20]
            )
            return AgentReply(
                reply=answer,
                lang=context.lang,
                intent="unknown_llm",
                grounded=True,
                escalate=False,
                disclaimer=context.schedule.get("disclaimer", ""),
                safety_blocked=False,
                sources=sources,
            )

    return respond(match, context)


def suggestions(db: Session, patient: Patient, lang: str = "en") -> list[str]:
    """Starter questions for the chat UI, localized and grounded."""
    return build_suggestions(_context(db, patient, lang))
