"""WhatsApp Cloud API adapter (Meta Graph).

Sends the dispatcher-built reminder text. Two modes:

* **template** — set ``MEDRECALL_WHATSAPP_TEMPLATE_NAME`` to an approved
  template whose body takes one parameter (``{{1}}``). Required for
  business-initiated messages outside WhatsApp's 24-hour service window.
* **free-form text** — no template configured; only works inside the
  24-hour customer-service window (fine for the sandbox / patient replies).

Credentials: ``MEDRECALL_WHATSAPP_TOKEN`` + ``MEDRECALL_WHATSAPP_PHONE_NUMBER_ID``.
Unconfigured adapters are never treated as delivered.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from ..core.config import Settings, get_settings
from .base import (
    ChannelAdapter,
    ChannelDeliveryError,
    ChannelNotConfigured,
    DeliveryResult,
    post_provider,
)


class WhatsAppAdapter(ChannelAdapter):
    name = "whatsapp"

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
            self.settings.whatsapp_token.strip()
            and self.settings.whatsapp_phone_number_id.strip()
        )

    def _payload(self, to_phone: str, body: str) -> dict[str, Any]:
        # WhatsApp expects digits with the country code, no leading "+".
        to = re.sub(r"\D", "", to_phone)
        template = self.settings.whatsapp_template_name.strip()
        if template:
            return {
                "messaging_product": "whatsapp",
                "to": to,
                "type": "template",
                "template": {
                    "name": template,
                    "language": {"code": self.settings.whatsapp_template_lang.strip() or "en"},
                    "components": [
                        {
                            "type": "body",
                            "parameters": [{"type": "text", "text": body}],
                        }
                    ],
                },
            }
        return {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {"preview_url": False, "body": body},
        }

    def send(self, to_phone: str, body: str, *, lang: str = "en") -> DeliveryResult:
        if not self.configured:
            raise ChannelNotConfigured(
                "WhatsApp Cloud API is not configured "
                "(MEDRECALL_WHATSAPP_TOKEN / MEDRECALL_WHATSAPP_PHONE_NUMBER_ID)."
            )

        url = (
            f"{self.settings.whatsapp_api_base.rstrip('/')}/"
            f"{self.settings.whatsapp_api_version.strip('/')}/"
            f"{self.settings.whatsapp_phone_number_id}/messages"
        )
        response = post_provider(
            "WhatsApp",
            url,
            settings=self.settings,
            client=self._client,
            headers={
                "Authorization": f"Bearer {self.settings.whatsapp_token}",
                "Content-Type": "application/json",
            },
            json=self._payload(to_phone, body),
        )

        try:
            data = response.json()
        except ValueError:
            data = {}
        messages = data.get("messages") if isinstance(data, dict) else None
        message_id = ""
        if isinstance(messages, list) and messages and isinstance(messages[0], dict):
            message_id = str(messages[0].get("id") or "")
        if not message_id:
            # 2xx without an id cannot be proven delivered; do not retry and
            # risk a duplicate dose reminder — surface it for ops instead.
            raise ChannelDeliveryError(
                "WhatsApp response did not include a message id", transient=False
            )
        return DeliveryResult(message_id=message_id, channel=self.name)
