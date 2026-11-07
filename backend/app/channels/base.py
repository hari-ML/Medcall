"""Channel adapter interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


class ChannelNotConfigured(Exception):
    """The provider for this channel has no credentials — nothing is sent."""


@dataclass(frozen=True)
class DeliveryResult:
    """What a successful adapter send returns."""

    message_id: str
    channel: str


class ChannelAdapter(ABC):
    """One way of reaching a patient (WhatsApp / SMS / voice call)."""

    name: str = ""

    @property
    @abstractmethod
    def configured(self) -> bool:
        """True when this adapter can actually deliver right now."""

    @abstractmethod
    def send(self, to_phone: str, body: str) -> DeliveryResult:
        """Deliver ``body`` to ``to_phone``; raise on failure.

        Implementations must never invent or modify the message content —
        the dispatcher builds it from the verified timetable.
        """
