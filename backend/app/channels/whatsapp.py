"""WhatsApp Cloud API adapter — credentials land in Phase 4b.

Once ``MEDRECALL_WHATSAPP_TOKEN`` and ``MEDRECALL_WHATSAPP_PHONE_NUMBER_ID``
are set, :attr:`configured` flips true and Phase 4b replaces :meth:`send`
with the real Graph API call. Until then the dispatcher marks occurrences
``failed`` (production) or uses the fake channel (development) — it never
pretends a message was delivered.
"""

from __future__ import annotations

import os

from .base import ChannelAdapter, ChannelNotConfigured, DeliveryResult


class WhatsAppAdapter(ChannelAdapter):
    name = "whatsapp"
    env_vars = ("MEDRECALL_WHATSAPP_TOKEN", "MEDRECALL_WHATSAPP_PHONE_NUMBER_ID")

    @property
    def configured(self) -> bool:
        return all(os.environ.get(var) for var in self.env_vars)

    def send(self, to_phone: str, body: str) -> DeliveryResult:  # noqa: ARG002
        raise ChannelNotConfigured(
            "WhatsApp Cloud API is not configured (Phase 4b wires the provider)."
        )
