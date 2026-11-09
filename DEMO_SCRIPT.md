# MedRecall — 2-Minute Demo Script

> **MedRecall explains. It never prescribes. Always confirm with your doctor or pharmacist.**

The whole demo is designed around one memorable moment: **the app refusing to
guess**. Everything else (Tamil UI, timetable, PDF) is the payoff.

---

## Before you start (T‑5 minutes)

1. **Backend:** `cd backend && uvicorn app.main:app`
2. **Frontend:** `cd frontend && npm run dev` → open **http://localhost:5173**
3. Browser zoom **110 %**, light theme, one clean tab. Second tab empty (for the PDF).
4. Optional clean slate: DevTools console → `localStorage.clear()` (resets "taken"
   marks and the remembered prescription).
5. Sanity check: Home loads and the footer disclaimer is visible.
6. Have `sample_data/rx.png` open on your desktop **only** if you plan the live
   OCR variant (it adds ~10 s — not recommended inside a strict 2‑minute slot).

> **Fallback:** if anything misbehaves, the demo button path below needs only the
> backend. You can also run `POST /api/demo` with curl and open `/review/{id}`.

---

## The script (2:00)

### 0:00 – 0:15 · Problem + promise
**Say:** *"Elderly patients juggle five or more medicines, written as `1-0-1 PC`
or `TDS`. Misreading one instruction can be dangerous. MedRecall turns a
prescription photo into a simple schedule in English, Tamil or Hindi — and it
has one rule above everything: it never guesses."*

Point at the footer: *"MedRecall explains. It never prescribes. Always confirm
with your doctor or pharmacist."*

### 0:15 – 0:35 · Home → Demo
- Click **⚡ Try demo prescription**.
- **Say:** *"A demo prescription so we don't depend on the venue Wi‑Fi. Three
  lines are clear; one is not."*
- You land on **Review**: original prescription on the left, extracted lines on
  the right, chips show **3 ready · 1 needs confirmation**.

### 0:35 – 1:05 · THE safety moment (slow down here)
- Scroll to **Cetirizine — "Dose unreadable."**
- Read the amber panel aloud: **"We won't guess. Please confirm before it is
  added to your schedule."**
- Show the three actions: **✓ Confirm this line**, **✏️ Edit manually**,
  **💬 Ask pharmacist** (the ready-to-copy message is on screen).
- Click **Edit manually**, type **10 mg**, press **Save**.
- **Say:** *"The status becomes **Edited**, never **Clear** — human input is
  re-parsed and re-gated. And before this moment, the schedule button was
  blocked; even if the UI were bypassed, the backend excludes unclear lines
  from the schedule, the PDF and the reminders. Defence in depth."*
- Counts flip to **4 ready · 0 pending**; **Generate schedule** turns teal.

### 1:05 – 1:20 · Language
- Click **Generate schedule →**.
- On the language screen tap **தமிழ்**.
- **Say:** *"Same data, three languages — the schedule, the PDF and the interface.
  Every card previews a real instruction."*
- Click **See my timetable →**.

### 1:20 – 1:50 · Timetable + PDF
- Four slot cards: **காலை 08:00 · மதியம் 13:00 · மாலை 18:00 · இரவு 21:00**, each
  with the instruction in Tamil that came from the backend translator.
- Point at the **as-needed (SOS)** card: *"No fixed time — so no reminder. We
  don't invent a schedule."*
- Click **✓ Mark as taken** on the morning dose (this feeds the Home progress bar).
- Click **🖨 Print timetable** → the Tamil PDF opens in the second tab. Flash the
  four slots + the disclaimer footer. Close the tab.
- Optional one-liner while clicking **🔔 Enable reminders**: *"The backend reminder
  engine only schedules verified fixed-time items — unclear and SOS never get a
  reminder. Sending is consent-gated: fake channels in dev, real WhatsApp/Twilio
  once credentials are set."*

### 1:50 – 2:00 · Close
- Click **← Back** / Home: the progress bar shows today's doses (e.g. *1 of 5*).
- **Say:** *"One rule holds everywhere: if MedRecall can't read it, it asks —
  it never guesses. That is the difference between a translator and a
  prescription app you can trust."*

---

## Timing card (keep on your phone)

| Time | Step | Click |
|---|---|---|
| 0:00 | Problem + promise | — |
| 0:15 | Demo | ⚡ Try demo prescription |
| 0:35 | Safety moment | ✏️ Edit manually → `10 mg` → Save |
| 1:05 | Language | Generate → தமிழ் → See my timetable |
| 1:20 | Timetable | Mark as taken → 🖨 Print timetable |
| 1:50 | Close | Back to Home (progress bar) |

---

## If a judge asks…

- **"What if OCR is wrong?"** → It's flagged `unclear` with the exact reason and
  the raw text, shown beside the original image. The user confirms or edits;
  nothing unclear reaches the schedule/PDF/reminders. We test this explicitly
  (`backend/tests/test_schedule_safety.py`, `scripts/safety_audit.mjs`).
- **"Can it prescribe or change doses?"** → No. It only explains what is written.
  No suggestions, no substitutions, no interaction checking — that is the
  doctor's/pharmacist's role, and the disclaimer says so everywhere.
- **"Why not an LLM translation?"** → The translation layer is a pluggable
  `Translator` interface; the MVP ships a deterministic phrase-table translator
  so medical wording can't drift. Swap in a medical model later without
  touching the safety gate.
- **"Can it answer questions?"** → Yes: `POST /api/agent/chat` is a read-only,
  grounded care agent in English/Tamil/Hindi. It answers only from the verified
  timetable, never gives a dose or time for an unclear item, and refuses dose
  changes, interactions and diagnosis. An optional LLM may rephrase unmatched
  questions, but any unverified number/unit/time is rejected.
- **"Is there an admin view?"** → Yes: `POST /api/admin/login` with
  `MEDRECALL_ADMIN_USERNAME`/`MEDRECALL_ADMIN_PASSWORD` (unset = disabled, fail
  closed) opens a **read-only** ops console — `/api/admin/stats`, paginated
  patients, any prescription, and a cross-patient reminder feed. It cannot
  confirm, edit, enroll or send anything, and its token is rejected on patient
  routes (and vice versa).
- **"What's real vs mocked?"** → Real Tesseract OCR (eng+tam+hin), real FastAPI +
  SQLite, real ReportLab PDFs with Noto fonts, real phone-OTP auth and reminder
  engine. Delivery providers use fake channels by default; real WhatsApp/Twilio
  adapters are credential-gated and never report an unconfigured send as "sent".

## Reset between run-throughs

```js
// DevTools console on localhost:5173
localStorage.clear()
```

Then reload — Home shows a clean state and the next demo starts fresh.
