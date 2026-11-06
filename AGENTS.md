# AGENTS.md

MedRecall — turns a prescription photo/PDF into a verified, trilingual (en/ta/hi) medicine schedule. Core product rule: **never guess** (see "Safety rule"). It is enforced by tests *and* by regex audits that parse the source — refactors can break the audit even when behavior is correct.

## Layout

- `backend/` — FastAPI + SQLAlchemy/SQLite. Entrypoint `app/main.py`. Run every backend command from `backend/`.
  Pipeline: `ocr.py → extract.py → parser.py → uncertainty.py (the gate) → translate.py → schedule.py / pdf.py`.
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

- The repo-root `.venv` present in this checkout is a **broken moved artifact**: its `pyvenv.cfg` points at `C:\Python315\python.exe`, which doesn't exist here, so `.venv\Scripts\python.exe` dies with "did not find executable". Delete it and create a fresh one as above. System `python` (3.14) has no deps installed either.
- `POST /api/demo` and everything downstream of it work with **zero OCR dependencies** — use the demo path when Tesseract/Poppler are unavailable.
- Env vars: `MEDRECALL_DB` (SQLite path/URL, used by tests), `POPPLER_PATH`, `MEDRECALL_API` (audit-script base URL, default `http://127.0.0.1:8000`).

## Verification

```bash
# 1. backend tests — from backend/
pytest                                   # 257 tests, ~5s; addopts=-q, testpaths=tests
pytest tests/test_api.py::test_health    # single test (file::node form)

# 2. frontend static check — from repo root, needs `npm install` in frontend/ (esbuild)
node scripts/frontend_verify.mjs         # 195 checks, no backend needed

# 3. live audits — backend must be running
node scripts/safety_audit.mjs            # 75 checks (part A static, part B live)
node scripts/api_contract.mjs            # 212 checks, uploads sample_data/rx.png through real OCR

# 4. production build — from frontend/
npm run build
```

Order matters only in that 3 needs a running backend; run 1–2 before claiming a change is safe.

Known failures on this machine (not regressions):

- **Tesseract is not installed** → `tests/test_api.py::test_upload_real_image_runs_full_ocr_pipeline` fails with 422, and `scripts/api_contract.mjs` crashes (TypeError, not a clean report) in its OCR-upload section. Install with `winget install UB-Mannheim.TesseractOCR` (see README for Tamil/Hindi packs) for a fully green run.
- **Poppler is not installed** → `tests/test_ocr.py::test_find_poppler_returns_a_real_directory_on_this_machine` skips.
- **`:8000` may already be occupied** by an unrelated app on this machine, which will silently answer `/api/health`. If so, bind uvicorn to another port, set `MEDRECALL_API`, and remember `frontend/vite.config.js` hardcodes the proxy target `http://localhost:8000`.
- Expected green counts **with Tesseract + Poppler installed and the backend running**: pytest 257 passed, frontend_verify 195/195, safety_audit 75/75, api_contract 212/212. On a bare machine only frontend_verify is fully green.

Tests never touch the real database: `tests/conftest.py` sets `MEDRECALL_DB` to a throwaway temp file *before* the app is imported — don't "clean up" `backend/medrecall.db` as part of testing.

## Safety rule (preserve invariants — tests + audit enforce this)

- Only the gate (`uncertainty.py`) may produce status `clear`/`unclear`. There is **no code path from `unclear` to `clear`**; humans produce `confirmed` (PATCH `confirm`) or `edited` (PATCH `edit`, which is re-parsed **and re-gated** — an incomplete edit stays `unclear`).
- `SCHEDULEABLE_STATUSES = {clear, confirmed, edited}`. `schedule.py`, `pdf.py` and `translate.py` all filter through `is_scheduleable()`; `translate.py` raises `UnclearItemError` as defense in depth. Unclear items never reach schedule, PDF, or reminders — `tests/test_schedule_safety.py` proves it.
- The audit's **part A greps source text**, so these patterns are load-bearing: `gate(parsed)` in `seed.py`; `item.status = STATUS_CONFIRMED/STATUS_EDITED/STATUS_UNCLEAR` (never `STATUS_CLEAR`) in `main.py`; `EditFields` must contain no `status` field; `is_scheduleable(` ≥3× in `schedule.py`; frontend never assigns `.status` (except `api.js`), never writes literal statuses, never defines `instruction:` outside `i18n.jsx`.
- Never weaken the gate to make OCR/demo output look better — flag-and-require-human-confirmation is the intended behavior.

## Frontend/i18n gotcha

Every UI string must exist in **all three** tables (`UI.en`, `UI.ta`, `UI.hi` in `src/i18n.jsx`); `frontend_verify.mjs` fails on key-set drift, empty strings, or a `t('key')` with no `UI.en` entry. Adding a translation only to English will fail verification.
