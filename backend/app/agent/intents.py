"""Deterministic intent routing for the care agent (Phase 5).

English, Tamil and Hindi keyword tables keep the default (no-LLM) agent
useful offline. When no intent matches, the optional LLM may rephrase an
answer — but only from the verified context and only after the safety filter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .context import AgentContext


@dataclass(frozen=True)
class IntentMatch:
    intent: str
    medicine: str = ""


# ---------------------------------------------------------------------------
# Keyword tables (order matters — safety intents are checked first)
# ---------------------------------------------------------------------------

EMERGENCY = (
    "emergency",
    "chest pain",
    "can't breathe",
    "cannot breathe",
    "breathing difficulty",
    "unconscious",
    "fainting",
    "severe bleeding",
    "stroke",
    "அவசரம்",
    "நெஞ்சு வலி",
    "மூச்சு",
    "மயக்கம்",
    "அதிக இரத்த",
    "आपातकाल",
    "इमरजेंसी",
    "सीने में दर्द",
    "सांस",
    "बेहोश",
    "खून",
)

MISSED = (
    "missed",
    "forgot",
    "forgotten",
    "late dose",
    "didn't take",
    "did not take",
    "skipped",
    "தவறவிட்ட",
    "மறந்த",
    "தாமத",
    "எடுக்கவில்லை",
    "छूट",
    "भूल",
    "देर",
    "नहीं लिया",
)

DOSE_CHANGE = (
    "double",
    "extra dose",
    "increase",
    "decrease",
    "reduce",
    "change my dose",
    "change the dose",
    "take two",
    "take 2",
    "take more",
    "take less",
    "skip",
    "stop taking",
    "stop my medicine",
    "half dose",
    "overdose",
    "இரட்டை",
    "கூடுதல்",
    "அளவை மாற்ற",
    "அளவு மாற்ற",
    "இரண்டு மாத்திரை",
    "அதிகமாக",
    "குறைக்க",
    "நிறுத்த",
    "दोगुनी",
    "ज़्यादा",
    "ज्यादा",
    "मात्रा बदल",
    "मात्रा बढ़ा",
    "मात्रा घटा",
    "दो गोली",
    "बंद",
    "छोड़",
    "ओवरडोज़",
)

SIDE_EFFECTS = (
    "side effect",
    "side-effect",
    "reaction",
    "allergic",
    "allergy",
    "rash",
    "nausea",
    "vomit",
    "dizzy",
    "dizziness",
    "பக்கவிளைவு",
    "ஒவ்வாமை",
    "தடிப்பு",
    "வாந்தி",
    "தலைச்சுற்றல்",
    "दुष्प्रभाव",
    "साइड इफेक्ट",
    "एलर्जी",
    "चकत्ते",
    "उल्टी",
    "चक्कर",
)

INTERACTION = (
    "interaction",
    "alcohol",
    "drink",
    "other medicine",
    "other medicines",
    "pregnant",
    "pregnancy",
    "breastfeeding",
    "ஆல்கஹால்",
    "மற்ற மருந்து",
    "கர்ப்ப",
    "பாலூட்ட",
    "शराब",
    "दूसरी दवा",
    "गर्भ",
    "स्तनपान",
)

DIAGNOSIS = (
    "diagnose",
    "diagnosis",
    "what disease",
    "what condition",
    "is it cancer",
    "நோய்",
    "கண்டறி",
    "என்ன நோய்",
    "बीमारी",
    "रोग",
    "निदान",
)

UNCLEAR = (
    "unclear",
    "not clear",
    "needs confirmation",
    "confirm",
    "unverified",
    "not verified",
    "excluded",
    "தெளிவில்லை",
    "உறுதிப்படுத்த",
    "உறுதி",
    "சரிபார்க்க",
    "स्पष्ट नहीं",
    "पुष्टि",
    "असत्यापित",
    "सत्यापित नहीं",
)

AS_NEEDED = (
    "as needed",
    "sos",
    "prn",
    "when required",
    "only if needed",
    "தேவைப்படும்போது",
    "தேவைப்பட்டால்",
    "ज़रूरत",
    "जरूरत",
    "आवश्यकता",
)

REMINDERS = (
    "reminder",
    "reminders",
    "notification",
    "notifications",
    "enrolled",
    "consent",
    "நினைவூட்டல்",
    "அறிவிப்பு",
    "ஒப்புதல்",
    "रिमाइंडर",
    "सूचना",
    "सहमति",
)

CAREGIVER = (
    "caregiver",
    "care giver",
    "emergency contact",
    "பராமரிப்பாளர்",
    "பராமரிப்பு",
    "देखभालकर्ता",
    "देखभाल",
)

LANGUAGE = (
    "language",
    "timezone",
    "time zone",
    "what language",
    "my profile",
    "மொழி",
    "நேர மண்டலம்",
    "भाषा",
    "समय क्षेत्र",
)

SCHEDULE = (
    "schedule",
    "timetable",
    "today",
    "when",
    "what time",
    "when do i",
    "when should i",
    "next dose",
    "dose time",
    "times",
    "அட்டவணை",
    "இன்று",
    "எப்போது",
    "நேரம்",
    "समय-सारणी",
    "अनुसूची",
    "आज",
    "कब",
    "समय",
)

LIST = (
    "what medicines",
    "which medicines",
    "my medicines",
    "list",
    "medicines",
    "medication",
    "prescription",
    "what do i take",
    "மருந்து",
    "மருந்துகள்",
    "பட்டியல்",
    "दवा",
    "दवाइयाँ",
    "दवाएं",
    "सूची",
)

HELP = (
    "help",
    "what can you do",
    "how can you help",
    "capabilities",
    "உதவி",
    "என்ன செய்ய",
    "मदद",
    "क्या कर सकते",
)

GREETING = (
    "hi",
    "hello",
    "hey",
    "vanakkam",
    "namaste",
    "good morning",
    "good evening",
    "வணக்கம்",
    "நமஸ்தே",
    "नमस्ते",
    "नमस्कार",
)

TIME_WORDS = (
    "when",
    "what time",
    "time",
    "schedule",
    "timetable",
    "next dose",
    "dose time",
    "எப்போது",
    "நேரம்",
    "அட்டவணை",
    "कब",
    "समय",
    "अनुसूची",
)


# ---------------------------------------------------------------------------
# Matching helpers
# ---------------------------------------------------------------------------


def _has(text: str, phrases: tuple[str, ...]) -> bool:
    for phrase in phrases:
        candidate = phrase.casefold()
        if candidate.isalpha() and len(candidate) <= 3:
            if re.search(rf"\b{re.escape(candidate)}\b", text):
                return True
        elif candidate in text:
            return True
    return False


def _match_medicine(text: str, context: AgentContext) -> str:
    """Longest stored medicine name (or first word) found in the message."""
    candidates: list[tuple[int, str]] = []
    seen: set[str] = set()
    for item in context.items:
        name = " ".join((item.medicine or "").split())
        key = name.casefold()
        if len(key) < 3 or key in seen:
            continue
        if key in text:
            candidates.append((len(key), name))
            seen.add(key)
            continue
        first = key.split()[0]
        if len(first) >= 4 and first in text:
            candidates.append((len(first), name))
            seen.add(key)
    if not candidates:
        return ""
    candidates.sort(key=lambda pair: pair[0], reverse=True)
    return candidates[0][1]


def detect_intent(message: str, context: AgentContext) -> IntentMatch:
    text = " ".join((message or "").casefold().split())
    medicine = _match_medicine(text, context)

    # Safety-critical questions first, regardless of whether a medicine matched.
    if _has(text, EMERGENCY):
        return IntentMatch("emergency", medicine)
    if _has(text, MISSED):
        return IntentMatch("missed_dose", medicine)
    if _has(text, DOSE_CHANGE):
        return IntentMatch("dose_change", medicine)
    if _has(text, SIDE_EFFECTS):
        return IntentMatch("side_effects", medicine)
    if _has(text, INTERACTION):
        return IntentMatch("interaction", medicine)
    if _has(text, DIAGNOSIS):
        return IntentMatch("diagnosis", medicine)

    if medicine:
        if _has(text, TIME_WORDS):
            return IntentMatch("medicine_time", medicine)
        return IntentMatch("medicine_info", medicine)

    if _has(text, UNCLEAR):
        return IntentMatch("unclear_items")
    if _has(text, AS_NEEDED):
        return IntentMatch("as_needed")
    if _has(text, REMINDERS):
        return IntentMatch("reminders_status")
    if _has(text, CAREGIVER):
        return IntentMatch("caregiver")
    if _has(text, LANGUAGE):
        return IntentMatch("language")
    if _has(text, SCHEDULE):
        return IntentMatch("schedule_today")
    if _has(text, LIST):
        return IntentMatch("list_medicines")
    if _has(text, HELP):
        return IntentMatch("help")
    if _has(text, GREETING):
        return IntentMatch("greeting")
    return IntentMatch("unknown")
