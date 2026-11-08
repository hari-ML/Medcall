"""AI care agent (Phase 5) — read-only, grounded, multilingual.

Public surface:

    from app.agent import chat, suggestions

Both answer only from the patient's stored, gate-approved prescription data
(the same ``build_schedule`` used by the timetable and PDF). Unclear items are
never given a dose or a time, as-needed items never get a fixed slot, and the
optional LLM is limited to rephrasing unmatched questions with a numeric/time
safety filter.
"""

from .service import chat, suggestions
from .types import AgentReply, AgentSource

__all__ = ["AgentReply", "AgentSource", "chat", "suggestions"]
