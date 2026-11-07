"""Reminder delivery channels (Phase 3).

Every channel implements :class:`ChannelAdapter`. Development uses
:class:`~app.channels.fake.FakeChannel` — it records the send and returns a
fake provider id, so the whole engine is exercised without contacting
anyone. Real WhatsApp/SMS/voice adapters read their provider config from the
environment and report ``configured=False`` until wired in Phase 4b.

Choosing a channel is NOT done here: the dispatcher requires explicit
patient consent for the channel first (see ``app.reminders``).
"""

from .base import ChannelAdapter, ChannelDeliveryError, ChannelNotConfigured, DeliveryResult
from .fake import FakeChannel
from .registry import adapter_for

#: the reminder channels, in preference order (also the consent vocabulary)
REMINDER_CHANNELS: tuple[str, ...] = ("whatsapp", "sms", "voice")

__all__ = [
    "ChannelAdapter",
    "ChannelDeliveryError",
    "ChannelNotConfigured",
    "DeliveryResult",
    "FakeChannel",
    "REMINDER_CHANNELS",
    "adapter_for",
]
