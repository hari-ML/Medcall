"""Deterministic, grounded answers for the care agent (Phase 5).

Every sentence here is composed from :class:`~app.agent.context.AgentContext`,
which in turn comes from stored gate output and the same ``build_schedule``
used by the timetable screen and PDF. This module:

* never invents a dose, time, frequency or diagnosis;
* never prints an unclear item's strength/frequency/timing (only its name and
  the gate's reason);
* refuses dose changes, interaction checks and diagnosis, escalating symptoms
  and emergencies to a human.

An optional LLM may rephrase an ``unknown`` question later, but it receives the
same context and its output is validated by :mod:`app.agent.llm`.
"""

from __future__ import annotations

from .context import AgentContext, ContextItem
from .intents import IntentMatch
from .types import AgentReply, AgentSource

# ---------------------------------------------------------------------------
# Phrase tables (en / ta / hi)
# ---------------------------------------------------------------------------

PHRASES: dict[str, dict[str, str]] = {
    "en": {
        "greeting": "Hello. I can explain your verified medicines, timetable and reminders. I cannot prescribe, change a dose, or diagnose.",
        "help": (
            "I can help with: your medicine list, today's timetable, one medicine's "
            "verified times, items that still need confirmation, as-needed medicines, "
            "reminder status, your language/timezone, and your caregiver contact. "
            "I cannot give medical advice, change doses, check interactions, or diagnose."
        ),
        "list_heading": "Your verified medicines:",
        "no_medicines": "No medicines are stored on your account yet.",
        "needs_confirmation": "needs confirmation — not in the timetable",
        "as_needed_label": "as needed — no fixed time",
        "no_fixed_time": "no fixed time",
        "schedule_heading": "Your verified timetable today:",
        "schedule_empty": "No fixed-time doses are scheduled. As-needed medicines have no fixed time.",
        "medicine_unknown": "I could not find that medicine in your verified prescriptions.",
        "unclear_time": "I cannot give a time for {name} because it still needs confirmation. Please confirm or edit it on the review screen first.",
        "as_needed_time": "{name} is as needed, so it has no fixed time and no reminder.",
        "no_times": "{name} has no fixed slot in your verified timetable.",
        "times_intro": "Verified times for {name}:",
        "info_status": "Status: {status}.",
        "unclear_heading": "These items still need confirmation and are not in the timetable or reminders:",
        "unclear_none": "Every stored item is verified. Nothing is waiting for confirmation.",
        "as_needed_heading": "As-needed medicines (no fixed time, no reminder):",
        "as_needed_none": "You have no as-needed medicines on file.",
        "reminders_heading": "Reminders: {count} active schedule(s).",
        "reminders_channels": "Consented channels: {channels}.",
        "reminders_none": "No channel has consent yet, so nothing can be sent. You can grant consent in Settings.",
        "reminders_rule": "Unclear and as-needed items never get a reminder.",
        "caregiver_heading": "Caregiver: {name} {phone}.",
        "caregiver_none": "No caregiver contact is saved. You can add one in your profile.",
        "language": "Your language is {language} and your timezone is {timezone}. You can change both in your profile.",
        "dose_change": "I cannot change, increase, reduce, or recommend a dose. Please ask your doctor or pharmacist. If you already took too much, contact emergency care now.",
        "missed": "Do not take a double dose to catch up. Follow the instructions your doctor or pharmacist gave you for a missed dose. MedRecall will not invent a catch-up dose or time.",
        "missed_with_times": "Your verified times for {name} are: {times}. Do not take a double dose to catch up; ask your doctor or pharmacist what to do.",
        "side_effects": "I cannot assess symptoms or say whether a medicine caused them. Please contact your doctor or pharmacist. If you have trouble breathing, swelling, fainting, or a severe rash, get emergency care now.",
        "interaction": "I cannot check medicine interactions. Ask your pharmacist or doctor before combining medicines, alcohol, or if you are pregnant or breastfeeding.",
        "diagnosis": "I cannot diagnose or tell you what disease you have. Please ask your doctor.",
        "emergency": "This sounds like an emergency. Call your local emergency number or go to the nearest emergency department now.",
        "unknown": "I can only answer from your verified prescription data. Ask me about your medicine list, timetable, unclear items, reminders, or caregiver contact.",
        "unclear_note": "Note: {name} still needs confirmation, so I cannot give its dose or time.",
        "suggestions": [
            "What medicines do I take?",
            "What is my timetable today?",
            "Which items need confirmation?",
            "When should I take {medicine}?",
            "Are my reminders on?",
            "What can you do?",
        ],
    },
    "ta": {
        "greeting": "வணக்கம். சரிபார்க்கப்பட்ட உங்கள் மருந்துகள், அட்டவணை மற்றும் நினைவூட்டல்களை விளக்க முடியும். மருந்து எழுதவோ, அளவை மாற்றவோ, நோய் கண்டறியவோ முடியாது.",
        "help": (
            "நான் உதவக்கூடியவை: மருந்து பட்டியல், இன்றைய அட்டவணை, ஒரு மருந்தின் "
            "சரிபார்க்கப்பட்ட நேரங்கள், உறுதிப்படுத்த வேண்டியவை, தேவைப்படும்போது "
            "எடுக்கும் மருந்துகள், நினைவூட்டல் நிலை, மொழி/நேர மண்டலம், "
            "பராமரிப்பாளர் தொடர்பு. மருத்துவ ஆலோசனை, அளவு மாற்றம், "
            "மருந்து இடைவினை பரிசோதனை அல்லது நோய் கண்டறிதல் செய்ய முடியாது."
        ),
        "list_heading": "சரிபார்க்கப்பட்ட உங்கள் மருந்துகள்:",
        "no_medicines": "உங்கள் கணக்கில் இன்னும் மருந்துகள் இல்லை.",
        "needs_confirmation": "உறுதிப்படுத்த வேண்டும் — அட்டவணையில் இல்லை",
        "as_needed_label": "தேவைப்படும்போது — நிலையான நேரம் இல்லை",
        "no_fixed_time": "நிலையான நேரம் இல்லை",
        "schedule_heading": "இன்றைய சரிபார்க்கப்பட்ட அட்டவணை:",
        "schedule_empty": "நிலையான நேர மருந்துகள் எதுவும் இல்லை. தேவைப்படும்போது எடுக்கும் மருந்துகளுக்கு நிலையான நேரம் இல்லை.",
        "medicine_unknown": "அந்த மருந்து உங்கள் சரிபார்க்கப்பட்ட மருந்துச் சீட்டுகளில் இல்லை.",
        "unclear_time": "{name} இன்னும் உறுதிப்படுத்தப்பட வேண்டும், எனவே நேரம் சொல்ல முடியாது. முதலில் மறுஆய்வுத் திரையில் உறுதிப்படுத்தவும் அல்லது திருத்தவும்.",
        "as_needed_time": "{name} தேவைப்படும்போது எடுக்க வேண்டியது; நிலையான நேரமும் நினைவூட்டலும் இல்லை.",
        "no_times": "{name} க்கு சரிபார்க்கப்பட்ட அட்டவணையில் நிலையான நேரம் இல்லை.",
        "times_intro": "{name} க்கான சரிபார்க்கப்பட்ட நேரங்கள்:",
        "info_status": "நிலை: {status}.",
        "unclear_heading": "இவை இன்னும் உறுதிப்படுத்தப்பட வேண்டும்; அட்டவணையிலோ நினைவூட்டல்களிலோ இல்லை:",
        "unclear_none": "எல்லா மருந்துகளும் சரிபார்க்கப்பட்டுள்ளன. உறுதிப்படுத்த எதுவும் இல்லை.",
        "as_needed_heading": "தேவைப்படும்போது எடுக்கும் மருந்துகள் (நிலையான நேரம் இல்லை, நினைவூட்டல் இல்லை):",
        "as_needed_none": "தேவைப்படும்போது எடுக்கும் மருந்துகள் எதுவும் இல்லை.",
        "reminders_heading": "நினைவூட்டல்கள்: {count} செயலில் உள்ள அட்டவணை(கள்).",
        "reminders_channels": "ஒப்புதல் அளித்த சேனல்கள்: {channels}.",
        "reminders_none": "எந்த சேனலுக்கும் இன்னும் ஒப்புதல் இல்லை, எனவே எதுவும் அனுப்ப முடியாது. அமைப்புகளில் ஒப்புதல் அளிக்கலாம்.",
        "reminders_rule": "தெளிவில்லாத மற்றும் தேவைப்படும்போது எடுக்கும் மருந்துகளுக்கு நினைவூட்டல் செல்லாது.",
        "caregiver_heading": "பராமரிப்பாளர்: {name} {phone}.",
        "caregiver_none": "பராமரிப்பாளர் தொடர்பு சேமிக்கப்படவில்லை. சுயவிவரத்தில் சேர்க்கலாம்.",
        "language": "உங்கள் மொழி {language}, நேர மண்டலம் {timezone}. இரண்டையும் சுயவிவரத்தில் மாற்றலாம்.",
        "dose_change": "நான் அளவை மாற்றவோ, கூட்டவோ, குறைக்கவோ, பரிந்துரைக்கவோ முடியாது. உங்கள் மருத்துவர் அல்லது மருந்தாளரிடம் கேளுங்கள். அதிகமாக எடுத்திருந்தால் உடனே அவசர சிகிச்சையை அணுகவும்.",
        "missed": "தவறிய அளவை ஈடுகட்ட இரட்டை அளவு எடுக்க வேண்டாம். தவறிய அளவுக்கு உங்கள் மருத்துவர் அல்லது மருந்தாளர் சொன்ன வழிமுறையைப் பின்பற்றுங்கள். MedRecall தானாக ஒரு அளவையோ நேரத்தையோ கற்பனை செய்யாது.",
        "missed_with_times": "{name} க்கான சரிபார்க்கப்பட்ட நேரங்கள்: {times}. ஈடுகட்ட இரட்டை அளவு எடுக்க வேண்டாம்; என்ன செய்வது என்று மருத்துவர் அல்லது மருந்தாளரிடம் கேளுங்கள்.",
        "side_effects": "அறிகுறிகளை என்னால் மதிப்பிட முடியாது; மருந்தால் வந்ததா என்றும் சொல்ல முடியாது. உங்கள் மருத்துவர் அல்லது மருந்தாளரை அணுகுங்கள். மூச்சுத் திணறல், வீக்கம், மயக்கம் அல்லது கடுமையான தடிப்பு இருந்தால் உடனே அவசர சிகிச்சை பெறுங்கள்.",
        "interaction": "மருந்து இடைவினைகளை என்னால் பரிசோதிக்க முடியாது. மருந்துகள், ஆல்கஹால் சேர்ப்பதற்கு முன், அல்லது கர்ப்பம்/பாலூட்டும் நிலையில் மருந்தாளர் அல்லது மருத்துவரிடம் கேளுங்கள்.",
        "diagnosis": "என்னால் நோய் கண்டறிய முடியாது. உங்கள் மருத்துவரிடம் கேளுங்கள்.",
        "emergency": "இது அவசரநிலை போலத் தெரிகிறது. உடனே உங்கள் உள்ளூர் அவசர எண்ணை அழைக்கவும் அல்லது அருகிலுள்ள அவசர சிகிச்சைப் பிரிவுக்குச் செல்லவும்.",
        "unknown": "சரிபார்க்கப்பட்ட மருந்துத் தகவலில் இருந்து மட்டுமே பதிலளிக்க முடியும். மருந்து பட்டியல், அட்டவணை, உறுதிப்படுத்த வேண்டியவை, நினைவூட்டல்கள் அல்லது பராமரிப்பாளர் பற்றிக் கேளுங்கள்.",
        "unclear_note": "குறிப்பு: {name} இன்னும் உறுதிப்படுத்தப்பட வேண்டும், எனவே அதன் அளவையோ நேரத்தையோ சொல்ல முடியாது.",
        "suggestions": [
            "நான் எந்த மருந்துகள் எடுக்க வேண்டும்?",
            "இன்றைய என் அட்டவணை என்ன?",
            "எந்த மருந்துகள் உறுதிப்படுத்த வேண்டும்?",
            "{medicine} எப்போது எடுக்க வேண்டும்?",
            "என் நினைவூட்டல்கள் இயங்குகிறதா?",
            "நீங்கள் என்ன செய்ய முடியும்?",
        ],
    },
    "hi": {
        "greeting": "नमस्ते। मैं आपकी सत्यापित दवाइयाँ, समय-सारणी और रिमाइंडर समझा सकता हूँ। मैं दवा नहीं लिख सकता, मात्रा नहीं बदल सकता और निदान नहीं कर सकता।",
        "help": (
            "मैं इनमें मदद कर सकता हूँ: दवा सूची, आज की समय-सारणी, किसी दवा के "
            "सत्यापित समय, पुष्टि बाकी वाले आइटम, ज़रूरत पड़ने पर ली जाने वाली "
            "दवाएँ, रिमाइंडर स्थिति, भाषा/समय क्षेत्र और देखभालकर्ता संपर्क। "
            "मैं चिकित्सा सलाह, मात्रा परिवर्तन, दवा परस्पर क्रिया जाँच या निदान नहीं कर सकता।"
        ),
        "list_heading": "आपकी सत्यापित दवाइयाँ:",
        "no_medicines": "आपके खाते में अभी कोई दवा नहीं है।",
        "needs_confirmation": "पुष्टि आवश्यक — समय-सारणी में नहीं",
        "as_needed_label": "ज़रूरत पड़ने पर — निश्चित समय नहीं",
        "no_fixed_time": "निश्चित समय नहीं",
        "schedule_heading": "आज की सत्यापित समय-सारणी:",
        "schedule_empty": "कोई निश्चित-समय खुराक निर्धारित नहीं है। ज़रूरत पड़ने पर ली जाने वाली दवाओं का निश्चित समय नहीं होता।",
        "medicine_unknown": "वह दवा आपके सत्यापित पर्चों में नहीं मिली।",
        "unclear_time": "{name} की अभी पुष्टि बाकी है, इसलिए मैं समय नहीं बता सकता। पहले समीक्षा स्क्रीन पर पुष्टि या संपादन करें।",
        "as_needed_time": "{name} ज़रूरत पड़ने पर लेनी है, इसलिए इसका निश्चित समय और रिमाइंडर नहीं है।",
        "no_times": "{name} का सत्यापित समय-सारणी में कोई निश्चित समय नहीं है।",
        "times_intro": "{name} के सत्यापित समय:",
        "info_status": "स्थिति: {status}.",
        "unclear_heading": "इन आइटम की अभी पुष्टि बाकी है और ये समय-सारणी या रिमाइंडर में नहीं हैं:",
        "unclear_none": "सभी दर्ज आइटम सत्यापित हैं। पुष्टि के लिए कुछ बाकी नहीं है।",
        "as_needed_heading": "ज़रूरत पड़ने पर ली जाने वाली दवाएँ (निश्चित समय नहीं, रिमाइंडर नहीं):",
        "as_needed_none": "आपके पास ज़रूरत पड़ने पर ली जाने वाली कोई दवा दर्ज नहीं है।",
        "reminders_heading": "रिमाइंडर: {count} सक्रिय अनुसूची।",
        "reminders_channels": "सहमति वाले चैनल: {channels}.",
        "reminders_none": "किसी चैनल पर अभी सहमति नहीं है, इसलिए कुछ भी नहीं भेजा जा सकता। सेटिंग्स में सहमति दें।",
        "reminders_rule": "अस्पष्ट और ज़रूरत पड़ने पर ली जाने वाली दवाओं का रिमाइंडर कभी नहीं बनता।",
        "caregiver_heading": "देखभालकर्ता: {name} {phone}.",
        "caregiver_none": "कोई देखभालकर्ता संपर्क सहेजा नहीं गया है। आप इसे प्रोफ़ाइल में जोड़ सकते हैं।",
        "language": "आपकी भाषा {language} और समय क्षेत्र {timezone} है। दोनों प्रोफ़ाइल में बदल सकते हैं।",
        "dose_change": "मैं मात्रा बदल, बढ़ा, घटा या सुझा नहीं सकता। कृपया अपने डॉक्टर या फ़ार्मासिस्ट से पूछें। अगर आपने ज़्यादा ले लिया है तो तुरंत आपातकालीन देखभाल लें।",
        "missed": "छूटी खुराक की भरपाई के लिए दोहरी खुराक न लें। छूटी खुराक के लिए अपने डॉक्टर या फ़ार्मासिस्ट के बताए निर्देश मानें। MedRecall अपनी ओर से कोई भरपाई खुराक या समय नहीं बनाएगा।",
        "missed_with_times": "{name} के सत्यापित समय: {times}. भरपाई के लिए दोहरी खुराक न लें; क्या करना है यह डॉक्टर या फ़ार्मासिस्ट से पूछें।",
        "side_effects": "मैं लक्षणों का आकलन या यह नहीं बता सकता कि दवा से हुआ है या नहीं। कृपया अपने डॉक्टर या फ़ार्मासिस्ट से संपर्क करें। साँस लेने में तकलीफ़, सूजन, बेहोशी या गंभीर चकत्ते पर तुरंत आपातकालीन देखभाल लें।",
        "interaction": "मैं दवा परस्पर क्रिया की जाँच नहीं कर सकता। दवाएँ, शराब मिलाने से पहले, या गर्भावस्था/स्तनपान में फ़ार्मासिस्ट या डॉक्टर से पूछें।",
        "diagnosis": "मैं निदान या यह नहीं बता सकता कि आपको कौन-सी बीमारी है। कृपया अपने डॉक्टर से पूछें।",
        "emergency": "यह आपातकाल जैसा लगता है। तुरंत अपने स्थानीय आपातकालीन नंबर पर कॉल करें या निकटतम आपातकालीन विभाग जाएँ।",
        "unknown": "मैं केवल आपके सत्यापित पर्चे के डेटा से उत्तर दे सकता हूँ। दवा सूची, समय-सारणी, पुष्टि बाकी आइटम, रिमाइंडर या देखभालकर्ता संपर्क के बारे में पूछें।",
        "unclear_note": "नोट: {name} की अभी पुष्टि बाकी है, इसलिए मैं इसकी मात्रा या समय नहीं बता सकता।",
        "suggestions": [
            "मैं कौन-सी दवाइयाँ लेता हूँ?",
            "आज की मेरी समय-सारणी क्या है?",
            "किन दवाओं की पुष्टि बाकी है?",
            "{medicine} कब लेनी चाहिए?",
            "मेरे रिमाइंडर चालू हैं?",
            "आप क्या कर सकते हैं?",
        ],
    },
}

#: Human-readable names for item statuses (never invented — stored gate values).
STATUS_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "clear": "verified",
        "confirmed": "confirmed by you",
        "edited": "edited by you",
        "unclear": "needs confirmation",
    },
    "ta": {
        "clear": "சரிபார்க்கப்பட்டது",
        "confirmed": "நீங்கள் உறுதிப்படுத்தியது",
        "edited": "நீங்கள் திருத்தியது",
        "unclear": "உறுதிப்படுத்த வேண்டும்",
    },
    "hi": {
        "clear": "सत्यापित",
        "confirmed": "आपने पुष्टि की",
        "edited": "आपने संपादित किया",
        "unclear": "पुष्टि आवश्यक",
    },
}

CHANNEL_NAMES: dict[str, dict[str, str]] = {
    "en": {"whatsapp": "WhatsApp", "sms": "SMS", "voice": "voice call"},
    "ta": {"whatsapp": "WhatsApp", "sms": "SMS", "voice": "குரல் அழைப்பு"},
    "hi": {"whatsapp": "WhatsApp", "sms": "SMS", "voice": "वॉइस कॉल"},
}


def _p(lang: str) -> dict[str, str]:
    return PHRASES.get(lang, PHRASES["en"])


def _status_label(status: str, lang: str) -> str:
    table = STATUS_LABELS.get(lang, STATUS_LABELS["en"])
    return table.get(status, status)


def _label(item: ContextItem) -> str:
    if not item.scheduleable:
        return item.medicine or "—"
    return " ".join(part for part in (item.medicine, item.strength) if part)


def _source(item: ContextItem) -> AgentSource:
    return AgentSource(
        prescription_id=item.prescription_id,
        item_id=item.item_id,
        medicine=item.medicine,
        status=item.status,
    )


def _sources(items: tuple[ContextItem, ...], limit: int = 20) -> tuple[AgentSource, ...]:
    return tuple(_source(item) for item in items[:limit])


def _find(context: AgentContext, medicine: str) -> ContextItem | None:
    if not medicine:
        return None
    wanted = medicine.casefold()
    for item in context.items:
        if (item.medicine or "").casefold() == wanted:
            return item
    return None


def _slot_name(context: AgentContext, slot: str) -> str:
    names = {
        "en": {"morning": "Morning", "afternoon": "Afternoon", "evening": "Evening", "night": "Night"},
        "ta": {"morning": "காலை", "afternoon": "மதியம்", "evening": "மாலை", "night": "இரவு"},
        "hi": {"morning": "सुबह", "afternoon": "दोपहर", "evening": "शाम", "night": "रात"},
    }
    return names.get(context.lang, names["en"]).get(slot, slot.title())


def _times(context: AgentContext, item: ContextItem) -> list[str]:
    return [f"{_slot_name(context, slot)} {time}" for slot, time in item.times]


def _reply(
    context: AgentContext,
    intent: str,
    text: str,
    *,
    grounded: bool = True,
    escalate: bool = False,
    blocked: bool = False,
    sources: tuple[AgentSource, ...] = (),
) -> AgentReply:
    return AgentReply(
        reply=text,
        lang=context.lang,
        intent=intent,
        grounded=grounded,
        escalate=escalate,
        disclaimer=context.schedule.get("disclaimer", ""),
        safety_blocked=blocked,
        sources=sources,
    )


# ---------------------------------------------------------------------------
# Intent handlers
# ---------------------------------------------------------------------------


def _greeting(context: AgentContext) -> AgentReply:
    return _reply(context, "greeting", _p(context.lang)["greeting"])


def _help(context: AgentContext) -> AgentReply:
    return _reply(context, "help", _p(context.lang)["help"])


def _list_medicines(context: AgentContext) -> AgentReply:
    phrases = _p(context.lang)
    if not context.items:
        return _reply(context, "list_medicines", phrases["no_medicines"])
    lines = [phrases["list_heading"]]
    for item in context.items:
        if not item.scheduleable:
            lines.append(f"- {_label(item)} — {phrases['needs_confirmation']}")
            continue
        detail = item.instruction or phrases["no_fixed_time"]
        if item.as_needed:
            detail = f"{detail} ({phrases['as_needed_label']})"
        lines.append(f"- {_label(item)} — {detail}")
    return _reply(
        context,
        "list_medicines",
        "\n".join(lines),
        sources=_sources(context.items),
    )


def _schedule_today(context: AgentContext) -> AgentReply:
    phrases = _p(context.lang)
    lines: list[str] = []
    for slot in ("morning", "afternoon", "evening", "night"):
        entries = context.schedule.get("slots", {}).get(slot, [])
        if not entries:
            continue
        time = context.schedule.get("slot_times", {}).get(slot, "")
        names = "; ".join(
            f"{entry.get('medicine', '')} — {entry.get('instruction', '')}".strip(" —")
            for entry in entries
        )
        lines.append(f"{_slot_name(context, slot)} {time}: {names}".strip())
    if not lines:
        return _reply(context, "schedule_today", phrases["schedule_empty"])
    return _reply(
        context,
        "schedule_today",
        "\n".join([phrases["schedule_heading"], *lines]),
        sources=_sources(
            tuple(item for item in context.items if item.scheduleable and not item.as_needed)
        ),
    )


def _medicine_time(context: AgentContext, medicine: str) -> AgentReply:
    phrases = _p(context.lang)
    item = _find(context, medicine)
    if item is None:
        return _reply(context, "medicine_time", phrases["medicine_unknown"])
    if not item.scheduleable:
        return _reply(
            context,
            "medicine_time",
            phrases["unclear_time"].format(name=_label(item)),
            sources=(_source(item),),
        )
    if item.as_needed:
        return _reply(
            context,
            "medicine_time",
            phrases["as_needed_time"].format(name=_label(item)),
            sources=(_source(item),),
        )
    times = _times(context, item)
    if not times:
        return _reply(
            context,
            "medicine_time",
            phrases["no_times"].format(name=_label(item)),
            sources=(_source(item),),
        )
    return _reply(
        context,
        "medicine_time",
        "\n".join(
            [
                phrases["times_intro"].format(name=_label(item)),
                *[f"- {time}" for time in times],
            ]
        ),
        sources=(_source(item),),
    )


def _medicine_info(context: AgentContext, medicine: str) -> AgentReply:
    phrases = _p(context.lang)
    item = _find(context, medicine)
    if item is None:
        return _reply(context, "medicine_info", phrases["medicine_unknown"])
    if not item.scheduleable:
        return _reply(
            context,
            "medicine_info",
            phrases["unclear_time"].format(name=_label(item)),
            sources=(_source(item),),
        )
    parts = [_label(item)]
    if item.instruction:
        parts.append(item.instruction)
    if item.as_needed:
        parts.append(phrases["as_needed_label"])
    elif item.times:
        parts.append(", ".join(_times(context, item)))
    parts.append(phrases["info_status"].format(status=_status_label(item.status, context.lang)))
    return _reply(
        context,
        "medicine_info",
        "\n".join(parts),
        sources=(_source(item),),
    )


def _unclear_items(context: AgentContext) -> AgentReply:
    phrases = _p(context.lang)
    unclear = tuple(item for item in context.items if not item.scheduleable)
    if not unclear:
        return _reply(context, "unclear_items", phrases["unclear_none"])
    lines = [phrases["unclear_heading"]]
    for item in unclear:
        reason = f" ({item.reason})" if item.reason else ""
        lines.append(f"- {item.medicine or '—'}{reason}")
    return _reply(
        context,
        "unclear_items",
        "\n".join(lines),
        sources=_sources(unclear),
    )


def _as_needed(context: AgentContext) -> AgentReply:
    phrases = _p(context.lang)
    items = tuple(item for item in context.items if item.scheduleable and item.as_needed)
    if not items:
        return _reply(context, "as_needed", phrases["as_needed_none"])
    lines = [phrases["as_needed_heading"]]
    for item in items:
        detail = item.instruction or phrases["no_fixed_time"]
        lines.append(f"- {_label(item)} — {detail}")
    return _reply(context, "as_needed", "\n".join(lines), sources=_sources(items))


def _reminders_status(context: AgentContext) -> AgentReply:
    phrases = _p(context.lang)
    lines = [phrases["reminders_heading"].format(count=context.active_schedules)]
    if context.consent_channels:
        names = CHANNEL_NAMES.get(context.lang, CHANNEL_NAMES["en"])
        channels = ", ".join(names.get(ch, ch) for ch in context.consent_channels)
        lines.append(phrases["reminders_channels"].format(channels=channels))
    else:
        lines.append(phrases["reminders_none"])
    lines.append(phrases["reminders_rule"])
    return _reply(context, "reminders_status", "\n".join(lines))


def _caregiver(context: AgentContext) -> AgentReply:
    phrases = _p(context.lang)
    if not (context.caregiver_name or context.caregiver_phone):
        return _reply(context, "caregiver", phrases["caregiver_none"])
    name = context.caregiver_name or "—"
    phone = f"({context.caregiver_phone})" if context.caregiver_phone else ""
    return _reply(
        context,
        "caregiver",
        phrases["caregiver_heading"].format(name=name, phone=phone).replace(" .", "."),
    )


def _language(context: AgentContext) -> AgentReply:
    return _reply(
        context,
        "language",
        _p(context.lang)["language"].format(
            language=context.language_name, timezone=context.timezone
        ),
    )


def _dose_change(context: AgentContext) -> AgentReply:
    return _reply(
        context,
        "dose_change",
        _p(context.lang)["dose_change"],
        blocked=True,
    )


def _missed_dose(context: AgentContext, medicine: str) -> AgentReply:
    phrases = _p(context.lang)
    item = _find(context, medicine)
    if item is not None and item.scheduleable and item.times:
        return _reply(
            context,
            "missed_dose",
            phrases["missed_with_times"].format(
                name=_label(item), times=", ".join(_times(context, item))
            ),
            sources=(_source(item),),
        )
    return _reply(context, "missed_dose", phrases["missed"])


def _side_effects(context: AgentContext) -> AgentReply:
    return _reply(
        context,
        "side_effects",
        _p(context.lang)["side_effects"],
        escalate=True,
    )


def _interaction(context: AgentContext) -> AgentReply:
    return _reply(
        context,
        "interaction",
        _p(context.lang)["interaction"],
        blocked=True,
    )


def _diagnosis(context: AgentContext) -> AgentReply:
    return _reply(
        context,
        "diagnosis",
        _p(context.lang)["diagnosis"],
        blocked=True,
    )


def _emergency(context: AgentContext) -> AgentReply:
    return _reply(
        context,
        "emergency",
        _p(context.lang)["emergency"],
        escalate=True,
    )


def _unknown(context: AgentContext) -> AgentReply:
    return _reply(context, "unknown", _p(context.lang)["unknown"], grounded=False)


def respond(match: IntentMatch, context: AgentContext) -> AgentReply:
    """Route one intent to its deterministic, grounded answer."""
    handlers = {
        "greeting": _greeting,
        "help": _help,
        "list_medicines": _list_medicines,
        "schedule_today": _schedule_today,
        "unclear_items": _unclear_items,
        "as_needed": _as_needed,
        "reminders_status": _reminders_status,
        "caregiver": _caregiver,
        "language": _language,
        "dose_change": _dose_change,
        "side_effects": _side_effects,
        "interaction": _interaction,
        "diagnosis": _diagnosis,
        "emergency": _emergency,
        "unknown": _unknown,
    }
    if match.intent == "medicine_time":
        return _medicine_time(context, match.medicine)
    if match.intent == "medicine_info":
        return _medicine_info(context, match.medicine)
    if match.intent == "missed_dose":
        return _missed_dose(context, match.medicine)
    handler = handlers.get(match.intent, _unknown)
    return handler(context)


def suggestions(context: AgentContext) -> list[str]:
    """Starter questions, localized, using a verified medicine name when possible."""
    phrases = _p(context.lang)
    verified = next(
        (item for item in context.items if item.scheduleable and item.medicine),
        None,
    )
    medicine = verified.medicine if verified else ""
    result: list[str] = []
    for template in phrases["suggestions"]:
        if "{medicine}" in template:
            if not medicine:
                continue
            result.append(template.format(medicine=medicine))
        else:
            result.append(template)
    return result
