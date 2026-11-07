# AGENTS.md

MedRecall — turns a prescription photo/PDF into a verified, trilingual (en/ta/hi) medicine schedule. Core product rule: **never guess** (see "Safety rule"). It is enforced by tests *and* by regex audits that parse the source — refactors can break the audit even when behavior is correct.

## Layout

- `backend/` — FastAPI + SQLAlchemy/SQLite. Entrypoint `app/main.py` (assembly only). Run every backend command from `backend/`.
  Pipeline: `ocr.py → extract.py → parser.py → uncertainty.py (the gate) → translate.py → schedule.py / pdf.py`.
  Structure (Phase 1/2/3): `app/main.py` wires routers + the dispatcher lifespan; `app/core/` holds `config.py` (settings, env, upload dir), `logging.py`, `middleware.py` (request-ID), `security.py` (JWT/OTP/signed image URLs), `deps.py` (phone normalisation, `get_current_patient`); `app/routers/` holds `auth.py`, `patients.py`, `prescriptions.py`, `reminders.py`, `system.py`, `serializers.py`; `app/reminders.py` is the Phase 3 engine and `app/channels/` the delivery adapters. Migrations in `alembic/` (baseline `4fe1831b87e1`, Phase 2 `c8b4f272dc02`, Phase 3 `c63b9c2fe09c`).
- `frontend/` — React 18 + Vite SPA. 5 routed pages in `src/pages/`, every API call in `src/api.js`, every UI string in `src/i18n.jsx`.
- `scripts/` — three Node verification scripts, run from the **repo root** (Node 18+; they use global `fetch`).
- `sample_data/` — text fixtures + `rx.png` (the PNG is required by `scripts/api_contract.mjs`).
- Docs are accurate against the code: `README.md` (setup, API table, tests), `backend/README.md` (module map, env vars, error codes), `SAFETY_AUDIT.md`, `DEMO_SCRIPT.md`.

There is **no linter, formatter, typechecker, CI, or pre-commit config** in this repo — the verification steps below are the whole story.

## Setup and run

```bash
# backend (Python 3.11+) — from backend/
python -m venv .venv
# Windows: .venv\Scripts\activate   |   macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload            # :8000

# frontend — from frontend/
npm install
npm run dev                              # :5173, proxies /api and /uploads to :8000
```

- The repo-root `.venv` (Python 3.14) is the working environment in this checkout — it has all deps incl. `PyJWT`, `tzdata`, `alembic`. (An older broken artifact pointing at a missing `C:\Python315` was deleted in Phase 0.) System `python` has no deps installed.
- `POST /api/demo` and everything downstream of it work with **zero OCR dependencies** — use the demo path when Tesseract/Poppler are unavailable.
- Env vars: `MEDRECALL_DB` (SQLite path/URL, used by tests), `POPPLER_PATH`, `MEDRECALL_API` (audit-script base URL, default `http://127.0.0.1:8000`), `MEDRECALL_ENV` (`development` default | `production` — production refuses dev-mode OTP echoes with 503 and makes the refresh cookie `Secure`), `MEDRECALL_SECRET_KEY` (JWT/OTP HMAC secret — set a real one in production).
- Reminder env vars (Phase 3): `MEDRECALL_REMINDER_DISPATCHER` (default on; `tests/conftest.py` turns it off), `MEDRECALL_REMINDER_INTERVAL_SECONDS` (30), `MEDRECALL_REMINDER_HORIZON_HOURS` (48), `MEDRECALL_REMINDER_GRACE_MINUTES` (120), `MEDRECALL_REMINDER_MAX_ATTEMPTS` (3), `MEDRECALL_CHANNEL_MODE` (`fake` in development; production ignores `fake` and uses the real adapters).

## Auth (Phase 2)

Every `/api/*` route except `/api/health` and the two `/api/auth` login routes requires a `Bearer` access token. `scripts/` audits and `tests/conftest.py` log in first (dev mode echoes the OTP code).

- **Login** is phone + OTP: `POST /api/auth/otp/request` → `POST /api/auth/otp/verify`. Dev mode returns `dev_code` in the response; production returns 503 until an SMS provider is wired (Phase 4b). No passwords — a deliberate, documented deviation from the original plan.
- **Tokens**: access JWT 15 min (PyJWT, HS256) + rotating refresh JWT 30 d in an httpOnly `SameSite=Strict` cookie `medrecall_refresh` (path `/api/auth`, `Secure` in production). `POST /api/auth/refresh` rotates; replaying a consumed jti revokes the patient's whole token family (theft response). `POST /api/auth/logout` ends the session.
- **Isolation**: every prescription endpoint is scoped to the caller. Someone else's id — or a legacy row with `patient_id NULL` (orphan) — is a plain **404, never 403**, so record existence doesn't leak. `GET /api/prescriptions` lists only the caller's rows, newest first.
- **Images**: the public `StaticFiles` mount for `/uploads` is gone. `image_url` in responses is a signed, 15-minute expiring URL (`?exp=&sig=`, HMAC over `prescription_id:filename:exp`, `core/security.py::sign_image_url`), served by `GET /uploads/{filename}` without a Bearer token so `<img src>` still works. Unsigned/forged/expired → 403; unknown file → 404.
- **New tables**: `patients`, `otp_codes` (HMAC-hashed, 10-min expiry, 5 attempts/code, 5 requests/phone/15 min → 429), `refresh_tokens` (jti registry), `consent_records` (whatsapp/sms/voice — the hard pre-send gate for Phase 3+; default deny).
- **Migration ops for an existing DB** (created by `create_all` before Phase 2): `alembic stamp 4fe1831b87e1` then `alembic upgrade head`. If a Phase-2 server already started against it, its `create_all` pre-created the 4 new tables — stop the server, drop `patients`, `otp_codes`, `refresh_tokens`, `consent_records` (FKs off), then `alembic upgrade head`. Old prescription rows stay NULL orphans (invisible to all accounts).
- **Frontend note**: the React SPA has no login UI yet (lands in Phase 7) — the web UI will 401 against this backend until then. That is accepted per plan; the API + audits are the source of truth.

## Reminders (Phase 3)

`app/reminders.py` materialises the timetable into `reminder_schedules` and dispatches `reminder_occurrences`; `app/channels/` holds the adapters. **Nothing in this layer can create a reminder for an unclear or as-needed item** — eligibility always goes through `is_scheduleable()` and `is_as_needed()`.

- **Enrollment**: `POST /api/prescriptions/{id}/reminders/enroll` creates one schedule per fixed daily slot (`08:00/13:00/18:00/21:00` local) for items in `{clear, confirmed, edited}` that are not SOS/PRN. Unclear/as-needed/no-slot items are returned in `skipped` with a reason. Re-enrolling is idempotent; `DELETE .../enroll` deactivates schedules and cancels pending occurrences (history kept). A confirm/edit after enrollment syncs schedules (`sync_item_schedules`): an edit that re-gates the item to `unclear` deactivates its schedules and cancels pending occurrences; a confirm on an already-enrolled prescription adds the item; a confirm on a never-enrolled prescription creates nothing.
- **Occurrences**: lazily generated up to `HORIZON` (48 h) from local slot times in the patient's IANA timezone, stored as naive UTC (the app-wide convention). Generation is idempotent (`uq_reminder_occurrence_slot`) and capped by `duration_days` (`end_date`).
- **Dispatch**: the dispatcher re-checks before **every** send — (a) schedule active, (b) item still scheduleable and not SOS/PRN, (c) inside the 2 h grace window (older → `missed`, never sent late), (d) explicit per-channel consent. No consent → `blocked` (terminal); unconfigured channel → `failed` (never “sent”). Occurrence statuses: `pending | sent | failed | blocked | missed | cancelled`.
- **Channels**: preference order `whatsapp → sms → voice`. Development defaults to `FakeChannel`, which records the exact body/channel/`fake-*` id on the occurrence row. Real adapters (`whatsapp.py`, `sms.py`, `voice.py`) are credential-gated stubs — until configured, production marks sends `failed`, never pretends delivery. Consent lives in `consent_records` (default deny) via `POST /api/patients/me/consent`.
- **Endpoints**: `POST/DELETE /api/prescriptions/{id}/reminders/enroll`, `GET /api/reminders/upcoming?days=`, `POST /api/reminders/run` (manual tick), `GET /api/reminders/history` — all patient-scoped (someone else's id → 404). A patient language change updates active schedules' `lang`; the message body is rebuilt at dispatch time via `translate.py` (which raises `UnclearItemError` as defense in depth).
- **Lifecycle**: the FastAPI lifespan starts the polling loop (`dispatcher_loop`); `python -m app.reminders --tick` runs one generate+dispatch pass for cron deployments. `tests/conftest.py` sets `MEDRECALL_REMINDER_DISPATCHER=off` so tests drive the engine with fixed clocks. Messages are prefixed `MedRecall:` and contain only stored verified fields — the engine never invents a dose or a time.

## Verification

```bash
# 1. backend tests — from backend/
pytest                                   # 310 tests, ~36s; addopts=-q, testpaths=tests
pytest tests/test_api.py::test_health    # single test (file::node form)

# 2. frontend static check — from repo root, needs `npm install` in frontend/ (esbuild)
node scripts/frontend_verify.mjs         # 195 checks, no backend needed

# 3. live audits — backend must be running
node scripts/safety_audit.mjs            # 88 checks (part A static, part B live incl. B0 login, B12 reminder engine)
node scripts/api_contract.mjs            # 216 checks, uploads sample_data/rx.png through real OCR

# 4. production build — from frontend/
npm run build
```

Order matters only in that 3 needs a running backend; run 1–2 before claiming a change is safe. The audit scripts use a **random phone per run** so the OTP rate limit (5 req/phone/15 min) never trips across repeated runs.

Known failures on this machine (not regressions):

- **Tesseract + Poppler are installed** (Phase 0: Tesseract 5.4.0 with tam/hin packs, Poppler 25.07.0) — the real-OCR pipeline test and the audit's OCR-upload section pass on this machine. On a bare machine (no Tesseract) `tests/test_api.py::test_upload_real_image_runs_full_ocr_pipeline` fails with 422 and `scripts/api_contract.mjs` crashes (TypeError) in its OCR-upload section; install with `winget install UB-Mannheim.TesseractOCR` (see README for Tamil/Hindi packs) for a fully green run.
- **`:8000` may already be occupied** by an unrelated app on this machine, which will silently answer `/api/health`. If so, bind uvicorn to another port, set `MEDRECALL_API`, and remember `frontend/vite.config.js` hardcodes the proxy target `http://localhost:8000`.
- Expected green counts **with Tesseract + Poppler installed and the backend running**: pytest 310 passed, frontend_verify 195/195, safety_audit 88/88, api_contract 216/216. On a bare machine only frontend_verify is fully green.

Tests never touch the real database: `tests/conftest.py` sets `MEDRECALL_DB` to a throwaway temp file *before* the app is imported — don't "clean up" `backend/medrecall.db` as part of testing.

## Safety rule (preserve invariants — tests + audit enforce this)

- Only the gate (`uncertainty.py`) may produce status `clear`/`unclear`. There is **no code path from `unclear` to `clear`**; humans produce `confirmed` (PATCH `confirm`) or `edited` (PATCH `edit`, which is re-parsed **and re-gated** — an incomplete edit stays `unclear`).
- `SCHEDULEABLE_STATUSES = {clear, confirmed, edited}`. `schedule.py`, `pdf.py`, `translate.py` and `reminders.py` all filter through `is_scheduleable()`; `translate.py` raises `UnclearItemError` as defense in depth. Unclear items never reach schedule, PDF, or reminders — `tests/test_schedule_safety.py` proves the first two, `tests/test_reminders.py` the third.
- The audit's **part A greps source text**, so these patterns are load-bearing: `gate(parsed)` in `seed.py`; `item.status = STATUS_CONFIRMED/STATUS_EDITED/STATUS_UNCLEAR` (never `STATUS_CLEAR`) in the API layer (`app/main.py` + `app/routers/*.py`); `EditFields` must contain no `status` field; `is_scheduleable(` ≥3× in `schedule.py`; frontend never assigns `.status` (except `api.js`), never writes literal statuses, never defines `instruction:` outside `i18n.jsx`.
- **Patient-data isolation (Phase 2)**: every prescription route goes through `_get_owned_prescription` — other patients' rows and NULL-`patient_id` orphans are indistinguishable from missing (404, never 403, no existence leak); only the caller's rows appear in `GET /api/prescriptions`; uploads and demo stamp `patient_id`. `tests/test_auth.py` proves it.
- **Reminders (Phase 3)**: enrollment skips unclear/as-needed/no-slot items; the dispatcher re-checks schedule active + `is_scheduleable` + not `is_as_needed` + grace window + explicit channel consent immediately before each send; no consent → `blocked` (terminal), unconfigured provider → `failed` (never “sent”); the body is rebuilt from stored verified fields and `translate.py` raises for unclear items. `tests/test_reminders.py` proves each gate, including edit-to-unclear cancelling pending occurrences.
- Never weaken the gate to make OCR/demo output look better — flag-and-require-human-confirmation is the intended behavior.

## Frontend/i18n gotcha

Every UI string must exist in **all three** tables (`UI.en`, `UI.ta`, `UI.hi` in `src/i18n.jsx`); `frontend_verify.mjs` fails on key-set drift, empty strings, or a `t('key')` with no `UI.en` entry. Adding a translation only to English will fail verification.
