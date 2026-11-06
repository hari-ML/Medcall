"""Template-based translation for MedRecall (English / Tamil / Hindi).

No ML model: instructions are composed from hand-written phrase tables for
frequency, food timing, dosage form, duration, slot names and headings.
Medicine names always stay in the original (Latin) script — only the
surrounding instruction words are translated.

SAFETY: every entry point validates the item's status first. Items that are
not ``clear | confirmed | edited`` raise :class:`UnclearItemError` and are
never rendered.

Pluggable: implement :class:`Translator.instruction()` against any engine
(IndicTrans2, a cloud translation API, ...) and return it from
:func:`get_translator` — the rest of the app needs no changes.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any, Mapping

from .uncertainty import SCHEDULEABLE_STATUSES

SUPPORTED_LANGUAGES = ("en", "ta", "hi")

LANG_NAMES: dict[str, str] = {
    "en": "English",
    "ta": "தமிழ் (Tamil)",
    "hi": "हिन्दी (Hindi)",
}


class TranslationError(Exception):
    """Base class for translation failures."""


class UnsupportedLanguageError(TranslationError):
    """Raised for an unsupported target language."""


class UnclearItemError(TranslationError):
    """Raised when an unclear/unscheduled item is passed for translation.

    This is the hard safety stop: it must never happen in normal flow
    (schedule.py filters first); if it does, the bug fails loudly.
    """


# ---------------------------------------------------------------------------
# Phrase tables (en / ta / hi)
# ---------------------------------------------------------------------------

SLOT_NAMES: dict[str, dict[str, str]] = {
    "en": {"morning": "Morning", "afternoon": "Afternoon", "evening": "Evening", "night": "Night"},
    "ta": {"morning": "காலை", "afternoon": "மதியம்", "evening": "மாலை", "night": "இரவு"},
    "hi": {"morning": "सुबह", "afternoon": "दोपहर", "evening": "शाम", "night": "रात"},
}

#: Slot adverbs used inside "N-in-the-morning" style phrases.
SLOT_ADVERBS: dict[str, dict[str, str]] = {
    "en": {
        "morning": "in the morning",
        "afternoon": "in the afternoon",
        "night": "at night",
    },
    "ta": {"morning": "காலையில்", "afternoon": "மதியம்", "night": "இரவில்"},
    "hi": {"morning": "सुबह", "afternoon": "दोपहर", "night": "रात में"},
}

FREQUENCY_PHRASES: dict[str, dict[str, str]] = {
    "en": {
        "OD": "once a day",
        "BD": "twice a day",
        "TDS": "three times a day",
        "QID": "four times a day",
        "HS": "at bedtime",
        "SOS": "as needed",
    },
    "ta": {
        "OD": "ஒரு நாளைக்கு ஒரு முறை",
        "BD": "ஒரு நாளைக்கு இரண்டு முறை",
        "TDS": "ஒரு நாளைக்கு மூன்று முறை",
        "QID": "ஒரு நாளைக்கு நான்கு முறை",
        "HS": "தூங்கும் முன்",
        "SOS": "தேவைப்படும்போது",
    },
    "hi": {
        "OD": "दिन में एक बार",
        "BD": "दिन में दो बार",
        "TDS": "दिन में तीन बार",
        "QID": "दिन में चार बार",
        "HS": "सोने से पहले",
        "SOS": "ज़रूरत पड़ने पर",
    },
}

FOOD_PHRASES: dict[str, dict[str, str]] = {
    "en": {
        "before": "before food",
        "after": "after food",
        "with": "with food",
        "empty_stomach": "on an empty stomach",
    },
    "ta": {
        "before": "உணவுக்கு முன்",
        "after": "உணவுக்குப் பின்",
        "with": "உணவுடன்",
        "empty_stomach": "வயிறு காலியாக",
    },
    "hi": {
        "before": "खाने से पहले",
        "after": "खाने के बाद",
        "with": "खाने के साथ",
        "empty_stomach": "खाली पेट",
    },
}

FORM_WORDS: dict[str, dict[str, str]] = {
    "tab": {"en": "tablet", "ta": "மாத்திரை", "hi": "गोली"},
    "cap": {"en": "capsule", "ta": "காப்சூல்", "hi": "कैप्सूल"},
    "syrup": {"en": "syrup", "ta": "சிரப்", "hi": "सिरप"},
    "inj": {"en": "injection", "ta": "ஊசி", "hi": "इंजेक्शन"},
    "drops": {"en": "drops", "ta": "சொட்டுகள்", "hi": "बूँदें"},
    "ointment": {"en": "ointment", "ta": "கிரீம்", "hi": "मलहम"},
    "inhaler": {"en": "inhaler", "ta": "இன்ஹேலர்", "hi": "इनहेलर"},
    "suppository": {"en": "suppository", "ta": "சப்போசிடரி", "hi": "सपोजिटरी"},
    "cream": {"en": "cream", "ta": "கிரீம்", "hi": "क्रीम"},
    "gel": {"en": "gel", "ta": "ஜெல்", "hi": "जेल"},
    "sachet": {"en": "sachet", "ta": "சாச்செட்", "hi": "सैशे"},
    "vial": {"en": "vial", "ta": "வயல்", "hi": "वायल"},
}

AS_NEEDED_PHRASE: dict[str, str] = {
    "en": "as needed",
    "ta": "தேவைப்படும்போது",
    "hi": "ज़रूरत पड़ने पर",
}

TITLES: dict[str, str] = {
    "en": "Daily Medicine Timetable",
    "ta": "தினசரி மருந்து அட்டவணை",
    "hi": "दैनिक दवा समय-सारणी",
}

AS_NEEDED_HEADING: dict[str, str] = {
    "en": "As needed (no fixed time)",
    "ta": "தேவைப்படும்போது (நிலையான நேரம் இல்லை)",
    "hi": "ज़रूरत पड़ने पर (निश्चित समय नहीं)",
}

EXCLUDED_HEADING: dict[str, str] = {
    "en": "Needs confirmation — NOT in this timetable",
    "ta": "உறுதிப்படுத்த வேண்டும் — இந்த அட்டவணையில் இல்லை",
    "hi": "पुष्टि आवश्यक — इस समय-सारणी में नहीं",
}

EMPTY_SLOT_NOTE: dict[str, str] = {
    "en": "No medicines scheduled",
    "ta": "மருந்துகள் எதுவும் இல்லை",
    "hi": "कोई दवा निर्धारित नहीं",
}

DISCLAIMER_TEXT: dict[str, str] = {
    "en": "MedRecall explains. It never prescribes. Always confirm with your doctor or pharmacist.",
    "ta": "MedRecall விளக்குகிறது. அது மருந்து எழுதாது. உங்கள் மருத்துவர் அல்லது மருந்தாளரிடம் எப்போதும் உறுதிப்படுத்தவும்.",
    "hi": "MedRecall समझाता है, दवा नहीं लिखता। हमेशा अपने डॉक्टर या फ़ार्मासिस्ट से पुष्टि करें।",
}

#: UI language cards: live preview sentence used on the Language screen.
LANGUAGE_PREVIEWS: dict[str, str] = {
    "en": "1 tablet after food, three times a day",
    "ta": "உணவுக்குப் பின் 1 மாத்திரை, தினமும் மூன்று முறை",
    "hi": "खाने के बाद 1 गोली, दिन में तीन बार",
}


def _check_lang(lang: str) -> str:
    if lang not in SUPPORTED_LANGUAGES:
        raise UnsupportedLanguageError(
            f"Unsupported language {lang!r}. Supported: {', '.join(SUPPORTED_LANGUAGES)}"
        )
    return lang


def _duration_phrase(days: int, lang: str) -> str:
    days = int(days)
    if lang == "en":
        return f"for {days} day" + ("s" if days != 1 else "")
    if lang == "ta":
        return f"{days} நாளுக்கு" if days == 1 else f"{days} நாட்களுக்கு"
    return f"{days} दिन तक" if days == 1 else f"{days} दिनों तक"


def frequency_phrase(code: str | None, lang: str) -> str:
    """Plain phrase for a normalized frequency code, in ``lang``."""
    if not code:
        return ""
    table = FREQUENCY_PHRASES[lang]
    if code in table:
        return table[code]
    if re.fullmatch(r"\d-\d-\d", code):
        parts = []
        for component, slot in zip(code.split("-"), ("morning", "afternoon", "night")):
            count = int(component)
            if count:
                parts.append(f"{count} {SLOT_ADVERBS[lang][slot]}")
        return ", ".join(parts)
    return code


# ---------------------------------------------------------------------------
# Translator interface + template implementation
# ---------------------------------------------------------------------------


class Translator(ABC):
    """Base class every translation backend must implement.

    Subclasses only implement :meth:`instruction`; status validation and the
    generic phrases (slots, headings, disclaimer) live here.
    """

    def __init__(self, lang: str = "en") -> None:
        self.lang = _check_lang(lang)

    # -- safety ------------------------------------------------------------
    @staticmethod
    def validate_item(item: Mapping[str, Any]) -> Mapping[str, Any]:
        """Raise UnclearItemError unless the item may be scheduled."""
        status = item.get("status")
        if status not in SCHEDULEABLE_STATUSES:
            raise UnclearItemError(
                "Refusing to translate an item that is not clear/confirmed/edited "
                f"(status={status!r}, reason={item.get('reason') or 'unclear item'})"
            )
        return item

    # -- the pluggable part -------------------------------------------------
    @abstractmethod
    def instruction(self, item: Mapping[str, Any], lang: str | None = None) -> str:
        """Human sentence telling the user how to take this medicine."""

    # -- shared phrase helpers ---------------------------------------------
    def slot_name(self, slot: str, lang: str | None = None) -> str:
        lang = _check_lang(lang or self.lang)
        return SLOT_NAMES[lang].get(slot, slot.title())

    def title(self, lang: str | None = None) -> str:
        lang = _check_lang(lang or self.lang)
        return TITLES[lang]

    def disclaimer(self, lang: str | None = None) -> str:
        lang = _check_lang(lang or self.lang)
        return DISCLAIMER_TEXT[lang]

    def as_needed_heading(self, lang: str | None = None) -> str:
        lang = _check_lang(lang or self.lang)
        return AS_NEEDED_HEADING[lang]

    def excluded_heading(self, lang: str | None = None) -> str:
        lang = _check_lang(lang or self.lang)
        return EXCLUDED_HEADING[lang]

    def empty_slot_note(self, lang: str | None = None) -> str:
        lang = _check_lang(lang or self.lang)
        return EMPTY_SLOT_NOTE[lang]


class TemplateTranslator(Translator):
    """Phrase-table translator (fast, offline, no model download).

    Example output:
      en  "500 mg tablet, once in the morning, once at night, after food, for 5 days"
      ta  "500 mg மாத்திரை, காலையில் 1, இரவில் 1, உணவுக்குப் பின், 5 நாட்களுக்கு"
      hi  "500 mg गोली, सुबह 1, रात में 1, खाने के बाद, 5 दिनों तक"
    """

    def instruction(self, item: Mapping[str, Any], lang: str | None = None) -> str:
        self.validate_item(item)
        lang = _check_lang(lang or self.lang)

        parts: list[str] = []

        # dose: strength + form word ("500 mg tablet" / "5 ml syrup")
        dose_bits: list[str] = []
        strength = (item.get("strength") or "").strip()
        form = (item.get("form") or "").strip().lower()
        if strength:
            dose_bits.append(strength)
        form_word = FORM_WORDS.get(form, {}).get(lang)
        if form_word:
            dose_bits.append(form_word)
        if dose_bits:
            parts.append(" ".join(dose_bits))

        # frequency ("twice a day" / "1 in the morning, 1 at night")
        freq = frequency_phrase(item.get("frequency"), lang)
        if freq:
            parts.append(freq)

        # scheduled-with-SOS: add the as-needed marker once
        if item.get("as_needed") and item.get("frequency") not in (None, "SOS"):
            parts.append(AS_NEEDED_PHRASE[lang])

        # food timing ("after food")
        food = item.get("food_timing")
        if food:
            parts.append(FOOD_PHRASES[lang].get(food, food))

        # duration ("for 5 days")
        if item.get("duration_days"):
            parts.append(_duration_phrase(int(item["duration_days"]), lang))

        return ", ".join(parts) if parts else ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_DEFAULT = TemplateTranslator


def get_translator(lang: str = "en") -> Translator:
    """Factory: return the translator for ``lang``.

    Swapping in IndicTrans2 / an API later means returning a different
    Translator subclass here — no other module changes.
    """
    _check_lang(lang)
    return _DEFAULT(lang)


def translate_instruction(item: Mapping[str, Any], lang: str = "en") -> str:
    """One-shot helper: translate a scheduleable item's instruction."""
    return get_translator(lang).instruction(item, lang)
