"""Translation tests: all three languages + the unclear-item hard stop."""

from __future__ import annotations

import pytest

from app.translate import (
    AS_NEEDED_HEADING,
    DISCLAIMER_TEXT,
    EXCLUDED_HEADING,
    FREQUENCY_PHRASES,
    FOOD_PHRASES,
    FORM_WORDS,
    LANGUAGE_PREVIEWS,
    SLOT_NAMES,
    SUPPORTED_LANGUAGES,
    TemplateTranslator,
    TITLES,
    Translator,
    UnclearItemError,
    UnsupportedLanguageError,
    frequency_phrase,
    get_translator,
    translate_instruction,
)

LANGS = ["en", "ta", "hi"]


# ---------------------------------------------------------------------------
# Instruction sentence in all 3 languages
# ---------------------------------------------------------------------------


def test_instruction_english_exact(clear_item):
    text = translate_instruction(clear_item, "en")
    assert text == "500 mg tablet, 1 in the morning, 1 at night, after food, for 5 days"


def test_instruction_tamil(clear_item):
    text = translate_instruction(clear_item, "ta")
    assert "500 mg" in text
    assert "மாத்திரை" in text            # tablet
    assert "உணவுக்குப் பின்" in text      # after food
    assert "நாட்களுக்கு" in text          # days
    assert text != translate_instruction(clear_item, "en")  # actually translated


def test_instruction_hindi(clear_item):
    text = translate_instruction(clear_item, "hi")
    assert "500 mg" in text
    assert "गोली" in text                 # tablet
    assert "खाने के बाद" in text          # after food
    assert "दिनों" in text                # days
    assert text != translate_instruction(clear_item, "en")


@pytest.mark.parametrize("lang", LANGS)
def test_medicine_name_never_in_instruction(clear_item, lang):
    # medicine names stay in Latin script in the DATA, but the instruction
    # sentence itself is built from translated parts only.
    assert "Paracetamol" not in translate_instruction(clear_item, lang)


@pytest.mark.parametrize("lang", LANGS)
def test_instruction_covers_dose_frequency_food_duration(clear_item, lang):
    text = translate_instruction(clear_item, lang)
    assert "500 mg" in text
    assert len(text.split(",")) >= 4  # dose, frequency, food, duration parts


# ---------------------------------------------------------------------------
# Phrase tables in all 3 languages
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("code", ["OD", "BD", "TDS", "QID", "HS", "SOS"])
def test_frequency_phrases_all_languages(lang, code):
    phrase = frequency_phrase(code, lang)
    assert phrase
    assert phrase == FREQUENCY_PHRASES[lang][code]


@pytest.mark.parametrize("lang", LANGS)
def test_nnn_frequency_phrase(lang):
    phrase = frequency_phrase("1-0-1", lang)
    assert phrase
    # one component for morning + one for night
    assert phrase.count(",") == 1


def test_frequency_phrase_english_nnn_readable():
    assert frequency_phrase("1-0-1", "en") == "1 in the morning, 1 at night"


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("food", ["before", "after", "with", "empty_stomach"])
def test_food_phrases_all_languages(lang, food):
    assert FOOD_PHRASES[lang][food]


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("form", ["tab", "cap", "syrup", "inj"])
def test_form_words_all_languages(lang, form):
    assert FORM_WORDS[form][lang]


@pytest.mark.parametrize("lang", LANGS)
def test_slot_names_all_languages(lang):
    assert set(SLOT_NAMES[lang]) == {"morning", "afternoon", "evening", "night"}
    assert all(SLOT_NAMES[lang].values())


@pytest.mark.parametrize("lang", LANGS)
def test_duration_phrasing(lang):
    translator = get_translator(lang)
    five_days = translate_instruction(
        {"status": "clear", "duration_days": 5, "frequency": "OD", "form": "tab",
         "strength": "100 mg"}, lang)
    one_day = translate_instruction(
        {"status": "clear", "duration_days": 1, "frequency": "OD", "form": "tab",
         "strength": "100 mg"}, lang)
    assert "5" in five_days
    assert "1" in one_day
    assert five_days != one_day  # singular/plural handled


@pytest.mark.parametrize("lang", LANGS)
def test_disclaimer_present_all_languages(lang):
    text = get_translator(lang).disclaimer()
    assert text == DISCLAIMER_TEXT[lang]
    assert "MedRecall" in text


@pytest.mark.parametrize("lang", LANGS)
def test_headings_present_all_languages(lang):
    t = get_translator(lang)
    assert t.title() == TITLES[lang]
    assert t.as_needed_heading() == AS_NEEDED_HEADING[lang]
    assert t.excluded_heading() == EXCLUDED_HEADING[lang]
    assert t.slot_name("morning") == SLOT_NAMES[lang]["morning"]


@pytest.mark.parametrize("lang", LANGS)
def test_language_preview_sentence_exists(lang):
    assert LANGUAGE_PREVIEWS[lang].strip()


def test_as_needed_instruction(clear_item, as_needed_item):
    text = translate_instruction(as_needed_item, "en")
    assert "three times a day" in text
    assert "as needed" in text


# ---------------------------------------------------------------------------
# Safety hard stop
# ---------------------------------------------------------------------------


def test_unclear_item_raises(clear_item):
    unclear = {**clear_item, "status": "unclear", "reason": "Dose unreadable"}
    with pytest.raises(UnclearItemError):
        translate_instruction(unclear, "en")
    with pytest.raises(UnclearItemError):
        translate_instruction(unclear, "ta")


def test_missing_status_raises(clear_item):
    item = {k: v for k, v in clear_item.items() if k != "status"}
    with pytest.raises(UnclearItemError):
        translate_instruction(item, "en")


@pytest.mark.parametrize("status", ["clear", "confirmed", "edited"])
def test_safe_statuses_translatable(clear_item, status):
    assert translate_instruction({**clear_item, "status": status}, "en")


def test_unsupported_language(clear_item):
    with pytest.raises(UnsupportedLanguageError):
        translate_instruction(clear_item, "fr")
    with pytest.raises(UnsupportedLanguageError):
        get_translator("de")


def test_supported_languages_are_exactly_three():
    assert SUPPORTED_LANGUAGES == ("en", "ta", "hi")


def test_translator_is_extensible():
    # The pluggable interface: a subclass only implements instruction().
    class FakeTranslator(Translator):
        def instruction(self, item, lang=None):
            return "FAKE"

    fake = FakeTranslator("ta")
    assert fake.instruction({"status": "clear"}) == "FAKE"
    assert fake.slot_name("night") == SLOT_NAMES["ta"]["night"]  # shared helpers work
    assert isinstance(get_translator("en"), TemplateTranslator)
