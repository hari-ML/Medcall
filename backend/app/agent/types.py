"""Shared value objects for the care agent (Phase 5)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentSource:
    """One verified record the answer is based on (never an unclear item's dose)."""

    prescription_id: int
    item_id: int | None
    medicine: str
    status: str


@dataclass(frozen=True)
class AgentReply:
    reply: str
    lang: str
    intent: str
    grounded: bool
    escalate: bool
    disclaimer: str
    safety_blocked: bool = False
    sources: tuple[AgentSource, ...] = ()
