"""Channel adapter interface and provider-error helpers.

Adapters are deliberately *dumb pipes*: they deliver the exact text the
dispatcher hands them and never import the parser, gate, translator or
scheduler. All medical content is built from the verified timetable in
``app.reminders`` — a channel can never invent or alter a dose.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import httpx


class ChannelNotConfigured(Exception):
    """The provider for this channel has no credentials — nothing is sent."""


class ChannelDeliveryError(Exception):
    """A provider rejected or failed the send.

    ``transient`` drives the dispatcher's retry policy: 429/5xx/timeouts are
    retried with exponential backoff until the attempt limit, while 4xx
    errors (bad number, bad template, revoked credentials) fail immediately.
    """

    def __init__(self, message: str, *, transient: bool) -> None:
        super().__init__(message)
        self.transient = transient


@dataclass(frozen=True)
class DeliveryResult:
    """What a successful adapter send returns."""

    message_id: str
    channel: str


def is_transient_status(status_code: int) -> bool:
    """HTTP statuses worth retrying (rate limit / provider-side failures)."""
    return status_code == 429 or status_code >= 500


@dataclass
class InteractiveButton:
    """One reply button on an outbound interactive message.

    ``id`` is an opaque callback token for the inbound webhook (e.g.
    ``TAKEN_123``); ``title`` is the short label shown to the patient
    (WhatsApp limit: 20 characters).
    """

    id: str
    title: str


@dataclass
class InteractiveMessage:
    """Structured reply actions accompanying an outbound message.

    Adapters stay dumb pipes: the dispatcher builds both the exact body text
    and these actions from the verified timetable. A button id references a
    reminder occurrence — it never carries medical content of its own.
    """

    buttons: list[InteractiveButton]


def provider_error_message(provider: str, response: httpx.Response) -> str:
    """A short, secret-free error string for the occurrence row.

    Only the provider's own message is included — never request headers,
    tokens, or the full response body.
    """
    detail = ""
    try:
        data: Any = response.json()
    except ValueError:
        data = None
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict):
            detail = str(error.get("message") or error.get("code") or "")
        elif error:
            detail = str(error)
        if not detail:
            detail = str(data.get("message") or "")
    if not detail:
        detail = (response.text or "").strip()[:200]
    detail = " ".join(detail.split())[:300]
    return f"{provider} HTTP {response.status_code}" + (f": {detail}" if detail else "")


def post_provider(
    provider: str,
    url: str,
    *,
    settings: Any,
    client: httpx.Client | None = None,
    **kwargs: Any,
) -> httpx.Response:
    """POST to a provider, translating transport/HTTP failures into our error.

    A caller-supplied client is used as-is (tests inject an
    ``httpx.MockTransport``); otherwise a short-lived client with the
    configured timeout is created so no connection pool leaks.
    """
    try:
        if client is not None:
            response = client.post(url, **kwargs)
        else:
            with httpx.Client(timeout=settings.http_timeout_seconds) as owned:
                response = owned.post(url, **kwargs)
    except httpx.HTTPError as exc:
        raise ChannelDeliveryError(
            f"{provider} request failed ({type(exc).__name__})", transient=True
        ) from exc

    if response.status_code >= 400:
        raise ChannelDeliveryError(
            provider_error_message(provider, response),
            transient=is_transient_status(response.status_code),
        )
    return response


class ChannelAdapter(ABC):
    """One way of reaching a patient (WhatsApp / SMS / voice call)."""

    name: str = ""

    @property
    @abstractmethod
    def configured(self) -> bool:
        """True when this adapter can actually deliver right now."""

    @abstractmethod
    def send(
        self,
        to_phone: str,
        body: str,
        *,
        lang: str = "en",
        interactive: InteractiveMessage | None = None,
    ) -> DeliveryResult:
        """Deliver ``body`` to ``to_phone``; raise on failure.

        ``lang`` is used only for provider-side voice/template selection.
        ``interactive`` carries structured reply buttons for channels that
        support them (WhatsApp); plain-SMS/voice adapters ignore it.
        Implementations must never invent or modify the message content —
        the dispatcher builds it from the verified timetable.
        """

    def send_otp(self, to_phone: str, code: str, *, lang: str = "en") -> DeliveryResult:
        """Deliver a 6-digit login code as a plain transactional message.

        Generic, adapter-agnostic copy (no medical content), so it lives on
        the base class; providers may override it — WhatsApp sends the code
        as an approved-template parameter when a template is configured.
        """
        body = (
            f"MedRecall verification code: {code}. "
            "It expires in 10 minutes. Never share it with anyone."
        )
        return self.send(to_phone, body, lang=lang)
