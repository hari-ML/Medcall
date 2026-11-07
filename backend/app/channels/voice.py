"""Twilio voice-call adapter.

The call reads the same verified instruction text through TwiML
``<Say>``. The language comes from the reminder schedule; the mapping is
configurable because provider TTS coverage differs by language
(``MEDRECALL_VOICE_LANG_MAP``, default ``en:en-US,ta:ta-IN,hi:hi-IN``).

Credentials: ``MEDRECALL_VOICE_ACCOUNT_SID``, ``MEDRECALL_VOICE_AUTH_TOKEN``,
``MEDRECALL_VOICE_FROM``. Unconfigured adapters are never treated as
delivered.
"""

from __future__ import annotations

from xml.sax.saxutils import escape

import httpx

from ..core.config import Settings, get_settings
from .base import (
    ChannelAdapter,
    ChannelDeliveryError,
    ChannelNotConfigured,
    DeliveryResult,
    post_provider,
)


class VoiceAdapter(ChannelAdapter):
    name = "voice"

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
            self.settings.voice_account_sid.strip()
            and self.settings.voice_auth_token.strip()
            and self.settings.voice_from.strip()
        )

    def twiml(self, body: str, lang: str) -> str:
        say_lang = self.settings.voice_lang_map_dict.get(lang, "en-US")
        return f'<Response><Say language="{say_lang}">{escape(body)}</Say></Response>'

    def send(self, to_phone: str, body: str, *, lang: str = "en") -> DeliveryResult:
        if not self.configured:
            raise ChannelNotConfigured(
                "Voice provider is not configured "
                "(MEDRECALL_VOICE_ACCOUNT_SID / MEDRECALL_VOICE_AUTH_TOKEN / MEDRECALL_VOICE_FROM)."
            )

        account_sid = self.settings.voice_account_sid
        url = (
            f"{self.settings.twilio_api_base.rstrip('/')}/2010-04-01/"
            f"Accounts/{account_sid}/Calls.json"
        )
        response = post_provider(
            "Voice",
            url,
            settings=self.settings,
            client=self._client,
            auth=(account_sid, self.settings.voice_auth_token),
            data={
                "To": to_phone,
                "From": self.settings.voice_from,
                "Twiml": self.twiml(body, lang),
            },
        )

        try:
            data = response.json()
        except ValueError:
            data = {}
        call_id = str(data.get("sid") or "") if isinstance(data, dict) else ""
        if not call_id:
            raise ChannelDeliveryError(
                "Voice provider response did not include a call id", transient=False
            )
        return DeliveryResult(message_id=call_id, channel=self.name)
