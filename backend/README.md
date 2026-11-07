# MedRecall — Backend

FastAPI service that turns prescription images/PDFs into structured, safety-gated
medicine lines, multilingual schedules, reminders and printable PDFs.

**MedRecall explains. It never prescribes. Always confirm with your doctor or pharmacist.**

## Install

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate      macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt
```

Requires **Python 3.11+** (verified on 3.11 → 3.15).

### External dependencies

| Dependency | Needed for | Install |
|---|---|---|
| **Tesseract** | all OCR | Windows: `winget install UB-Mannheim.TesseractOCR` · Linux: `apt install tesseract-ocr` · macOS: `brew install tesseract` |
| **tam/hin language data** | Tamil & Hindi OCR | installer "Modify" → tick Tamil/Hindi, **or** drop `tam.traineddata` + `hin.traineddata` (from [tessdata_fast](https://github.com/tesseract-ocr/tessdata_fast)) in `C:\Program Files\Tesseract-OCR\tessdata\` **or** `%LOCALAPPDATA%\Tesseract-OCR\tessdata\` (auto-detected; copy `eng.traineddata` there too) |
| **Poppler** | PDF uploads | Windows: `winget install oschwartz10612.Poppler` · Linux: `apt install poppler-utils` · macOS: `brew install poppler` |
| **Noto fonts** | Tamil/Hindi PDF | see [`fonts/README.md`](fonts/README.md) — without them the PDF falls back to English (never crashes) |

Nothing installed? `GET /api/health` reports it (`status: degraded` with a reason),
and `POST /api/demo` works with **zero OCR dependencies**.

## Run

```bash
uvicorn app.main:app --reload        # from backend/, serves http://localhost:8000
```

## Tests

```bash
pytest                               # from backend/ (uses a throwaway SQLite DB)
```

`pytest.ini` sets `pythonpath = .` and `testpaths = tests`. Tests never touch your
real database (`MEDRECALL_DB` is overridden to a temp file by `tests/conftest.py`).

## Modules

| Module | Responsibility |
|---|---|
| `ocr.py` | file → `OcrLine(text, confidence 0-100)`; OpenCV preprocessing (grayscale → denoise → adaptive threshold, with grayscale retry); tesseract exe auto-discovery; `eng+tam+hin` → `eng` fallback; PDF via pdf2image |
| `extract.py` | skip headers (clinic/doctor/date/patient/Rx/advice), pick medicine lines; **never silently drops a line containing a dosage form** |
| `parser.py` | `medicine_name / strength / form / frequency / food_timing / duration_days`, each with a 0-1 confidence + source fragment; `ABBREVIATIONS`, `SLOT_MAP`, conflict detection |
| `uncertainty.py` | the gate: `clear | unclear` + human reasons; `SCHEDULEABLE_STATUSES = {clear, confirmed, edited}` |
| `translate.py` | `Translator` ABC + `TemplateTranslator` phrase tables (en/ta/hi); raises `UnclearItemError` on unsafe items; swap in IndicTrans2/API later via `get_translator()` |
| `schedule.py` | `build_schedule()` → `slots / as_needed / excluded`; `build_reminders()` (08:00, 13:00, 18:00, 21:00) |
| `pdf.py` | ReportLab timetable: 4 slots, as-needed, amber excluded box, disclaimer footer; Noto fonts with graceful fallback |
| `models.py / db.py / schemas.py` | SQLAlchemy tables + Pydantic v2 API models |
| `seed.py` | `DEMO_TEXT`, shared prescription builder, CLI seeder |
| `main.py` | app assembly: settings, CORS, middleware, exception handlers, dispatcher lifespan, `init_db()` |
| `core/` | `config.py` (settings/env/uploads), `logging.py`, `middleware.py` (request-ID), `security.py` (JWT/OTP/signed URLs), `deps.py` (`get_current_patient`) |
| `routers/` | `auth.py`, `patients.py`, `prescriptions.py`, `reminders.py`, `system.py`, `serializers.py` |
| `reminders.py` | Phase 3 engine: enrollment, timezone-aware occurrence generation, consent-gated dispatch, background loop + `python -m app.reminders --tick` |
| `channels/` | `ChannelAdapter` interface, `FakeChannel` (dev), credential-gated WhatsApp/SMS/voice adapters |

Migrations live in `alembic/versions/` — baseline `4fe1831b87e1`, Phase 2
`c8b4f272dc02`, Phase 3 `c63b9c2fe09c`. Run `alembic upgrade head` from
`backend/` before starting against an existing database.

## Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `MEDRECALL_DB` | SQLite file path or SQLAlchemy URL (used by tests) | `backend/medrecall.db` |
| `MEDRECALL_ENV` | `development` \| `production` (production disables dev OTP echoes and sets `Secure` cookies) | `development` |
| `MEDRECALL_SECRET_KEY` | JWT/OTP HMAC secret — set a real one in production | random per process (dev) |
| `MEDRECALL_CORS_ORIGINS` | comma-separated allowed origins | localhost dev origins |
| `MEDRECALL_LOG_LEVEL` | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` | `INFO` |
| `MEDRECALL_REMINDER_DISPATCHER` | start the background reminder loop | on (`off` in tests) |
| `MEDRECALL_REMINDER_INTERVAL_SECONDS` | dispatcher tick interval | `30` |
| `MEDRECALL_REMINDER_HORIZON_HOURS` | how far ahead occurrences are generated | `48` |
| `MEDRECALL_REMINDER_GRACE_MINUTES` | late-delivery window; older doses become `missed` | `120` |
| `MEDRECALL_REMINDER_MAX_ATTEMPTS` | failed send attempts before `failed` | `3` |
| `MEDRECALL_CHANNEL_MODE` | `fake` records sends locally (ignored in production) | `fake` |

## Safety rule (enforced, not just documented)

1. The gate (`uncertainty.py`) is the **only** producer of `clear`/`unclear`.
2. Humans produce `confirmed` (PATCH `confirm`) or `edited` (PATCH `edit`,
   re-parsed **and re-gated** — an incomplete edit stays `unclear`).
3. There is **no code path** that turns `unclear` into `clear`.
4. `schedule.build_schedule()`, `schedule.build_reminders()`, `pdf.py` and
   `reminders.py` all filter through `is_scheduleable()`; `translate.py` raises
   `UnclearItemError` if an unsafe item ever slips through (defense in depth).
5. `tests/test_schedule_safety.py` proves an unclear item never reaches the
   schedule, the PDF data, or the reminders.
6. The dispatcher re-checks schedule active + item scheduleable + not as-needed
   + grace window + explicit channel consent immediately before every send.
   No consent → `blocked`; unconfigured provider → `failed` (never “sent”).
   `tests/test_reminders.py` proves each gate, including edit-to-unclear
   cancelling pending occurrences.

## Error responses

All errors are plain JSON: `{"detail": "…"}`

| Status | When |
|---|---|
| 400 | empty file, edit without `fields` |
| 401 | missing/invalid/expired access token |
| 403 | bad, forged or expired signed image URL |
| 404 | unknown prescription/item — also someone else's record (no existence leak) |
| 413 | upload > 10 MB |
| 415 | not JPG/PNG/PDF |
| 422 | OCR failure, no medicine lines found, invalid `lang`/timezone |
| 429 | too many OTP requests for one phone |
