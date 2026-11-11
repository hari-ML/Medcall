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

    Resolution (``Settings.effective_channel_provider``; the plain
    ``CHANNEL_PROVIDER`` env var wins, production can never resolve to fake):

    * ``live`` — always the real provider (configured or not; an
      unconfigured adapter fails honestly rather than pretending).
    * ``fake`` — the development recording channel.
    * ``auto`` — the real provider when its credentials exist, otherwise the
      fake channel in development, otherwise the real adapter in production
      (reports ``configured=False`` — the dispatcher marks the occurrence
      ``failed``, never "sent").
    """
    try:
        adapter_class = _ADAPTERS[channel]
    except KeyError:
        raise ValueError(f"Unknown reminder channel: {channel!r}") from None

    resolved = settings or get_settings()
    provider = resolved.effective_channel_provider
    if provider == "fake":
        return FakeChannel(channel)

    real = adapter_class(settings=resolved)
    if provider == "live":
        return real
    if real.configured:
        return real
    if resolved.use_fake_channels:
        return FakeChannel(channel)
    return real


__all__ = ["adapter_for", "ChannelNotConfigured"]
