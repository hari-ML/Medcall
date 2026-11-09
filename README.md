# MedRecall — Medicine Instruction Decoder

> **Making Medicine Instructions Simple, Safe and Understandable.**

MedRecall turns a photo/PDF of a prescription into a **verified, multilingual daily
medicine schedule** (English / தமிழ் Tamil / हिन्दी Hindi) with reminders and a
printable timetable — built for elderly patients, caregivers and regional-language
users who manage many medicines.

> ### ⚠️ The MedRecall promise
> **MedRecall explains. It never prescribes. Always confirm with your doctor or pharmacist.**
> MedRecall **never guesses**: any line with unreadable text, missing dose, missing
> frequency, or low OCR confidence is flagged **"unclear"** and is **not translated,
> not scheduled, not printed and not used for reminders** until a human confirms or
> edits it. It never suggests, changes, or substitutes medicines.

---

## How it works

```
Upload photo/PDF → OCR (Tesseract eng+tam+hin) → line extraction
                 → instruction parsing (dose, frequency, food timing, duration)
                 → UNCERTAINTY GATE (never guesses)
                 → human confirmation / edit for unclear lines
                 → translation (en / ta / hi) → 4-slot timetable
                 → reminders + printable PDF
                 → read-only care agent (grounded answers, no prescribing)
```

| Slot | Default time | Frequency examples |
|---|---|---|
| Morning / காலை / सुबह | 08:00 | `OD`, `1-0-1`, "once a day" |
| Afternoon / மதியம் / दोपहर | 13:00 | `TDS`, `1-1-1` |
| Evening / மாலை / शाम | 18:00 | `QID` |
| Night / இரவு / रात | 21:00 | `BD`, `0-0-1`, `HS` |
| As needed | — | `SOS` / `PRN` → **no fixed slot, no reminder** |

## Tech stack

* **Backend:** Python 3.11+, FastAPI, Uvicorn, Pydantic v2, SQLAlchemy + SQLite,
  pytesseract (Tesseract), pdf2image, Pillow, OpenCV, ReportLab, pytest
* **Frontend:** React 18, Vite, Tailwind CSS, react-router-dom, axios
* **OCR languages:** `eng+tam+hin` (auto-falls back to `eng` if packs are missing)

---

## Project structure

```
medrecall/
├── backend/
│   ├── app/
│   │   ├── main.py          FastAPI assembly (routers, CORS, lifespan)
│   │   ├── core/            settings, logging, request-ID, auth/security, deps
│   │   ├── routers/         auth, patients, prescriptions, reminders, agent, admin, system
│   │   ├── agent/           grounded care agent: context, intents, responder, llm
│   │   ├── ocr.py           image/PDF → text lines + confidence (Tesseract)
│   │   ├── extract.py       OCR lines → candidate medicine lines
│   │   ├── parser.py        dose / frequency / food / duration parsing
│   │   ├── uncertainty.py   THE uncertainty gate (clear | unclear)
│   │   ├── translate.py     phrase-table translation en/ta/hi (pluggable)
│   │   ├── schedule.py      timetable + reminder builder
│   │   ├── pdf.py           ReportLab printable timetable
│   │   ├── models.py db.py schemas.py   database + API schemas
│   │   └── seed.py          demo data + CLI seeder
│   ├── fonts/               NotoSansTamil / NotoSansDevanagari (see fonts/README.md)
│   ├── tests/               pytest suite (390 tests)
│   ├── uploads/             uploaded images (runtime)
│   ├── requirements.txt  pytest.ini
├── frontend/                React + Vite + Tailwind app
│   ├── src/
│   │   ├── pages/           Home, Upload, Review, Language, Timetable
│   │   ├── components/      Header, DoseCard, MedicineLine, WarningCard, Disclaimer, LanguageCard
│   │   ├── i18n.jsx         UI translations en/ta/hi + language context
│   │   ├── api.js reminders.js store.js
│   │   └── main.jsx App.jsx
├── sample_data/             prescription text fixtures + rx.png (real-OCR sample)
├── scripts/                 safety_audit.mjs · api_contract.mjs · frontend_verify.mjs
├── SAFETY_AUDIT.md          the enforced safety rule + audit results
├── DEMO_SCRIPT.md           2-minute hackathon demo script
└── README.md                ← you are here
```

---

## Setup

### 1. Backend

```bash
cd medrecall/backend
python -m venv .venv
# Windows:  .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Tesseract OCR (required for real uploads)

**Windows (fastest):**

```powershell
winget install UB-Mannheim.TesseractOCR
```

**Language data for Tamil + Hindi** (one of these):

* Installer route: run the Tesseract installer again → *Modify* → tick
  **Tamil** and **Hindi** language data.
* Or download `tam.traineddata` and `hin.traineddata` from
  <https://github.com/tesseract-ocr/tessdata_fast> into either:
  * `C:\Program Files\Tesseract-OCR\tessdata\` (needs admin), or
  * `%LOCALAPPDATA%\Tesseract-OCR\tessdata\` — **MedRecall auto-detects this
    per-user folder** (copy `eng.traineddata` there too).

**Linux:**

```bash
sudo apt install tesseract-ocr tesseract-ocr-eng tesseract-ocr-tam tesseract-ocr-hin
```

**macOS:**

```bash
brew install tesseract tesseract-lang
```

No language packs? MedRecall still works with **English OCR** and tells you so in
`GET /api/health`.

### 3. Poppler (only needed for **PDF** uploads)

* Windows: `winget install oschwartz10612.Poppler`
* Linux: `sudo apt install poppler-utils`
* macOS: `brew install poppler`

MedRecall auto-detects Poppler from PATH and the WinGet package folder (Windows);
if you installed it somewhere else, set `POPPLER_PATH` to its `bin` directory and
restart the backend. `GET /api/health` reports whether PDF uploads are ready
(`poppler` field) — image uploads work either way.

### 4. Indic fonts (only needed for Tamil/Hindi **PDF** output)

Follow `backend/fonts/README.md` (two Noto TTFs). Without them the timetable PDF
still prints — in English, with a note.

### 5. Frontend

```bash
cd medrecall/frontend
npm install
```

---

## Run

Terminal 1 — backend (from `backend/`):

```bash
uvicorn app.main:app --reload
```

Terminal 2 — frontend (from `frontend/`):

```bash
npm run dev
```

Open **<http://localhost:5173>**.

The dev server proxies `/api` and `/uploads` to the backend on `:8000`
(see `frontend/vite.config.js`); CORS is also enabled for `http://localhost:5173`.

---

## Quick demo (no OCR needed)

> A timed, judge-ready walkthrough (and fallbacks) is in **[`DEMO_SCRIPT.md`](DEMO_SCRIPT.md)**.

1. On **Home**, click **“Try demo prescription”** (or `POST /api/demo`).
2. **Review** screen: 3 lines are ✅ *clear*, line 3 is ⚠️ *“Dose unreadable”*
   (“We won't guess.”) → **Edit manually** (e.g. `10 mg`) or **Confirm**.
3. **Generate schedule** is disabled-looking until you resolve it (or choose
   *“Schedule only confirmed items”*).
4. **Language**: pick English / தமிழ் / हिन्दी — the schedule, PDF and UI switch.
5. **Timetable**: 4 slot cards, *Mark as taken* (updates the Home progress bar),
   *Print timetable* (PDF), *Enable reminders* (browser notifications while open).

Real upload: click **Scan prescription** and drop a JPG/PNG/PDF of a prescription
(sample text fixtures live in `sample_data/`).

---

## API

Every `/api/*` route except `/api/health` and the two OTP login routes requires
`Authorization: Bearer <access token>` (phone + OTP login; dev mode echoes the
code). Prescriptions are scoped to the caller — someone else's id is a 404.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/auth/otp/request` | request a phone OTP (dev echoes `dev_code`) |
| `POST` | `/api/auth/otp/verify` | verify OTP → access token + refresh cookie |
| `POST` | `/api/auth/refresh` | rotate the refresh token (cookie) |
| `POST` | `/api/auth/logout` | end the session |
| `GET/PATCH` | `/api/patients/me` | own profile (language/timezone/caregiver) |
| `GET/POST` | `/api/patients/me/consent` | per-channel communication consent (default deny) |
| `GET` | `/api/prescriptions` | own prescriptions, newest first |
| `POST` | `/api/prescriptions` | multipart upload (JPG/PNG/PDF, ≤10 MB) → parsed items |
| `GET` | `/api/prescriptions/{id}` | same payload for the review screen |
| `PATCH` | `/api/prescriptions/{id}/items/{item_id}` | `{action:"confirm"\|"edit", fields?}` |
| `POST` | `/api/prescriptions/{id}/schedule?lang=en\|ta\|hi` | 4-slot timetable + `excluded[]` |
| `GET` | `/api/prescriptions/{id}/timetable.pdf?lang=...` | printable PDF |
| `GET` | `/api/prescriptions/{id}/reminders?lang=...` | `[{time, medicine, instruction}]` (display only) |
| `POST/DELETE` | `/api/prescriptions/{id}/reminders/enroll` | start/stop the reminder engine for a prescription |
| `GET` | `/api/reminders/upcoming?days=` | pending occurrences (patient-local times) |
| `POST` | `/api/reminders/run` | one manual generate + dispatch tick |
| `GET` | `/api/reminders/history` | sent / blocked / failed / missed occurrences |
| `POST` | `/api/agent/chat` | grounded answer from the caller's own verified data |
| `GET` | `/api/agent/suggestions?lang=` | localized starter questions |
| `POST` | `/api/admin/login` | admin username + password → admin token (503 if unconfigured) |
| `GET` | `/api/admin/stats` | dashboard counts: patients, items by status, reminders, consent |
| `GET` | `/api/admin/patients?page=&page_size=` | paginated cross-patient list |
| `GET` | `/api/admin/patients/{id}` | one patient + prescriptions + consent |
| `GET` | `/api/admin/prescriptions/{id}` | any prescription (read-only admin view) |
| `GET` | `/api/admin/reminders?status=&limit=` | cross-patient occurrence feed (read-only) |
| `POST` | `/api/demo` | prefilled prescription (3 clear + 1 unclear) |
| `GET` | `/api/health` | Tesseract + language availability |

Item statuses: `clear | unclear | confirmed | edited`.
**Only** `clear/confirmed/edited` reach translation, schedule, PDF and reminders;
SOS/PRN items never get a fixed-time reminder.

Existing databases need the Alembic migrations before the first start:
`cd backend && alembic upgrade head` (Phase 4 head: `a489a7b88ae5`).

Reminder delivery uses fake channels in development (sends are recorded, not
sent). To deliver real WhatsApp/Twilio messages, set the provider variables
from `.env.example`; unconfigured providers never report a reminder as sent.

The **care agent** (`POST /api/agent/chat`) is read-only and answers only from
the same verified timetable as the UI/PDF: it never diagnoses, changes a dose,
checks interactions, or invents a time. Unclear items are named but never given
a dose or time; SOS/PRN items are described as having no fixed time. It is
deterministic by default; an optional OpenAI-compatible LLM may rephrase only
unmatched questions, and any answer containing an unverified number, unit or
time is rejected (`MEDRECALL_AGENT_LLM_*` in `.env.example`).

The **admin dashboard API** (`/api/admin/*`) is a read-only ops console with a
separate credential: username + password from `MEDRECALL_ADMIN_USERNAME` /
`MEDRECALL_ADMIN_PASSWORD` (both empty → login 503 and all admin routes 401,
i.e. disabled by default). Admin tokens are a distinct type (`type=admin`, 8 h)
and never work on patient routes — and patient tokens never work on admin
routes. The admin layer only reads: it cannot confirm, edit, enroll or send
anything (`.env.example` lists the variables).

---

## Tests

```bash
cd backend
pytest            # 390 tests: parser, gate, translation, safety invariants, auth, reminders, providers, agent, admin, API
```

What the suite covers:

* every frequency format (`1-0-1`, `1-1-1`, `OD`, `BD`, `TDS`, `QID`, `HS`, `SOS`…),
  food timing and duration parsing;
* every uncertainty-gate failure case + the 70 % confidence boundary;
* translation output in **all three languages**;
* **the explicit safety test**: an *unclear* item never appears in the schedule,
  the PDF data, or the reminders (`tests/test_schedule_safety.py`);
* confirm/edit flow + full API tests through FastAPI's `TestClient`, including a
  real end-to-end OCR upload;
* patient isolation (other patients' records are 404, never 403);
* the reminder engine: enrollment skips unclear/SOS items, occurrences follow the
  patient's timezone, and nothing is sent without consent or outside the grace
  window (`tests/test_reminders.py`);
* provider adapters with mocked HTTP: exact WhatsApp/Twilio payloads, error
  classification, and retry backoff (`tests/test_channels.py`);
* the care agent: verified-only answers, no dose/time for unclear or SOS items,
  dose-change/diagnosis/interaction refusals, Tamil/Hindi replies, patient
  isolation, and the LLM numeric/time safety filter (`tests/test_agent.py`);
* the admin dashboard: login lockout, token-family isolation both ways,
  pagination, cross-patient views, and a read-only guarantee — admin requests
  never change a row (`tests/test_admin.py`).

## Safety audit

The full audit report — enforcement chain, adversarial attempts, results and
limitations — is in **[`SAFETY_AUDIT.md`](SAFETY_AUDIT.md)**. It is reproducible:

```bash
# with the backend running on :8000, from the repo root
node scripts/safety_audit.mjs      # 149 checks — static enforcement + live adversarial (incl. agent + admin + reminders)
node scripts/api_contract.mjs      # 216 checks — every payload the five pages consume
node scripts/frontend_verify.mjs   # 195 checks — bundle, i18n, SSR of all routes
```

Last run: pytest **390 passed**; audits **149 / 216 / 195 checks, 0 failures**.
The live audit tries to inject `status:"clear"` through five different PATCH
payloads, uploads blank/oversize/empty files, and confirms the unclear demo line
stays out of the schedule, PDF and reminders until it is confirmed — and appears
in all three immediately after.

## Seed the database from sample data

```bash
cd backend
python -m app.seed --demo
python -m app.seed --text ../sample_data/full_prescription.txt
python -m app.seed --list
```

---

## Known limitations

* **Handwritten prescriptions are not supported reliably** — OCR (Tesseract)
  works best on printed text. Expect low confidence → lines are flagged unclear
  for you to confirm, which is by design.
* Small/blurry photos may produce garbled lines; the gate catches them instead of
  guessing, but you may need to edit more lines.
* Browser reminders only fire **while the MedRecall tab is open** (no push server).
* Translation is phrase-based (offline, deterministic) — it explains instructions,
  it is not a medical translation engine.
* The app never validates drug interactions or dosing appropriateness — that is a
  doctor's/pharmacist's job.
* **Single-user local SQLite, no authentication** — this is a hackathon MVP. A real
  deployment would need accounts, encrypted storage and audit logging.
* **"Taken" marks, language choice and the last prescription ID live in
  `localStorage`** — clearing browser data resets them. Prescription records
  themselves stay in the local SQLite database.
* OCR packs are only `eng` + `tam` + `hin`; other scripts fall back to English
  (`GET /api/health` reports exactly which packs are installed).
* Tamil/Hindi PDF fonts are optional — if absent the PDF prints in English with a
  note (never garbled glyphs).

**MedRecall explains. It never prescribes. Always confirm with your doctor or pharmacist.**
