"""Adapter registry: real provider when configured, fake in development."""

from __future__ import annotations

from ..core.config import Settings, get_settings
from .base import ChannelAdapter, ChannelNotConfigured
from .fake import FakeChannel
from .sms import SmsAdapter
from .voice import VoiceAdapter
from .whatsapp import WhatsAppAdapter

_ADAPTERS: dict[str, type[ChannelAdapter]] = {
    "whatsapp": WhatsAppAdapter,
    "sms": SmsAdapter,
    "voice": VoiceAdapter,
}


def adapter_for(channel: str, settings: Settings | None = None) -> ChannelAdapter:
    """The adapter for ``channel``.

    * configured real provider -> use it
    * development + fake mode  -> FakeChannel (records the send)
    * production, unconfigured -> the real adapter (reports configured=False;
      the dispatcher then marks the occurrence failed — never "sent")
    """
    try:
        adapter_class = _ADAPTERS[channel]
    except KeyError:
        raise ValueError(f"Unknown reminder channel: {channel!r}") from None

    resolved = settings or get_settings()
    real = adapter_class(settings=resolved)
    if real.configured:
        return real
    if resolved.use_fake_channels:
        return FakeChannel(channel)
    return real


__all__ = ["adapter_for", "ChannelNotConfigured"]
