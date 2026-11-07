"""Voice-call adapter — credentials land in Phase 4b.

The call would read the same verified instruction text (text-to-speech);
no dose is ever synthesized beyond the stored timetable.
"""

from __future__ import annotations

import os

from .base import ChannelAdapter, ChannelNotConfigured, DeliveryResult


class VoiceAdapter(ChannelAdapter):
    name = "voice"
    env_vars = ("MEDRECALL_VOICE_ACCOUNT_SID", "MEDRECALL_VOICE_AUTH_TOKEN", "MEDRECALL_VOICE_FROM")

    @property
    def configured(self) -> bool:
        return all(os.environ.get(var) for var in self.env_vars)

    def send(self, to_phone: str, body: str) -> DeliveryResult:  # noqa: ARG002
        raise ChannelNotConfigured(
            "Voice provider is not configured (Phase 4b wires the provider)."
        )
