"""Phase 4 provider-adapter tests.

All HTTP is mocked — no test ever contacts WhatsApp or Twilio. The tests pin
the exact payloads (so a refactor cannot silently change what is sent), the
error classification that drives retries, and the rule that adapters are
dumb pipes: they deliver the dispatcher's text unchanged.
"""

from __future__ import annotations

import json
from urllib.parse import parse_qs

import httpx
import pytest

from app.channels import ChannelDeliveryError, ChannelNotConfigured, FakeChannel
from app.channels.registry import adapter_for
from app.channels.sms import SmsAdapter
from app.channels.voice import VoiceAdapter
from app.channels.whatsapp import WhatsAppAdapter
from app.core.config import Settings
from app.reminders import retry_delay_seconds


def _settings(**overrides) -> Settings:
    base = {
        "whatsapp_token": "",
        "whatsapp_phone_number_id": "",
        "whatsapp_api_base": "https://graph.test",
        "whatsapp_api_version": "v21.0",
        "whatsapp_template_name": "",
        "whatsapp_template_lang": "en",
        "sms_account_sid": "",
        "sms_auth_token": "",
        "sms_from": "",
        "voice_account_sid": "",
        "voice_auth_token": "",
        "voice_from": "",
        "twilio_api_base": "https://api.twilio.test",
        "channel_mode": "fake",
        "environment": "development",
    }
    base.update(overrides)
    return Settings(**base)


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


BODY = "MedRecall: Paracetamol 500 mg — after food, morning"


# ---------------------------------------------------------------------------
# WhatsApp Cloud API
# ---------------------------------------------------------------------------


def test_whatsapp_requires_credentials():
    adapter = WhatsAppAdapter(settings=_settings())
    assert adapter.configured is False
    with pytest.raises(ChannelNotConfigured):
        adapter.send("+919876543210", BODY)


def test_whatsapp_freeform_payload_and_result():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["json"] = json.loads(request.content)
        return httpx.Response(200, json={"messages": [{"id": "wamid.123"}]})

    adapter = WhatsAppAdapter(
        settings=_settings(whatsapp_token="tok", whatsapp_phone_number_id="123"),
        client=_client(handler),
    )
    result = adapter.send("+91 98765-43210", BODY, lang="ta")

    assert seen["url"] == "https://graph.test/v21.0/123/messages"
    assert seen["auth"] == "Bearer tok"
    payload = seen["json"]
    assert payload["messaging_product"] == "whatsapp"
    assert payload["to"] == "919876543210"  # digits only, no leading +
    assert payload["type"] == "text"
    assert payload["text"]["body"] == BODY  # exact dispatcher text, unchanged
    assert result.message_id == "wamid.123"
    assert result.channel == "whatsapp"


def test_whatsapp_template_payload_when_configured():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["json"] = json.loads(request.content)
        return httpx.Response(200, json={"messages": [{"id": "wamid.t"}]})

    adapter = WhatsAppAdapter(
        settings=_settings(
            whatsapp_token="tok",
            whatsapp_phone_number_id="123",
            whatsapp_template_name="medrecall_reminder",
            whatsapp_template_lang="ta",
        ),
        client=_client(handler),
    )
    adapter.send("+919876543210", BODY)

    payload = seen["json"]
    assert payload["type"] == "template"
    assert payload["template"]["name"] == "medrecall_reminder"
    assert payload["template"]["language"]["code"] == "ta"
    assert payload["template"]["components"][0]["parameters"][0]["text"] == BODY


@pytest.mark.parametrize(
    ("status", "transient"),
    [(400, False), (401, False), (404, False), (429, True), (500, True), (503, True)],
)
def test_whatsapp_error_classification(status, transient):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"message": "provider said no"}})

    adapter = WhatsAppAdapter(
        settings=_settings(whatsapp_token="tok", whatsapp_phone_number_id="123"),
        client=_client(handler),
    )
    with pytest.raises(ChannelDeliveryError) as excinfo:
        adapter.send("+919876543210", BODY)

    assert excinfo.value.transient is transient
    assert f"HTTP {status}" in str(excinfo.value)
    assert "provider said no" in str(excinfo.value)
    assert "tok" not in str(excinfo.value)  # never leak credentials


def test_whatsapp_network_error_is_transient():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    adapter = WhatsAppAdapter(
        settings=_settings(whatsapp_token="tok", whatsapp_phone_number_id="123"),
        client=_client(handler),
    )
    with pytest.raises(ChannelDeliveryError) as excinfo:
        adapter.send("+919876543210", BODY)
    assert excinfo.value.transient is True


def test_whatsapp_2xx_without_message_id_is_not_retried():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"messages": []})

    adapter = WhatsAppAdapter(
        settings=_settings(whatsapp_token="tok", whatsapp_phone_number_id="123"),
        client=_client(handler),
    )
    with pytest.raises(ChannelDeliveryError) as excinfo:
        adapter.send("+919876543210", BODY)
    assert excinfo.value.transient is False


# ---------------------------------------------------------------------------
# Twilio SMS
# ---------------------------------------------------------------------------


def test_sms_requires_credentials():
    adapter = SmsAdapter(settings=_settings())
    assert adapter.configured is False
    with pytest.raises(ChannelNotConfigured):
        adapter.send("+919876543210", BODY)


def test_sms_payload_auth_and_result():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization", "")
        seen["form"] = parse_qs(request.content.decode("utf-8"))
        return httpx.Response(201, json={"sid": "SM123"})

    adapter = SmsAdapter(
        settings=_settings(
            sms_account_sid="AC123", sms_auth_token="secret", sms_from="+15550001111"
        ),
        client=_client(handler),
    )
    result = adapter.send("+919876543210", BODY)

    assert seen["url"] == "https://api.twilio.test/2010-04-01/Accounts/AC123/Messages.json"
    assert seen["auth"].startswith("Basic ")
    assert seen["form"]["To"] == ["+919876543210"]
    assert seen["form"]["From"] == ["+15550001111"]
    assert seen["form"]["Body"] == [BODY]
    assert result.message_id == "SM123"
    assert result.channel == "sms"


@pytest.mark.parametrize(
    ("status", "transient"),
    [(400, False), (401, False), (429, True), (502, True)],
)
def test_sms_error_classification(status, transient):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"message": "twilio error"})

    adapter = SmsAdapter(
        settings=_settings(
            sms_account_sid="AC123", sms_auth_token="secret", sms_from="+15550001111"
        ),
        client=_client(handler),
    )
    with pytest.raises(ChannelDeliveryError) as excinfo:
        adapter.send("+919876543210", BODY)
    assert excinfo.value.transient is transient
    assert f"HTTP {status}" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Twilio voice
# ---------------------------------------------------------------------------


def test_voice_requires_credentials():
    adapter = VoiceAdapter(settings=_settings())
    assert adapter.configured is False
    with pytest.raises(ChannelNotConfigured):
        adapter.send("+919876543210", BODY)


def test_voice_twiml_escapes_body_and_maps_language():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["form"] = parse_qs(request.content.decode("utf-8"))
        return httpx.Response(201, json={"sid": "CA123"})

    adapter = VoiceAdapter(
        settings=_settings(
            voice_account_sid="AC999", voice_auth_token="secret", voice_from="+15550002222"
        ),
        client=_client(handler),
    )
    result = adapter.send("+919876543210", "MedRecall: <Paracetamol & food>", lang="hi")

    assert seen["url"] == "https://api.twilio.test/2010-04-01/Accounts/AC999/Calls.json"
    assert seen["form"]["To"] == ["+919876543210"]
    assert seen["form"]["From"] == ["+15550002222"]
    assert seen["form"]["Twiml"] == [
        '<Response><Say language="hi-IN">MedRecall: &lt;Paracetamol &amp; food&gt;</Say></Response>'
    ]
    assert result.message_id == "CA123"
    assert result.channel == "voice"


def test_voice_language_map_is_configurable():
    adapter = VoiceAdapter(
        settings=_settings(
            voice_account_sid="AC999",
            voice_auth_token="secret",
            voice_from="+15550002222",
            voice_lang_map="en:en-GB,ta:ta-LK",
        )
    )
    assert 'language="ta-LK"' in adapter.twiml("hello", "ta")
    assert 'language="en-GB"' in adapter.twiml("hello", "en")
    assert 'language="en-US"' in adapter.twiml("hello", "unknown")


def test_voice_error_classification():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"message": "unavailable"})

    adapter = VoiceAdapter(
        settings=_settings(
            voice_account_sid="AC999", voice_auth_token="secret", voice_from="+15550002222"
        ),
        client=_client(handler),
    )
    with pytest.raises(ChannelDeliveryError) as excinfo:
        adapter.send("+919876543210", BODY, lang="en")
    assert excinfo.value.transient is True


# ---------------------------------------------------------------------------
# Registry + backoff
# ---------------------------------------------------------------------------


def test_registry_uses_fake_channels_in_development_when_unconfigured():
    adapter = adapter_for("whatsapp", _settings())
    assert isinstance(adapter, FakeChannel)


def test_registry_uses_real_adapter_when_configured_even_in_fake_mode():
    adapter = adapter_for(
        "whatsapp",
        _settings(whatsapp_token="tok", whatsapp_phone_number_id="123"),
    )
    assert isinstance(adapter, WhatsAppAdapter)
    assert adapter.configured is True


def test_registry_never_fakes_in_production():
    adapter = adapter_for(
        "sms", _settings(channel_mode="fake", environment="production")
    )
    assert isinstance(adapter, SmsAdapter)
    assert adapter.configured is False


def test_registry_rejects_unknown_channel():
    with pytest.raises(ValueError):
        adapter_for("carrier-pigeon", _settings())


def test_retry_delay_is_exponential_and_capped():
    # defaults: base 60s, cap 3600s
    assert retry_delay_seconds(1) == 60
    assert retry_delay_seconds(2) == 120
    assert retry_delay_seconds(3) == 240
    assert retry_delay_seconds(20) == 3600
