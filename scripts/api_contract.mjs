/**
 * MedRecall — API-contract test.
 *
 * Run with the backend up:  node scripts/api_contract.mjs
 * (MEDRECALL_API=http://host:port overrides the default localhost:8000)
 *
 * Verifies the LIVE backend serves exactly the shapes the five pages consume
 * (SSR cannot exercise useEffect fetch paths).
 *
 * Covers: health, OTP login, demo, GET prescription, schedule (ta),
 * reminders (hi), PDF (en+ta), uploaded image, real multipart PNG upload
 * through OCR, confirm → schedule/reminders change, edit (incomplete stays
 * unclear), error payloads ({detail}) — i.e. every api.js call the UI makes.
 *
 * Phase 2: after the health check the script logs in via phone OTP (dev
 * mode echoes the code) and attaches the Bearer token to every call except
 * the signed /uploads/ image URL, which is deliberately public.
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = fileURLToPath(new URL('..', import.meta.url))
const BASE = process.env.MEDRECALL_API || 'http://127.0.0.1:8000'
const RX_PATH = path.join(ROOT, 'sample_data', 'rx.png')
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

let checks = 0
const failures = []
function check(cond, label) {
  checks += 1
  if (!cond) failures.push(label)
}

let AUTH_HEADERS = {}
async function hit(path, opts = {}) {
  const res = await fetch(BASE + path, {
    ...opts,
    headers: { ...AUTH_HEADERS, ...(opts.headers || {}) },
  })
  let body = null
  try {
    body = await res.json()
  } catch {
    /* non-JSON */
  }
  return { status: res.status, body, headers: res.headers, raw: res }
}
async function jsonBody(path, opts) {
  const result = await hit(path, opts)
  return result
}
function patchItem(prescriptionId, itemId, payload) {
  return jsonBody(`/api/prescriptions/${prescriptionId}/items/${itemId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

// --- wait for backend ------------------------------------------------------
let ready = false
for (let attempt = 0; attempt < 60 && !ready; attempt += 1) {
  try {
    const res = await fetch(`${BASE}/api/health`)
    ready = res.ok
  } catch {
    await sleep(500)
  }
}
if (!ready) {
  console.error('BACKEND DID NOT START')
  process.exit(1)
}
console.log('== backend up: /api/health')

// --- A. health -------------------------------------------------------------
{
  const { status, body } = await hit('/api/health')
  check(status === 200, `health status ${status}`)
  check(['ok', 'degraded'].includes(body?.status), `health.status = ${body?.status}`)
  check(typeof body?.version === 'string' && body.version, 'health.version missing')
}

// --- A2. register + OTP login (every record endpoint is patient-scoped) ----
{
  const phone = '+9198' + Array.from({ length: 7 }, () => Math.floor(Math.random() * 10)).join('')
  const req = await jsonBody('/api/auth/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      phone,
      full_name: 'Contract Patient',
      preferred_lang: 'en',
      preferred_channel: 'whatsapp',
    }),
  })
  check(req.status === 201, `register -> ${req.status}`)
  check(/^\d{6}$/.test(req.body?.dev_code || ''), 'otp dev_code missing (dev mode expected)')
  const ver = await jsonBody('/api/auth/otp/verify', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ phone, code: req.body?.dev_code }),
  })
  check(ver.status === 200 && ver.body?.access_token && ver.body?.patient?.phone === phone,
    `otp verify -> ${ver.status}`)
  check((ver.headers.get('set-cookie') || '').includes('medrecall_refresh='),
    'refresh cookie not set on login')
  AUTH_HEADERS = { Authorization: 'Bearer ' + ver.body.access_token }
}

// --- B. demo prescription (Review page payload) ----------------------------
const ITEM_FIELDS = [
  'id', 'line_number', 'medicine', 'strength', 'form', 'frequency', 'food_timing',
  'duration_days', 'as_needed', 'slots', 'status', 'reason', 'source_text', 'confidence',
]
let demo = null
{
  const { status, body } = await jsonBody('/api/demo', { method: 'POST' })
  check(status === 201, `POST /api/demo -> ${status}`)
  demo = body
  check(Number.isInteger(demo?.id), 'demo.id not an integer')
  check(demo?.items?.length === 4, `demo items = ${demo?.items?.length}`)
  check(typeof demo?.image_url === 'string' && demo.image_url.startsWith('/uploads/'),
    `demo.image_url = ${demo?.image_url}`)
  for (const item of demo.items) {
    for (const field of ITEM_FIELDS) {
      check(field in item, `item ${item.line_number} missing field ${field}`)
    }
    check(['clear', 'unclear', 'confirmed', 'edited'].includes(item.status),
      `item status ${item.status}`)
  }
  const unclear = demo.items.find((i) => i.status === 'unclear')
  check(unclear?.reason === 'Dose unreadable', `unclear reason = ${unclear?.reason}`)
  check(unclear?.strength === null, 'unclear item should have strength null')
}

// --- C. GET prescription (Review reload) -----------------------------------
{
  const { status, body } = await hit(`/api/prescriptions/${demo.id}`)
  check(status === 200, `GET prescription -> ${status}`)
  check(body?.id === demo.id, 'GET returns same id')
  check(body?.items?.length === 4, 'GET items count')
}

// --- D. schedule in Tamil (Timetable page payload) -------------------------
let schedule = null
{
  const { status, body } = await jsonBody(
    `/api/prescriptions/${demo.id}/schedule?lang=ta`, { method: 'POST' })
  check(status === 200, `schedule ta -> ${status}`)
  schedule = body
  for (const key of [
    'title', 'disclaimer', 'as_needed_heading', 'excluded_heading', 'empty_slot_note',
    'slots', 'as_needed', 'excluded', 'slot_times', 'date', 'lang',
  ]) {
    check(key in (schedule || {}), `schedule missing key ${key}`)
  }
  check(schedule.lang === 'ta', `schedule.lang = ${schedule.lang}`)
  check(schedule.title && schedule.disclaimer && schedule.empty_slot_note,
    'schedule texts empty')
  check(/[\u0B80-\u0BFF]/.test(schedule.title), 'title not in Tamil script')
  check(/[\u0B80-\u0BFF]/.test(schedule.disclaimer), 'disclaimer not in Tamil script')

  const slotKeys = Object.keys(schedule.slot_times).sort().join(',')
  check(slotKeys === 'afternoon,evening,morning,night', `slot_times keys = ${slotKeys}`)
  check(schedule.slot_times.morning === '08:00' && schedule.slot_times.night === '21:00',
    'slot default times wrong')

  const placed = [...Object.values(schedule.slots).flat(), ...schedule.as_needed]
  check(placed.length === 6, `placed entries = ${placed.length} (want 5 fixed + 1 as-needed)`)
  for (const entry of placed) {
    check(entry.id != null && entry.medicine && entry.status, 'entry missing id/medicine/status')
    check(typeof entry.instruction === 'string' && entry.instruction.length > 3,
      `entry instruction empty: ${JSON.stringify(entry)}`)
    check(entry.status !== 'unclear', 'UNCLEAR item leaked into slots/as-needed!')
    check(!('reason' in entry) || entry.status !== 'unclear', 'placed entry carries unclear reason')
  }
  check(placed.some((e) => /[\u0B80-\u0BFF]/.test(e.instruction)),
    'no Tamil script in ta instructions')
  for (const slot of ['morning', 'afternoon', 'evening', 'night']) {
    for (const entry of schedule.slots[slot]) {
      check(entry.slot === slot && entry.time === schedule.slot_times[slot],
        `slot entry wrong slot/time: ${JSON.stringify(entry)}`)
    }
  }

  const excluded = schedule.excluded
  check(excluded.length === 1, `excluded = ${excluded.length}`)
  check(excluded[0]?.medicine === 'Cetirizine' && excluded[0]?.reason === 'Dose unreadable',
    'excluded entry wrong')
  check(typeof excluded[0]?.source_text === 'string' && excluded[0].source_text,
    'excluded.source_text missing (Review links it)')
  check(excluded[0]?.line_number != null, 'excluded.line_number missing')
  check(!('instruction' in excluded[0]), 'excluded entry was TRANSLATED (must never be)')
  const placedJson = JSON.stringify({ slots: schedule.slots, as: schedule.as_needed })
  check(!placedJson.includes('Cetirizine'), 'unclear medicine leaked into schedule JSON')
}

// --- E. reminders in Hindi (Home + Timetable reminders) --------------------
{
  const { status, body } = await jsonBody(`/api/prescriptions/${demo.id}/reminders?lang=hi`)
  check(status === 200, `reminders hi -> ${status}`)
  check(Array.isArray(body) && body.length === 5, `reminders = ${body?.length} (want 5)`)
  for (const reminder of body) {
    for (const key of ['time', 'medicine', 'instruction', 'slot', 'id']) {
      check(key in reminder, `reminder missing ${key}`)
    }
    check(/^\d{2}:\d{2}$/.test(reminder.time), `reminder.time = ${reminder.time}`)
    check(['morning', 'afternoon', 'evening', 'night'].includes(reminder.slot),
      `reminder.slot = ${reminder.slot}`)
    check(/[\u0900-\u097F]/.test(reminder.instruction), 'reminder instruction not Hindi')
    check(reminder.medicine !== 'Cetirizine', 'UNCLEAR medicine in reminders!')
    check(reminder.medicine !== 'Cough Syrup', 'SOS medicine got a reminder slot!')
  }
}

// --- F. printable PDFs (en + ta) -------------------------------------------
for (const lang of ['en', 'ta']) {
  const res = await fetch(`${BASE}/api/prescriptions/${demo.id}/timetable.pdf?lang=${lang}`, { headers: AUTH_HEADERS })
  const bytes = new Uint8Array(await res.arrayBuffer())
  check(res.status === 200, `pdf ${lang} -> ${res.status}`)
  check(res.headers.get('content-type') === 'application/pdf', `pdf ${lang} content-type`)
  check(String.fromCharCode(...bytes.slice(0, 5)) === '%PDF-', `pdf ${lang} magic`)
  check(bytes.length > 1000, `pdf ${lang} too small (${bytes.length})`)
}

// --- G. served image -------------------------------------------------------
{
  const res = await fetch(BASE + demo.image_url)
  check(res.status === 200, `image GET -> ${res.status}`)
  check((res.headers.get('content-type') || '').startsWith('image/'), 'image content-type')
}

// --- H. real multipart upload (Upload page path) ---------------------------
{
  if (fs.existsSync(RX_PATH)) {
    const bytes = await fs.promises.readFile(RX_PATH)
    const form = new FormData()
    form.append('file', new Blob([bytes], { type: 'image/png' }), 'rx.png')
    const res = await fetch(`${BASE}/api/prescriptions`, { method: 'POST', body: form, headers: AUTH_HEADERS })
    const body = await res.json().catch(() => null)
    check(res.status === 201, `multipart upload -> ${res.status} ${JSON.stringify(body).slice(0, 200)}`)
    check(Array.isArray(body?.items) && body.items.length >= 3,
      `upload items = ${body?.items?.length} (want >=3)`)
    const statuses = (body?.items || []).map((i) => i.status)
    check(statuses.every((s) => ['clear', 'unclear'].includes(s)),
      `upload statuses = ${statuses}`)
    check(statuses.includes('unclear'), 'OCR upload produced no unclear line (Cetirizine ?? mg)')
    console.log(`   real OCR upload: ${body.items.length} items, statuses=${JSON.stringify(statuses)}`)
  } else {
    check(false, `sample image missing: ${RX_PATH}`)
  }
}

// --- I. confirm flow (the ONLY route from unclear → scheduleable) ----------
{
  const unclear = demo.items.find((i) => i.status === 'unclear')
  const { status, body } = await patchItem(demo.id, unclear.id, { action: 'confirm' })
  check(status === 200, `confirm -> ${status}`)
  check(body?.status === 'confirmed', `after confirm status = ${body?.status}`)
  check(body?.reason === '', 'confirmed item still has a reason')

  const s2 = await jsonBody(`/api/prescriptions/${demo.id}/schedule?lang=en`, { method: 'POST' })
  check(s2.body.excluded.length === 0, 'confirmed item still excluded from schedule')
  const placed2 = [...Object.values(s2.body.slots).flat(), ...s2.body.as_needed]
  check(placed2.some((e) => e.medicine === 'Cetirizine'), 'confirmed item not placed in schedule')
  check(placed2.length === 7, `after confirm placed = ${placed2.length} (want 7)`)

  const r2 = await jsonBody(`/api/prescriptions/${demo.id}/reminders`)
  check(r2.body.length === 6, `after confirm reminders = ${r2.body.length} (want 6)`)
}

// --- J. edit flow (incomplete stays unclear; complete → edited) ------------
{
  const { body: fresh } = await jsonBody('/api/demo', { method: 'POST' })
  const unclear = fresh.items.find((i) => i.status === 'unclear')

  const partial = await patchItem(fresh.id, unclear.id, {
    action: 'edit', fields: { frequency: '0-0-1' },
  })
  check(partial.status === 200, `edit partial -> ${partial.status}`)
  check(partial.body?.status === 'unclear',
    `incomplete edit auto-promoted to ${partial.body?.status} (must stay unclear)`)

  const full = await patchItem(fresh.id, unclear.id, {
    action: 'edit',
    fields: { medicine_name: 'Cetirizine', strength: '10 mg', form: 'tab',
      frequency: '0-0-1', duration_days: 5 },
  })
  check(full.status === 200, `edit full -> ${full.status}`)
  check(full.body?.status === 'edited', `complete edit status = ${full.body?.status}`)
  check(full.body?.confidence === 100, `edited confidence = ${full.body?.confidence}`)
  check(JSON.stringify(full.body?.slots) === '["night"]', `edited slots = ${JSON.stringify(full.body?.slots)}`)
}

// --- K. error payloads the UI turns into messages --------------------------
{
  const notFound = await hit('/api/prescriptions/999999')
  check(notFound.status === 404, `404 -> ${notFound.status}`)
  check(typeof notFound.body?.detail === 'string' && notFound.body.detail,
    '404 detail not a string (frontend errorMessage needs it)')

  const badLang = await jsonBody(`/api/prescriptions/${demo.id}/schedule?lang=fr`,
    { method: 'POST' })
  check(badLang.status === 422, `bad lang -> ${badLang.status}`)
  check(badLang.body?.detail != null, '422 detail missing')

  // wrong file type → 415 with a human-readable {detail}
  const form = new FormData()
  form.append('file', new Blob([Buffer.from('hello')], { type: 'text/plain' }), 'notes.txt')
  const wrongType = await fetch(`${BASE}/api/prescriptions`, { method: 'POST', body: form, headers: AUTH_HEADERS })
  check(wrongType.status === 415, `wrong type -> ${wrongType.status}`)
  const wrongBody = await wrongType.json()
  check(typeof wrongBody?.detail === 'string', '415 detail not a string')
}

// --- verdict ---------------------------------------------------------------
console.log('\n========================================')
if (failures.length === 0) {
  console.log(`API CONTRACT PASSED — ${checks} checks, 0 failures`)
} else {
  console.log(`FAILURES (${failures.length} of ${checks} checks):`)
  failures.forEach((failure) => console.log('  x ' + failure))
  process.exitCode = 1
}
