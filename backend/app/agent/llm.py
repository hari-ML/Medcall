"""Optional LLM rephrasing for unmatched agent questions (Phase 5).

The LLM is a *presentation* layer, never a medical authority:

* it is only called for the ``unknown`` intent (everything medical, dose,
  reminder or safety related is answered deterministically);
* the prompt contains only :meth:`AgentContext.prompt_text` — verified fields,
  never source text, phone numbers, images, or unclear-item doses;
* :func:`is_safe_answer` rejects any answer that introduces a number, dose
  unit, time, or number-word that is not present in the verified context, that
  mentions an unclear item together with a dose/time, that switches script, or
  that gives a prescribing/diagnosis directive;
* on any error or rejection the caller keeps the deterministic fallback, so
  the feature is strictly additive and fails closed.

The provider is OpenAI-compatible (``POST {base_url}/chat/completions``), so
OpenAI, Azure-compatible gateways, Ollama, vLLM, etc. all work by changing
``MEDRECALL_AGENT_LLM_BASE_URL``.
"""

from __future__ import annotations

import re

import httpx

from ..core.config import get_settings
from .context import AgentContext

#: hard cap on returned text — a care answer is a few sentences, not an essay
MAX_ANSWER_CHARS = 1200

#: number words that could smuggle a dose ("take two tablets") past digit checks
NUMBER_WORDS = (
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "twenty",
    "thirty",
    "once",
    "twice",
    "thrice",
    "half",
    "ஒன்று",
    "இரண்டு",
    "மூன்று",
    "நான்கு",
    "ஐந்து",
    "ஆறு",
    "ஏழு",
    "எட்டு",
    "ஒன்பது",
    "பத்து",
    "ஒரு",
    "இரு",
    "एक",
    "दो",
    "तीन",
    "चार",
    "पाँच",
    "पांच",
    "छह",
    "सात",
    "आठ",
    "नौ",
    "दस",
    "आधी",
)

#: directives the agent must never emit (prescribing / dose changes / diagnosis)
BANNED_PATTERNS = (
    r"\bincrease (?:your|the) dose\b",
    r"\bdecrease (?:your|the) dose\b",
    r"\bdouble (?:your|the) dose\b",
    r"\bdouble dose\b",
    r"\bextra dose\b",
    r"\bchange (?:your|the) dose\b",
    r"\bstop taking\b",
    r"\byou (?:have|are diagnosed with)\b",
    r"\bdiagnosis is\b",
    r"\bஅளவை (?:அதிகரிக்க|குறைக்க)\b",
    r"\bமருந்தை நிறுத்த\b",
    r"\bमात्रा (?:बढ़ा|घटा)\b",
    r"\bदवा बंद\b",
)

_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")
_TIME_RE = re.compile(r"\b\d{1,2}:\d{2}\b")
_MASS_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(mg|ml|mcg|µg|g|iu|%)\b", re.IGNORECASE
)
_TAMIL_RE = re.compile(r"[\u0B80-\u0BFF]")
_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")
_LATIN_RE = re.compile(r"[A-Za-z]")


class LLMError(Exception):
    """The provider was unreachable or returned an unusable response."""


def is_llm_configured() -> bool:
    settings = get_settings()
    provider = (settings.agent_llm_provider or "none").strip().lower()
    return (
        provider == "openai"
        and bool(settings.agent_llm_api_key.strip())
        and bool(settings.agent_llm_model.strip())
    )


def _normalise(text: str) -> str:
    return " ".join((text or "").casefold().split())


def _allowed_text(context: AgentContext) -> str:
    """Everything the LLM is allowed to echo: verified data + profile basics."""
    return "\n".join(
        [
            context.safety_text(),
            context.today,
            context.timezone,
            context.language_name,
            context.schedule.get("title", ""),
            context.schedule.get("disclaimer", ""),
        ]
    )


def _numbers(text: str) -> set[str]:
    return {match.replace(",", ".") for match in _NUMBER_RE.findall(text or "")}


def _mass_pairs(text: str) -> set[str]:
    return {
        f"{num.replace(',', '.')} {unit.lower()}"
        for num, unit in _MASS_RE.findall(text or "")
    }


def _times(text: str) -> set[str]:
    return set(_TIME_RE.findall(text or ""))


def _number_words(text: str) -> set[str]:
    normalised = _normalise(text)
    found: set[str] = set()
    for word in NUMBER_WORDS:
        if _TAMIL_RE.search(word) or _DEVANAGARI_RE.search(word):
            if word in normalised:
                found.add(word)
        elif re.search(rf"\b{re.escape(word)}\b", normalised):
            found.add(word)
    return found


def is_safe_answer(answer: str, context: AgentContext) -> bool:
    """True only if ``answer`` introduces no unverified clinical value.

    This is deliberately conservative: a false rejection just falls back to the
    deterministic reply, while a false acceptance could invent a dose.
    """
    text = (answer or "").strip()
    if not text or len(text) > MAX_ANSWER_CHARS:
        return False

    lowered = text.casefold()
    for pattern in BANNED_PATTERNS:
        if re.search(pattern, lowered):
            return False

    # Language consistency: an English answer must not silently switch script.
    if context.lang == "ta" and not _TAMIL_RE.search(text):
        return False
    if context.lang == "hi" and not _DEVANAGARI_RE.search(text):
        return False
    if context.lang == "en" and (
        _TAMIL_RE.search(text) or _DEVANAGARI_RE.search(text)
    ):
        return False

    allowed = _allowed_text(context)
    allowed_numbers = _numbers(allowed)
    allowed_mass = _mass_pairs(allowed)
    allowed_times = _times(allowed)
    allowed_words = _number_words(allowed)

    # Any digit must already exist in verified data (covers doses, counts,
    # durations and dates alike).
    if not _numbers(text) <= allowed_numbers:
        return False

    # A mass/unit pair must match a verified pair exactly ("500 mg" != "1000 mg").
    if not _mass_pairs(text) <= allowed_mass:
        return False

    # Any clock time must be one of the verified slot times.
    if not _times(text) <= allowed_times:
        return False

    # Number words ("take two") must appear in verified text.
    if not _number_words(text) <= allowed_words:
        return False

    # Never attach a dose/time to an item that is still unclear.
    unclear_names = [
        item.medicine.casefold()
        for item in context.items
        if not item.scheduleable and item.medicine
    ]
    if any(name in lowered for name in unclear_names) and (
        _numbers(text) or _times(text) or _mass_pairs(text)
    ):
        return False

    return True


def _system_prompt(context: AgentContext) -> str:
    return (
        "You are MedRecall's care agent. You explain a patient's own verified "
        "prescription data in their language. HARD RULES:\n"
        "1. Use ONLY the verified data below. Never add medical knowledge.\n"
        "2. Never prescribe, diagnose, suggest a dose change, or interpret "
        "symptoms or interactions. Tell the patient to ask a doctor/pharmacist.\n"
        "3. Never state a dose, strength, frequency, time, or duration that is "
        "not literally in the verified data. Never invent a number.\n"
        "4. Items marked as needing confirmation have NO dose/frequency/time. "
        "Do not guess them.\n"
        "5. As-needed medicines have no fixed time and no reminder.\n"
        "6. Answer in the patient's language code given below. Be brief "
        "(max 3 short sentences), plain text, no markdown.\n"
        "7. If the question cannot be answered from the verified data, say you "
        "do not know and suggest asking the doctor or pharmacist.\n\n"
        f"PATIENT LANGUAGE CODE: {context.lang}\n\n"
        f"{context.prompt_text()}"
    )


def _post_chat(payload: dict) -> dict:
    """One OpenAI-compatible chat completion call (separate for easy mocking)."""
    settings = get_settings()
    base = settings.agent_llm_base_url.rstrip("/")
    url = f"{base}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.agent_llm_api_key}",
        "Content-Type": "application/json",
    }
    try:
        response = httpx.post(
            url,
            json=payload,
            headers=headers,
            timeout=settings.agent_llm_timeout_seconds,
        )
    except httpx.HTTPError as exc:  # timeouts, DNS, connection refused
        raise LLMError(f"agent LLM request failed: {type(exc).__name__}") from exc
    if response.status_code >= 400:
        raise LLMError(f"agent LLM returned HTTP {response.status_code}")
    try:
        return response.json()
    except ValueError as exc:
        raise LLMError("agent LLM returned non-JSON") from exc


def answer_with_llm(question: str, context: AgentContext) -> str | None:
    """Rephrase an unmatched question from verified data, or return ``None``.

    ``None`` means "keep the deterministic fallback" and is the result for an
    unconfigured provider, any transport error, a malformed response, or an
    answer that fails :func:`is_safe_answer`.
    """
    if not is_llm_configured():
        return None
    settings = get_settings()
    payload = {
        "model": settings.agent_llm_model,
        "messages": [
            {"role": "system", "content": _system_prompt(context)},
            {"role": "user", "content": (question or "").strip()[:500]},
        ],
        "temperature": 0,
        "max_tokens": settings.agent_llm_max_tokens,
    }
    try:
        data = _post_chat(payload)
        answer = data["choices"][0]["message"]["content"]
    except (LLMError, KeyError, IndexError, TypeError):
        return None
    if not isinstance(answer, str):
        return None
    answer = answer.strip()
    if not is_safe_answer(answer, context):
        return None
    return answer
