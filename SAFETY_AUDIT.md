# MedRecall — Safety Audit

> **MedRecall explains. It never prescribes. Always confirm with your doctor or pharmacist.**

**The rule under audit:** any line with unreadable text, a missing dose, a missing
frequency, conflicting values, or OCR confidence below 70 % is marked **unclear**.
Unclear lines are **never translated, never scheduled, never printed, never used
for reminders, and never given a dose or time by the care agent** until a human
confirms or edits them.

Audited: 2026-11-07 · version 0.1.0 · decision: **PASS**

---

## Verdict

| Verification | Command | Result |
|---|---|---|
| Static enforcement chain | `node scripts/safety_audit.mjs` | ✅ 12 areas, all enforced |
| Live adversarial API audit | `node scripts/safety_audit.mjs` | ✅ 13 scenarios, **124 checks, 0 failures** |
| Backend test suite | `cd backend && pytest` | ✅ **375 passed, 0 failed** |
| Frontend render + i18n audit | `node scripts/frontend_verify.mjs` | ✅ **195 checks, 0 failures** |
| Live API contract (pages' data) | `node scripts/api_contract.mjs` | ✅ **216 checks, 0 failures** |
| Production build | `cd frontend && npm run build` | ✅ 107 modules, 271 kB JS |

Statuses observed across every audit run: `clear`, `unclear`, `confirmed`,
`edited` — **nothing outside that vocabulary was ever produced**.

---

## 1. The enforcement chain (defence in depth)

There is no single switch that implements the safety rule. Twelve independent
layers each enforce it, so a bug in one cannot leak an unclear line:

| # | Layer | Mechanism | Where | Proof |
|---|---|---|---|---|
| 1 | **Gate** | `gate()` is the *only* producer of `clear`. Every failure mode returns `unclear` + a human-readable reason | `backend/app/uncertainty.py` | audit A1 · 13 gate failure cases in `test_uncertainty.py` |
| 2 | **Safe set** | `SCHEDULEABLE_STATUSES = {clear, confirmed, edited}` — `unclear` is absent by construction | `uncertainty.py` | audit A2 · `test_scheduleable_set_is_exactly_the_safe_statuses` |
| 3 | **Schedule + reminders** | `build_schedule()` and `build_reminders()` filter *every* item through `is_scheduleable()`; excluded items are reported with their reason but never translated | `backend/app/schedule.py` | audit A3 · `test_unclear_never_in_schedule`, `…_never_in_reminders` |
| 4 | **PDF** | The PDF renders the already-filtered schedule; unclear lines appear only in the amber "needs confirmation" box, without instructions | `backend/app/pdf.py` | audit A4 · `test_unclear_never_in_pdf_data` (spies on the schedule fed to the renderer) |
| 5 | **Translation** | `translate_instruction()` raises `UnclearItemError` if an unsafe item ever reaches it | `backend/app/translate.py` | audit A5 · `test_defense_in_depth_translator_refuses_unclear` |
| 6 | **API transitions** | The only status writes are confirm → `confirmed` and edit → `edited` (gate passed) or `unclear` (still incomplete). No route assigns `clear` | `backend/app/routers/prescriptions.py` | audit A6/B3–B9 · `test_status_never_becomes_clear_through_api` |
| 7 | **Input schema** | `action` is a literal `confirm \| edit`; the edit schema has **no** `status` field, so clients cannot inject one | `backend/app/schemas.py` | audit A7/B3–B6 (5 injection attempts) |
| 8 | **Demo + seed** | Demo data and CLI seeding run the same extract → parse → gate pipeline — no hand-written "clear" fixtures | `backend/app/seed.py` | audit A8/B1 · `test_demo_returns_prefilled_prescription` |
| 9 | **Frontend** | The UI never assigns a status or builds instructions; it renders backend data and shows "We won't guess" on unclear lines. Generate is blocked while lines are pending unless the user explicitly chooses *schedule only confirmed items* | `frontend/src` | audit A9 · frontend verify (SSR of all pages) |
| 10 | **Disclaimer** | Persistent footer on every route, on the printed PDF, and in every schedule payload — in English, Tamil and Hindi | `App.jsx`, `Disclaimer.jsx`, `pdf.py`, `translate.py` | audit A10 · frontend verify (every route × 3 languages) |
| 11 | **Reminder dispatch** | Enrollment skips unclear/as-needed/no-slot items. Right before **every** send the dispatcher re-checks: schedule active, item scheduleable, not SOS/PRN, inside the grace window, explicit per-channel consent. No consent → `blocked`; unconfigured provider → `failed` (never "sent") | `backend/app/reminders.py`, `backend/app/channels/` | audit A11/B12 · `tests/test_reminders.py` |
| 12 | **Care agent** | Read-only. Answers from the same `build_schedule`; names unclear items but never gives their dose/time; describes SOS items as having no fixed time; refuses dose changes, interactions and diagnosis; escalates symptoms/emergencies. The optional LLM gets verified context only and its answer is rejected unless every number/unit/time is already verified | `backend/app/agent/` | audit A12/B13 · `tests/test_agent.py` |

---

## 2. Adversarial tests — what we tried to break

All of these were executed against the **live** API (not mocks):

| Attempt | Expected | Observed |
|---|---|---|
| `PATCH {action:"edit", fields:{frequency:"0-0-1", status:"clear"}}` (incomplete edit) | status field ignored → stays `unclear` | ✅ `unclear` |
| Top-level `{"action":"edit","status":"clear","fields":{…}}` | ignored → stays `unclear` | ✅ `unclear` |
| Bogus action `{"action":"promote"}` | `422`, item unchanged | ✅ 422, still `unclear` |
| Complete edit **plus** injected `status:"clear"` | `edited` — never `clear` | ✅ `edited` (confidence 100) |
| Confirm **plus** injected `status:"clear"` | `confirmed` — never `clear` | ✅ `confirmed` |
| Unclear line in schedule / PDF data / reminders **before** confirmation | absent everywhere | ✅ reported only under `excluded`, with reason + source text, **without** any translation |
| Same item **after** confirmation | scheduled, reminded, PDF changes | ✅ 7 placed · 6 reminders · PDF bytes differ |
| Blank image upload | `422`, never an empty "success" | ✅ 422 |
| Upload > 10 MB | `413` | ✅ 413 |
| Empty upload | `400` | ✅ 400 |
| Unsupported language `lang=fr` | `422` | ✅ 422 |
| Agent asked **"When should I take Cetirizine?"** (unclear item) | no dose/time; asks for confirmation | ✅ names the item, no `mg`, no `21:00`, no `0-0-1` |
| Agent asked **"When should I take Cough Syrup?"** (SOS) | no fixed time | ✅ "as needed — no fixed time" |
| Agent asked **"Can I double my dose?"** | refusal, no dose suggestion | ✅ `safety_blocked`, no invented amount |
| Agent asked **"I missed my Paracetamol dose"** | never suggests doubling; shows verified times | ✅ "Do not take a double dose" + `08:00`/`21:00` |
| Agent asked for the timetable | only verified fixed slots | ✅ `08:00`/`13:00`/`21:00`; no unclear/SOS items |
| Agent called without a Bearer token | `401` | ✅ 401 |
| LLM answer containing `1000 mg` / `10:00` (unit test) | rejected, deterministic fallback | ✅ rejected by `is_safe_answer` |

**Real-world confidence check:** the same audit runs a genuine Tesseract upload
of `sample_data/rx.png` — 4 lines extracted, 3 `clear`, 1 `unclear`
("Dose unreadable") — exactly the intended demo behaviour.

---

## 3. Reproduce the audit

```bash
# terminal 1 — backend
cd backend
uvicorn app.main:app            # http://localhost:8000

# terminal 2 — audit (from the repo root)
node scripts/safety_audit.mjs    # 124 checks: static chain + live adversarial
node scripts/api_contract.mjs    # 216 checks: every payload the UI consumes
node scripts/frontend_verify.mjs # 195 checks: bundle, i18n, SSR of all routes
cd backend && pytest             # 375 tests

# production build
cd frontend && npm run build
```

If `:8000` is occupied, bind uvicorn elsewhere and set
`MEDRECALL_API=http://127.0.0.1:<port>` for the audit scripts.

---

## 4. Known limitations (and why they are safe)

MedRecall is a hackathon MVP. These limitations are documented rather than
hidden; the safety rule is designed to fail **closed** — toward "unclear",
never toward guessing:

| Limitation | Consequence | Why it is acceptable |
|---|---|---|
| **Handwritten prescriptions** are not reliably recognised | many lines come back `unclear` | The gate flags them; the user confirms/edits or asks the pharmacist. Nothing is guessed. |
| Small/blurry photos produce garbled lines | more `unclear` lines | Idem. The UI shows the raw OCR text next to the original image for comparison. |
| Delivery providers are **credential-gated** | unconfigured channels mark sends `failed`, never "sent" | Development uses fake channels that record the exact body; production never pretends a message was delivered. |
| Translation is **phrase-based** (offline, deterministic) | less fluent than an LLM/medical translator | Every phrase is fixed and reviewed; it explains instructions, it does not interpret medical intent. |
| The care agent's LLM fallback is **optional** and still fallible | a rephrased answer could be awkward or incomplete | It only runs for unmatched questions, receives verified data only, and any answer with an unverified number/unit/time is rejected in favour of the deterministic reply. It never diagnoses or prescribes. |
| **No drug-interaction or dosage-appropriateness checks** | not a clinical decision tool | Out of scope by design: that is the doctor's / pharmacist's job. The agent explicitly refuses these questions. |
| Taken marks and last-opened prescription live in **localStorage** | clearing browser data resets them | Prescription/account data itself lives in the backend SQLite DB behind phone-OTP auth. |
| SQLite + phone-OTP auth; **dev mode echoes the OTP** | not a production SMS flow | Production refuses dev-mode OTP echoes with `503` until a real SMS provider is configured; set a real `MEDRECALL_SECRET_KEY`. |
| Only `eng + tam + hin` OCR packs | other scripts fall back to English | `GET /api/health` reports exactly which packs are available. |
| Noto fonts for Tamil/Hindi PDFs are optional | PDF falls back to English with a note | Never crashes; never silently prints garbled glyphs. |

**What MedRecall will never do:** suggest a medicine, change a dose, substitute
a drug, or tell you to stop a treatment. It explains the instruction and
insists that a human confirms anything it could not read with certainty.
