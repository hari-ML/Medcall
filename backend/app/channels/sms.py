"""Twilio SMS adapter.

Credentials: ``MEDRECALL_SMS_ACCOUNT_SID``, ``MEDRECALL_SMS_AUTH_TOKEN``,
``MEDRECALL_SMS_FROM`` (an E.164 Twilio number). Unconfigured adapters are
never treated as delivered.
"""

from __future__ import annotations

import httpx

from ..core.config import Settings, get_settings
from .base import (
    ChannelAdapter,
    ChannelDeliveryError,
    ChannelNotConfigured,
    DeliveryResult,
    post_provider,
)


class SmsAdapter(ChannelAdapter):
    name = "sms"

    def __init__(
        self,
        settings: Settings | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._client = client

    @property
    def configured(self) -> bool:
        return bool(
            self.settings.sms_account_sid.strip()
            and self.settings.sms_auth_token.strip()
            and self.settings.sms_from.strip()
        )

    def send(self, to_phone: str, body: str, *, lang: str = "en") -> DeliveryResult:
        if not self.configured:
            raise ChannelNotConfigured(
                "SMS provider is not configured "
                "(MEDRECALL_SMS_ACCOUNT_SID / MEDRECALL_SMS_AUTH_TOKEN / MEDRECALL_SMS_FROM)."
            )

        account_sid = self.settings.sms_account_sid
        url = (
            f"{self.settings.twilio_api_base.rstrip('/')}/2010-04-01/"
            f"Accounts/{account_sid}/Messages.json"
        )
        response = post_provider(
            "SMS",
            url,
            settings=self.settings,
            client=self._client,
            auth=(account_sid, self.settings.sms_auth_token),
            data={
                "To": to_phone,
                "From": self.settings.sms_from,
                "Body": body,
            },
        )

        try:
            data = response.json()
        except ValueError:
            data = {}
        message_id = str(data.get("sid") or "") if isinstance(data, dict) else ""
        if not message_id:
            raise ChannelDeliveryError(
                "SMS provider response did not include a message id", transient=False
            )
        return DeliveryResult(message_id=message_id, channel=self.name)
