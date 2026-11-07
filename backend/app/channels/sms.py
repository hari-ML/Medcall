"""SMS adapter — credentials land in Phase 4b (e.g. Twilio/MSG91).

Unconfigured adapters are never silently treated as delivered.
"""

from __future__ import annotations

import os

from .base import ChannelAdapter, ChannelNotConfigured, DeliveryResult


class SmsAdapter(ChannelAdapter):
    name = "sms"
    env_vars = ("MEDRECALL_SMS_ACCOUNT_SID", "MEDRECALL_SMS_AUTH_TOKEN", "MEDRECALL_SMS_FROM")

    @property
    def configured(self) -> bool:
        return all(os.environ.get(var) for var in self.env_vars)

    def send(self, to_phone: str, body: str) -> DeliveryResult:  # noqa: ARG002
        raise ChannelNotConfigured(
            "SMS provider is not configured (Phase 4b wires the provider)."
        )
