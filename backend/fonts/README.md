# MedRecall — Indic fonts for the printable PDF timetable

The ReportLab timetable renders Tamil and Hindi text with Noto fonts. Place the
following two files **directly in this `fonts/` folder**:

| File | Used for |
|---|---|
| `NotoSansTamil-Regular.ttf` | Tamil (தமிழ்) instructions in the PDF |
| `NotoSansDevanagari-Regular.ttf` | Hindi (हिन्दी) instructions in the PDF |

## How to download

1. Google Fonts' GitHub repository (canonical source):
   - Noto Sans Tamil: <https://github.com/google/fonts/tree/main/ofl/notosanstamil>
   - Noto Sans Devanagari: <https://github.com/google/fonts/tree/main/ofl/notosansdevanagari>
2. Download the `...-Regular.ttf` file for each family and save it here.

Alternative: <https://fonts.google.com> → search "Noto Sans Tamil" /
"Noto Sans Devanagari" → download the font zip → extract the `Regular` TTFs here.

## If the fonts are missing

The backend handles missing fonts **gracefully**: the PDF falls back to the
built-in Helvetica face and renders the instructions in English with a short
note, so the demo never crashes. English output works without any fonts.
