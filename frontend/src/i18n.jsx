/**
 * MedRecall UI language layer (en / ta / hi).
 *
 * - UI label tables + language context (persisted to localStorage)
 * - slot names, status labels, backend "reason" localization
 * - the live-preview sentences shown on the Language screen
 *
 * The backend translates schedule/PDF content; this file translates the UI.
 */
import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'

export const LANGS = [
  { code: 'en', label: 'English', native: 'English' },
  { code: 'ta', label: 'Tamil', native: 'தமிழ்' },
  { code: 'hi', label: 'Hindi', native: 'हिन्दी' },
]

/** Live preview sentence for the language cards (mirrors backend phrase tables). */
export const LANGUAGE_PREVIEWS = {
  en: '1 tablet after food, three times a day',
  ta: 'உணவுக்குப் பின் 1 மாத்திரை, தினமும் மூன்று முறை',
  hi: 'खाने के बाद 1 गोली, दिन में तीन बार',
}

export const SLOT_NAMES = {
  en: { morning: 'Morning', afternoon: 'Afternoon', evening: 'Evening', night: 'Night' },
  ta: { morning: 'காலை', afternoon: 'மதியம்', evening: 'மாலை', night: 'இரவு' },
  hi: { morning: 'सुबह', afternoon: 'दोपहर', evening: 'शाम', night: 'रात' },
}

export const SLOT_ORDER = ['morning', 'afternoon', 'evening', 'night']

export const DISCLAIMER = {
  en: 'MedRecall explains. It never prescribes. Always confirm with your doctor or pharmacist.',
  ta: 'MedRecall விளக்குகிறது. அது மருந்து எழுதாது. உங்கள் மருத்துவர் அல்லது மருந்தாளரிடம் எப்போதும் உறுதிப்படுத்தவும்.',
  hi: 'MedRecall समझाता है, दवा नहीं लिखता। हमेशा अपने डॉक्टर या फ़ार्मासिस्ट से पुष्टि करें।',
}

export const UI = {
  en: {
    appName: 'MedRecall',
    tagline: 'Making medicine instructions simple, safe and understandable.',
    loading: 'Loading…',
    errorGeneric: 'Something went wrong. Please try again.',
    retry: 'Try again',
    back: 'Back',
    home: 'Home',
    save: 'Save',
    cancel: 'Cancel',
    close: 'Close',
    copy: 'Copy',
    copied: 'Copied!',
    next: 'Next',

    greetingMorning: 'Good morning ☀️',
    greetingAfternoon: 'Good afternoon 🌤️',
    greetingEvening: 'Good evening 🌇',
    greetingNight: 'Good night 🌙',
    nextDose: 'NEXT DOSE',
    noNextDose: 'No dose scheduled right now',
    scanPrescription: 'Scan prescription',
    tryDemo: 'Try demo prescription',
    todayProgress: 'Today: {taken} of {total} doses taken',
    progressEmpty: 'No doses scheduled yet — scan a prescription to begin.',
    allTaken: 'All doses taken — well done! 🎉',
    viewTimetable: 'View my timetable',
    backToReview: 'Review all lines',
    changeLanguage: 'Change language',

    uploadTitle: 'Scan your prescription',
    dropHere: 'Drop an image or PDF here',
    dropFormats: 'JPG · PNG · PDF (max 10 MB)',
    fileTypeInvalid: 'Please choose a JPG, PNG or PDF file.',
    fileTooLarge: 'That file is larger than 10 MB. Try a photo of the prescription instead.',
    dropActive: 'Release to upload',
    takePhoto: 'Take photo',
    chooseFile: 'Choose file',
    uploading: 'Reading your prescription…',
    uploadHint: 'A sharp, well-lit photo of the printed prescription works best.',
    noPrescription: 'No prescription handy?',

    reviewTitle: 'Check the extracted lines',
    reviewSubtitle: 'Every line MedRecall found, next to your original image — so you can verify it.',
    originalImage: 'Original prescription',
    extractedLines: 'Extracted lines',
    line: 'Line {n}',
    statusClear: 'Clear',
    statusUnclear: 'Needs confirmation',
    statusConfirmed: 'Confirmed',
    statusEdited: 'Edited',
    confidence: 'OCR confidence {n}%',
    notAddedYet: 'Not added to timetable yet',
    weWontGuess: "We won't guess. Please confirm before it is added to your schedule.",
    needsConfirmation: 'Needs confirmation',
    askPharmacist: 'Ask pharmacist',
    editManually: 'Edit manually',
    confirmLine: 'Confirm this line',
    confirmHint: 'Tap only if you have checked this line against the prescription.',
    pharmacistMsgLabel: 'Copy this message and send it to your pharmacist:',
    linesReady: '{n} line(s) ready',
    linesPending: '{n} line(s) need confirmation',
    generateSchedule: 'Generate schedule',
    scheduleOnlyConfirmed: 'Schedule only confirmed items',
    resolveFirst: 'Resolve the highlighted lines first — MedRecall never guesses.',
    fieldMedicine: 'Medicine name',
    fieldStrength: 'Dose / strength',
    fieldForm: 'Form',
    fieldFrequency: 'Frequency',
    fieldFood: 'With/without food',
    fieldDuration: 'Duration (days)',
    placeholderMedicine: 'e.g. Cetirizine',
    placeholderStrength: 'e.g. 10 mg',
    placeholderFrequency: 'e.g. 1-0-1, OD, BD, TDS',
    foodBefore: 'Before food',
    foodAfter: 'After food',
    foodWith: 'With food',
    foodEmpty: 'Empty stomach',
    foodUnspecified: 'Not specified',

    langTitle: 'Choose your language',
    langSubtitle: 'Your choice applies to the schedule, the printable timetable and these labels.',
    preview: 'Preview',
    selected: 'Selected',
    choose: 'Choose',
    seeTimetable: 'See my timetable',

    ttTitle: 'My daily timetable',
    ttSubtitle: '{date}',
    asNeeded: 'As needed (no fixed time)',
    excludedWarning: 'Not in this timetable — needs confirmation',
    excludedHint: 'These lines were not added for your safety. Confirm or edit them, then generate again.',
    markAsTaken: 'Mark as taken',
    taken: 'Taken ✓',
    printTimetable: 'Print timetable',
    enableReminders: 'Enable reminders',
    remindersOn: 'Reminders are on 🎉',
    remindersBlocked: 'Notifications are blocked — allow them in your browser settings.',
    remindersUnsupported: 'This browser does not support notifications.',
    noMedicines: 'No medicines scheduled',
    time: 'Time',
    medicine: 'Medicine',
    howToTake: 'How to take',
    excludedCount: '{n} line(s) excluded for your safety',
    openPdf: 'Open printable PDF',
  },

  ta: {
    appName: 'MedRecall',
    tagline: 'மருந்து வழிமுறைகளை எளிமையாக, பாதுகாப்பாக, புரியும்படியாக மாற்றுகிறது.',
    loading: 'ஏற்றுகிறது…',
    errorGeneric: 'ஏதோ ஒரு பிரச்சினை. மீண்டும் முயற்சிக்கவும்.',
    retry: 'மீண்டும் முயற்சி',
    back: 'பின்',
    home: 'முகப்பு',
    save: 'சேமி',
    cancel: 'ரத்து',
    close: 'மூடு',
    copy: 'நகல்',
    copied: 'நகல் எடுக்கப்பட்டது!',
    next: 'அடுத்து',

    greetingMorning: 'காலை வணக்கம் ☀️',
    greetingAfternoon: 'மதிய வணக்கம் 🌤️',
    greetingEvening: 'மாலை வணக்கம் 🌇',
    greetingNight: 'இரவு வணக்கம் 🌙',
    nextDose: 'அடுத்த மருந்து',
    noNextDose: 'இப்போது மருந்து எதுவும் இல்லை',
    scanPrescription: 'மருந்துச் சீட்டை ஸ்கேன் செய்',
    tryDemo: 'டெமோ மருந்துச் சீட்டை முயற்சி',
    todayProgress: 'இன்று: {taken} / {total} மருந்துகள் எடுக்கப்பட்டன',
    progressEmpty: 'இன்னும் மருந்துகள் இல்லை — ஸ்கேன் செய்து தொடங்கவும்.',
    allTaken: 'அனைத்து மருந்துகளும் எடுத்துவிட்டது! 🎉',
    viewTimetable: 'அட்டவணையைக் காண்க',
    backToReview: 'அனைத்து வரிகளையும் சரிபார்க்க',
    changeLanguage: 'மொழியை மாற்று',

    uploadTitle: 'மருந்துச் சீட்டை ஸ்கேன் செய்யவும்',
    dropHere: 'படத்தை அல்லது PDF-ஐ இங்கே விடவும்',
    dropFormats: 'JPG · PNG · PDF (அதிகபட்சம் 10 MB)',
    fileTypeInvalid: 'JPG, PNG அல்லது PDF கோப்பை மட்டும் தேர்வுசெய்யவும்.',
    fileTooLarge: 'இக்கோப்பு 10 MB-க்கு மேல் உள்ளது. மருந்துச் சீட்டின் புகைப்படத்தை முயற்சிக்கவும்.',
    dropActive: 'விடுங்கள் — ஏற்றப்படும்',
    takePhoto: 'புகைப்படம் எடு',
    chooseFile: 'கோப்பைத் தேர்வுசெய்',
    uploading: 'மருந்துச் சீட்டு படிக்கப்படுகிறது…',
    uploadHint: 'தெளிவான, நன்கு வெளிச்சம் உள்ள புகைப்படம் சிறந்தது.',
    noPrescription: 'மருந்துச் சீட்டு இல்லையா?',

    reviewTitle: 'எடுக்கப்பட்ட வரிகளைச் சரிபார்க்கவும்',
    reviewSubtitle: 'MedRecall கண்டறிந்த ஒவ்வொரு வரியும், உங்கள் அசல் படத்துடன் — சரிபார்க்க.',
    originalImage: 'அசல் மருந்துச் சீட்டு',
    extractedLines: 'எடுக்கப்பட்ட வரிகள்',
    line: 'வரி {n}',
    statusClear: 'தெளிவு',
    statusUnclear: 'உறுதிப்படுத்த வேண்டும்',
    statusConfirmed: 'உறுதிப்படுத்தப்பட்டது',
    statusEdited: 'திருத்தப்பட்டது',
    confidence: 'OCR நம்பகத்தன்மை {n}%',
    notAddedYet: 'அட்டவணையில் சேர்க்கப்படவில்லை',
    weWontGuess: 'நாங்கள் யூகிப்பதில்லை. அட்டவணையில் சேர்ப்பதற்கு முன் உறுதிப்படுத்தவும்.',
    needsConfirmation: 'உறுதிப்படுத்த வேண்டும்',
    askPharmacist: 'மருந்தாளரிடம் கேளுங்கள்',
    editManually: 'கைமுறையாகத் திருத்து',
    confirmLine: 'இந்த வரியை உறுதிப்படுத்து',
    confirmHint: 'மருந்துச் சீட்டுடன் ஒப்பிட்டு சரிபார்த்த பின்னரே அழுத்தவும்.',
    pharmacistMsgLabel: 'இந்தச் செய்தியை நகலெடுத்து மருந்தாளருக்கு அனுப்பவும்:',
    linesReady: '{n} வரிகள் தயார்',
    linesPending: '{n} வரிகள் தேவை',
    generateSchedule: 'அட்டவணையை உருவாக்கு',
    scheduleOnlyConfirmed: 'உறுதிப்படுத்தியவை மட்டும்',
    resolveFirst: 'முதலில் சிவப்பு வரிகளைச் சரிப்படுத்தவும் — MedRecall யூகிப்பதில்லை.',
    fieldMedicine: 'மருந்து பெயர்',
    fieldStrength: 'அளவு',
    fieldForm: 'வடிவம்',
    fieldFrequency: 'அதிர்வெண்',
    fieldFood: 'உணவு',
    fieldDuration: 'காலம் (நாட்கள்)',
    placeholderMedicine: 'எ.கா. Cetirizine',
    placeholderStrength: 'எ.கா. 10 mg',
    placeholderFrequency: 'எ.கா. 1-0-1, OD, BD, TDS',
    foodBefore: 'உணவுக்கு முன்',
    foodAfter: 'உணவுக்குப் பின்',
    foodWith: 'உணவுடன்',
    foodEmpty: 'வயிறு காலியாக',
    foodUnspecified: 'குறிப்பிடப்படவில்லை',

    langTitle: 'மொழியைத் தேர்ந்தெடுக்கவும்',
    langSubtitle: 'உங்கள் தேர்வு அட்டவணை, அச்சிடக்கூடிய PDF மற்றும் இந்த வார்த்தைகளுக்கு பொருந்தும்.',
    preview: 'முன்னோட்டம்',
    selected: 'தேர்வு செய்யப்பட்டது',
    choose: 'தேர்வு',
    seeTimetable: 'அட்டவணையைக் காண்க',

    ttTitle: 'என் தினசரி அட்டவணை',
    ttSubtitle: '{date}',
    asNeeded: 'தேவைப்படும்போது (நிலையான நேரம் இல்லை)',
    excludedWarning: 'இந்த அட்டவணையில் இல்லை — உறுதிப்படுத்த வேண்டும்',
    excludedHint: 'உங்கள் பாதுகாப்புக்காக இவை சேர்க்கப்படவில்லை. உறுதிப்படுத்திய பின் மீண்டும் உருவாக்கவும்.',
    markAsTaken: 'எடுத்துவிட்டேன்',
    taken: 'எடுத்தது ✓',
    printTimetable: 'அச்சிடு',
    enableReminders: 'நினைவூட்டல்களை இயக்கு',
    remindersOn: 'நினைவூட்டல்கள் இயக்கத்தில் 🎉',
    remindersBlocked: 'அறிவிப்புகள் தடுக்கப்பட்டுள்ளன — உலாவி அமைப்பில் அனுமதிக்கவும்.',
    remindersUnsupported: 'இந்த உலாவி அறிவிப்புகளை ஆதரிப்பதில்லை.',
    noMedicines: 'மருந்துகள் எதுவும் இல்லை',
    time: 'நேரம்',
    medicine: 'மருந்து',
    howToTake: 'எப்படி எடுக்க வேண்டும்',
    excludedCount: '{n} வரிகள் பாதுகாப்புக்காக விலக்கப்பட்டன',
    openPdf: 'PDF திற',
  },

  hi: {
    appName: 'MedRecall',
    tagline: 'दवा के निर्देशों को सरल, सुरक्षित और समझने योग्य बनाना।',
    loading: 'लोड हो रहा है…',
    errorGeneric: 'कुछ गड़बड़ हुई। फिर से प्रयास करें।',
    retry: 'फिर से प्रयास करें',
    back: 'वापस',
    home: 'होम',
    save: 'सहेजें',
    cancel: 'रद्द करें',
    close: 'बंद करें',
    copy: 'कॉपी',
    copied: 'कॉपी हो गया!',
    next: 'अगला',

    greetingMorning: 'सुप्रभात ☀️',
    greetingAfternoon: 'नमस्कार 🌤️',
    greetingEvening: 'शुभ संध्या 🌇',
    greetingNight: 'शुभ रात्रि 🌙',
    nextDose: 'अगली खुराक',
    noNextDose: 'अभी कोई खुराक निर्धारित नहीं',
    scanPrescription: 'पर्चा स्कैन करें',
    tryDemo: 'डेमो पर्चा आज़माएँ',
    todayProgress: 'आज: {taken} / {total} खुराक ली गईं',
    progressEmpty: 'अभी कोई खुराक नहीं — स्कैन करके शुरू करें।',
    allTaken: 'सारी खुराक ले ली — बहुत बढ़िया! 🎉',
    viewTimetable: 'मेरी समय-सारणी देखें',
    backToReview: 'सभी पंक्तियाँ जाँचें',
    changeLanguage: 'भाषा बदलें',

    uploadTitle: 'अपना पर्चा स्कैन करें',
    dropHere: 'यहाँ छवि या PDF छोड़ें',
    dropFormats: 'JPG · PNG · PDF (अधिकतम 10 MB)',
    fileTypeInvalid: 'कृपया JPG, PNG या PDF फ़ाइल चुनें।',
    fileTooLarge: 'यह फ़ाइल 10 MB से बड़ी है। पर्चे की फ़ोटो आज़माएँ।',
    dropActive: 'छोड़ें — अपलोड होगा',
    takePhoto: 'फ़ोटो लें',
    chooseFile: 'फ़ाइल चुनें',
    uploading: 'पर्चा पढ़ा जा रहा है…',
    uploadHint: 'साफ़, अच्छी रोशनी वाली छवि सबसे अच्छी रहती है।',
    noPrescription: 'पर्चा नहीं है?',

    reviewTitle: 'निकाली गई पंक्तियाँ जाँचें',
    reviewSubtitle: 'MedRecall ने जो पंक्तियाँ मिलीं, आपकी मूल छवि के बगल में — ताकि आप पुष्टि कर सकें।',
    originalImage: 'मूल पर्चा',
    extractedLines: 'निकाली गई पंक्तियाँ',
    line: 'पंक्ति {n}',
    statusClear: 'स्पष्ट',
    statusUnclear: 'पुष्टि आवश्यक',
    statusConfirmed: 'पुष्टि की गई',
    statusEdited: 'संपादित',
    confidence: 'OCR विश्वसनीयता {n}%',
    notAddedYet: 'अभी समय-सारणी में नहीं',
    weWontGuess: 'हम अनुमान नहीं लगाते। समय-सारणी में जोड़ने से पहले पुष्टि करें।',
    needsConfirmation: 'पुष्टि आवश्यक',
    askPharmacist: 'फ़ार्मासिस्ट से पूछें',
    editManually: 'स्वयं संपादित करें',
    confirmLine: 'इस पंक्ति की पुष्टि करें',
    confirmHint: 'पर्चे से मिलान करने के बाद ही दबाएँ।',
    pharmacistMsgLabel: 'यह संदेश कॉपी करके फ़ार्मासिस्ट को भेजें:',
    linesReady: '{n} पंक्तियाँ तैयार',
    linesPending: '{n} पंक्तियों की पुष्टि बाकी',
    generateSchedule: 'समय-सारणी बनाएँ',
    scheduleOnlyConfirmed: 'केवल पुष्टि की गई पंक्तियाँ',
    resolveFirst: 'पहले हा�ाइलाइट पंक्तियाँ सुलझाएँ — MedRecall अनुमान नहीं लगाता।',
    fieldMedicine: 'दवा का नाम',
    fieldStrength: 'खुराक / मात्रा',
    fieldForm: 'रूप',
    fieldFrequency: 'कितनी बार',
    fieldFood: 'खाने के साथ/बिना',
    fieldDuration: 'अवधि (दिन)',
    placeholderMedicine: 'जैसे Cetirizine',
    placeholderStrength: 'जैसे 10 mg',
    placeholderFrequency: 'जैसे 1-0-1, OD, BD, TDS',
    foodBefore: 'खाने से पहले',
    foodAfter: 'खाने के बाद',
    foodWith: 'खाने के साथ',
    foodEmpty: 'खाली पेट',
    foodUnspecified: 'निर्दिष्ट नहीं',

    langTitle: 'अपनी भाषा चुनें',
    langSubtitle: 'आपका चुनाव समय-सारणी, प्रिंट PDF और इन लेबलों पर लागू होगा।',
    preview: 'पूर्वावलोकन',
    selected: 'चुना गया',
    choose: 'चुनें',
    seeTimetable: 'मेरी समय-सारणी देखें',

    ttTitle: 'मेरी दैनिक समय-सारणी',
    ttSubtitle: '{date}',
    asNeeded: 'ज़रूरत पड़ने पर (निश्चित समय नहीं)',
    excludedWarning: 'इस समय-सारणी में नहीं — पुष्टि आवश्यक',
    excludedHint: 'आपकी सुरक्षा के लिए ये नहीं जोड़ी गईं। पुष्टि करके फिर से बनाएँ।',
    markAsTaken: 'ले लिया',
    taken: 'लिया ✓',
    printTimetable: 'प्रिंट करें',
    enableReminders: 'रिमाइंडर चालू करें',
    remindersOn: 'रिमाइंडर चालू हैं 🎉',
    remindersBlocked: 'सूचनाएँ ब्लॉक हैं — ब्राउज़र सेटिंग में अनुमति दें।',
    remindersUnsupported: 'यह ब्राउज़र सूचनाओं का समर्थन नहीं करता।',
    noMedicines: 'कोई दवा निर्धारित नहीं',
    time: 'समय',
    medicine: 'दवा',
    howToTake: 'कैसे लें',
    excludedCount: '{n} पंक्तियाँ सुरक्षा के लिए बाहर रखीं',
    openPdf: 'PDF खोलें',
  },
}

/** Backend gate reasons → localized text (unknown reasons pass through). */
export const REASON_TEXT = {
  en: {
    'Low OCR confidence': 'Low OCR confidence — the photo was hard to read',
    'Dose unreadable': 'Dose unreadable',
    'Dose missing': 'Dose missing',
    'Frequency missing': 'Frequency missing',
    'Frequency ambiguous': 'Frequency ambiguous',
    'Medicine name unclear': 'Medicine name unclear',
    'Conflicting values': 'Conflicting values in the same line',
  },
  ta: {
    'Low OCR confidence': 'படிப்பது கடினம் — புகைப்படம் தெளிவில்லை',
    'Dose unreadable': 'அளவு படிக்க முடியவில்லை',
    'Dose missing': 'அளவு இல்லை',
    'Frequency missing': 'எத்தனை முறை என இல்லை',
    'Frequency ambiguous': 'எத்தனை முறை தெளிவில்லை',
    'Medicine name unclear': 'மருந்து பெயர் தெளிவில்லை',
    'Conflicting values': 'ஒரே வரியில் முரணான தகவல்',
  },
  hi: {
    'Low OCR confidence': 'पठन कठिन — फ़ोटो साफ़ नहीं है',
    'Dose unreadable': 'खुराक पढ़ी नहीं जा सकी',
    'Dose missing': 'खुराक की जानकारी नहीं',
    'Frequency missing': 'कितनी बार — जानकारी नहीं',
    'Frequency ambiguous': 'कितनी बार — स्पष्ट नहीं',
    'Medicine name unclear': 'दवा का नाम स्पष्ट नहीं',
    'Conflicting values': 'एक ही पंक्ति में विरोधाभासी जानकारी',
  },
}

export function localizeReason(lang, reason) {
  if (!reason) return ''
  const table = REASON_TEXT[lang] || REASON_TEXT.en
  const key = Object.keys(table).find((k) => reason.includes(k))
  return key ? reason.replace(key, table[key]) : reason
}

/** Simple {var} interpolation. */
export function interpolate(template, vars = {}) {
  return String(template).replace(/\{(\w+)\}/g, (match, name) =>
    Object.prototype.hasOwnProperty.call(vars, name) ? String(vars[name]) : match,
  )
}

export const LangContext = createContext(null)

export function LangProvider({ children, initialLang }) {
  const [lang, setLangState] = useState(() => {
    // explicit initial override (used by tests / server rendering)
    if (['en', 'ta', 'hi'].includes(initialLang)) return initialLang
    try {
      const stored = localStorage.getItem('medrecall:lang')
      if (['en', 'ta', 'hi'].includes(stored)) return stored
    } catch {
      /* localStorage unavailable */
    }
    return 'en'
  })

  useEffect(() => {
    try {
      localStorage.setItem('medrecall:lang', lang)
    } catch {
      /* ignore */
    }
    document.documentElement.lang = lang
  }, [lang])

  const setLang = useCallback((next) => {
    if (['en', 'ta', 'hi'].includes(next)) setLangState(next)
  }, [])

  const value = useMemo(() => {
    const table = UI[lang] || UI.en
    const t = (key, vars) => interpolate(table[key] != null ? table[key] : (UI.en[key] || key), vars)
    return {
      lang,
      setLang,
      t,
      table,
      disclaimer: DISCLAIMER[lang] || DISCLAIMER.en,
      slotName: (slot) => (SLOT_NAMES[lang] || SLOT_NAMES.en)[slot] || slot,
      localizeReason: (reason) => localizeReason(lang, reason),
      languagePreview: LANGUAGE_PREVIEWS[lang] || LANGUAGE_PREVIEWS.en,
    }
  }, [lang, setLang])

  return <LangContext.Provider value={value}>{children}</LangContext.Provider>
}

export function useI18n() {
  const ctx = useContext(LangContext)
  if (!ctx) throw new Error('useI18n must be used inside <LangProvider>')
  return ctx
}
