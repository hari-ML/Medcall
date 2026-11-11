"""Development fake channel: exercises the engine without contacting anyone.

The send is fully recorded on the occurrence row (body, channel, provider
message id), so tests and the audit can prove exactly what would have been
delivered — and that nothing was delivered without consent.
"""

from __future__ import annotations

import logging
import uuid

from .base import ChannelAdapter, DeliveryResult, InteractiveMessage

logger = logging.getLogger("medrecall.channels")


class FakeChannel(ChannelAdapter):
    """Always configured; returns a ``fake-<channel>-<hex>`` message id.

    Development/test only — :func:`app.channels.registry.adapter_for` never
    selects it in production (see ``Settings.effective_channel_provider``).
    """

    def __init__(self, name: str) -> None:
        self.name = name

    @property
    def configured(self) -> bool:
        return True

    def send(
        self,
        to_phone: str,
        body: str,
        *,
        lang: str = "en",
        interactive: InteractiveMessage | None = None,
    ) -> DeliveryResult:
        message_id = f"fake-{self.name}-{uuid.uuid4().hex[:12]}"
        buttons = (
            ",".join(button.id for button in interactive.buttons) if interactive else "-"
        )
        logger.info(
            "FAKE %s -> %s [%s] buttons=%s: %s",
            self.name,
            to_phone,
            lang,
            buttons,
            body,
        )
        return DeliveryResult(message_id=message_id, channel=self.name)
