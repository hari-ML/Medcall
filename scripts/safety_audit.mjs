/**
 * MedRecall — SAFETY-RULE AUDIT.
 *
 * Run with the backend up:  node scripts/safety_audit.mjs
 * (MEDRECALL_API=http://host:port overrides the default localhost:8000)
 *
 * Part A (static): prove the enforcement chain in the source:
 *   gate is the only producer of "clear" → every schedule/PDF/reminder path
 *   filters through SCHEDULEABLE_STATUSES → translation hard-stops on unclear
 *   → the API's only status transitions are confirm/edit (with re-gating)
 *   → the frontend never assigns a status or fabricates instructions.
 *
 * Part B (live, adversarial): try to get an UNCLEAR line into the schedule,
 * PDF or reminders by abusing the API (status injection in `fields`, bogus
 * actions, extra top-level fields), and verify the demo/upload gates:
 *   blank image → 422, oversize → 413, empty → 400, bad language → 422.
 *
 * Phase 2: Part B first logs in via phone OTP (dev mode echoes the code)
 * and sends the Bearer token on every API call — the audited endpoints are
 * patient-scoped, so an unauthenticated run would prove nothing.
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = fileURLToPath(new URL('..', import.meta.url))
const APP = path.join(ROOT, 'backend/app')
const SRC = path.join(ROOT, 'frontend/src')
const BASE = process.env.MEDRECALL_API || 'http://127.0.0.1:8000'
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

let checks = 0
const failures = []
function check(cond, label) {
  checks += 1
  if (!cond) failures.push(label)
}
function section(name) {
  console.log(`\n== ${name}`)
}
function read(file) {
  return fs.readFileSync(file, 'utf8')
}
function walk(dir) {
  const out = []
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) out.push(...walk(full))
    else out.push(full)
  }
  return out
}

// ===========================================================================
// PART A — static enforcement-chain audit
// ===========================================================================
section('A1. only the uncertainty gate may produce the "clear" status')
// Recursive since Phase 1: routers/ and core/ subpackages count too — a
// clear-assignment hiding in a new subpackage must still be caught.
const backendPy = walk(APP).filter((f) => f.endsWith('.py'))
const clearAssignments = []
for (const file of backendPy) {
  const text = read(file)
  const rel = path.relative(APP, file).split(path.sep).join('/')
  for (const match of text.matchAll(/\bstatus\s*=\s*(STATUS_CLEAR|["']clear["'])/g)) {
    clearAssignments.push(`${rel}: ${match[0]}`)
  }
}
check(clearAssignments.length > 0, 'gate should produce clear somewhere')
const outsideGate = clearAssignments.filter((entry) => !entry.startsWith('uncertainty.py:'))
check(outsideGate.length === 0, `clear produced outside the gate: ${outsideGate.join(' | ')}`)
console.log(`   clear-producing sites: ${clearAssignments.length} (all in uncertainty.py)`)

section('A2. scheduleable set is exactly {clear, confirmed, edited}')
const uncertainty = read(path.join(APP, 'uncertainty.py'))
const setMatch = uncertainty.match(/SCHEDULEABLE_STATUSES\s*=\s*frozenset\(\s*\{([^}]*)\}/)
check(Boolean(setMatch), 'SCHEDULEABLE_STATUSES definition not found')
if (setMatch) {
  const ids = setMatch[1].split(',').map((s) => s.trim()).filter(Boolean).sort()
  check(JSON.stringify(ids) === JSON.stringify(['STATUS_CLEAR', 'STATUS_CONFIRMED', 'STATUS_EDITED']),
    `scheduleable set = ${ids.join(',')}`)
  check(!setMatch[1].includes('STATUS_UNCLEAR'), 'unclear must never be scheduleable')
}

section('A3. schedule + reminders filter through is_scheduleable()')
const scheduleSrc = read(path.join(APP, 'schedule.py'))
check(/from \.uncertainty import SCHEDULEABLE_STATUSES/.test(scheduleSrc), 'schedule must import the safe set')
const guardUses = (scheduleSrc.match(/is_scheduleable\(/g) || []).length
check(guardUses >= 3, `is_scheduleable occurrences in schedule.py = ${guardUses} (want def + 2 uses)`)
check(/def build_schedule/.test(scheduleSrc) && /def build_reminders/.test(scheduleSrc), 'builders missing')

section('A4. the PDF is built from the filtered schedule (excluded only in warning box)')
const pdfSrc = read(path.join(APP, 'pdf.py'))
check(/from \.schedule import .*build_schedule/.test(pdfSrc), 'pdf must use build_schedule')
check(/schedule\["excluded"\]/.test(pdfSrc), 'pdf must render the excluded warning box')

section('A5. translation hard-stops on unclear (defense in depth)')
const translateSrc = read(path.join(APP, 'translate.py'))
check(/SCHEDULEABLE_STATUSES/.test(translateSrc), 'translate must consult the safe set')
check(/raise UnclearItemError/.test(translateSrc), 'translate must raise on unclear')

section('A6. API transitions: confirm→confirmed, edit→edited/unclear, never clear')
// Since Phase 1 the endpoint code lives in app/routers/ (main.py is assembly
// only): positives must hold in the API layer (main.py + routers/*), the
// "never assign clear" negative is enforced across the WHOLE backend tree.
const apiLayerFiles = [path.join(APP, 'main.py'),
  ...walk(path.join(APP, 'routers')).filter((f) => f.endsWith('.py'))]
const apiLayerSrc = apiLayerFiles.map((f) => read(f)).join('\n')
check(/item\.status = STATUS_CONFIRMED/.test(apiLayerSrc), 'confirm transition missing (main.py/routers)')
check(/item\.status = STATUS_EDITED/.test(apiLayerSrc), 'edited transition missing (main.py/routers)')
check(/item\.status = STATUS_UNCLEAR/.test(apiLayerSrc), 'edit failure must stay unclear (main.py/routers)')
const clearInApiLayer = backendPy.filter((f) => /item\.status\s*=\s*STATUS_CLEAR/.test(read(f)))
check(clearInApiLayer.length === 0,
  `API must never assign clear: ${clearInApiLayer.map((f) => path.basename(f)).join(', ')}`)

section('A7. edit schema cannot carry a status field')
const schemasSrc = read(path.join(APP, 'schemas.py'))
check(/action:\s*Literal\["confirm",\s*"edit"\]/.test(schemasSrc), 'action literal missing')
const editBlock = schemasSrc.match(/class EditFields\(BaseModel\):([\s\S]*?)(?=\n\nclass )/)
check(Boolean(editBlock), 'EditFields not found')
if (editBlock) {
  check(!/\bstatus\b/.test(editBlock[1]), 'EditFields must not contain a status field')
  for (const field of ['medicine_name', 'strength', 'form', 'frequency', 'food_timing',
    'duration_days', 'source_text']) {
    check(editBlock[1].includes(field), `EditFields missing ${field}`)
  }
}

section('A8. seed/demo data also passes through the gate')
const seedSrc = read(path.join(APP, 'seed.py'))
check(/gate\(parsed\)/.test(seedSrc), 'seed must gate parsed lines')

section('A9. frontend never assigns statuses or fabricates instructions')
const feFiles = walk(SRC).filter((f) => /\.(jsx?|tsx?)$/.test(f))
const statusAssignments = []
for (const file of feFiles) {
  const text = read(file)
  for (const match of text.matchAll(/[A-Za-z_$][\w$]*\.status\s*=(?!=)/g)) {
    statusAssignments.push(`${path.basename(file)}: ${match[0]}`)
  }
}
const allowedStatusAssignments = statusAssignments.filter((entry) => entry.startsWith('api.js:'))
check(statusAssignments.length === allowedStatusAssignments.length,
  `unexpected status assignment: ${statusAssignments.filter((e) => !e.startsWith('api.js:')).join(' | ')}`)
const literalStatuses = []
for (const file of feFiles) {
  for (const match of read(file).matchAll(/status\s*=\s*["'](?:clear|unclear|confirmed|edited)["']/g)) {
    literalStatuses.push(`${path.basename(file)}: ${match[0]}`)
  }
}
check(literalStatuses.length === 0, `frontend invents statuses: ${literalStatuses.join(' | ')}`)

const fabricated = []
for (const file of feFiles.filter((f) => !f.endsWith('i18n.jsx'))) {
  for (const match of read(file).matchAll(/\binstruction\s*:/g)) {
    fabricated.push(`${path.basename(file)}: ${match[0]}`)
  }
}
check(fabricated.length === 0, `frontend builds instructions itself: ${fabricated.join(' | ')}`)

section('A10. persistent disclaimer + language tables on the frontend')
const appSrc = read(path.join(SRC, 'App.jsx'))
check(/<Disclaimer/.test(appSrc), 'App must mount the Disclaimer')
check(/<LangProvider/.test(appSrc) && /<Routes/.test(appSrc), 'App shell incomplete')
const i18nSrc = read(path.join(SRC, 'i18n.jsx'))
const disclaimerBlock = i18nSrc.match(/export const DISCLAIMER = \{([\s\S]*?)\n\}/)
check(Boolean(disclaimerBlock), 'DISCLAIMER table not found')
if (disclaimerBlock) {
  for (const lang of ['en', 'ta', 'hi']) {
    check(new RegExp(`\\b${lang}:`).test(disclaimerBlock[1]), `DISCLAIMER.${lang} missing`)
  }
}
const medicineLineSrc = read(path.join(SRC, 'components/MedicineLine.jsx'))
check(/item\.status === 'unclear'/.test(medicineLineSrc), 'MedicineLine unclear branch missing')
check(/weWontGuess/.test(medicineLineSrc), 'MedicineLine must state "we won\'t guess"')

// ===========================================================================
// PART B — live adversarial API audit
// ===========================================================================
let AUTH_HEADERS = {}
async function hit(url, opts = {}) {
  const res = await fetch(BASE + url, {
    ...opts,
    headers: { ...AUTH_HEADERS, ...(opts.headers || {}) },
  })
  let body = null
  try {
    body = await res.json()
  } catch {
    /* not JSON */
  }
  return { status: res.status, body }
}
function patchItem(pid, itemId, payload) {
  return hit(`/api/prescriptions/${pid}/items/${itemId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}
const scheduleOf = (pid, lang = 'en') =>
  hit(`/api/prescriptions/${pid}/schedule?lang=${lang}`, { method: 'POST' })
const remindersOf = (pid, lang = 'en') =>
  hit(`/api/prescriptions/${pid}/reminders?lang=${lang}`)
const SAFE = new Set(['clear', 'confirmed', 'edited'])
const seenStatuses = new Set()

let ready = false
for (let attempt = 0; attempt < 40 && !ready; attempt += 1) {
  try {
    ready = (await fetch(`${BASE}/api/health`)).ok
  } catch {
    await sleep(500)
  }
}
if (!ready) {
  console.error('BACKEND NOT RUNNING — start uvicorn first')
  process.exit(1)
}

section('B0. login as a throwaway audit patient (Phase 2 auth)')
{
  const phone = '+9198' + Array.from({ length: 7 }, () => Math.floor(Math.random() * 10)).join('')
  const req = await hit('/api/auth/otp/request', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ phone }),
  })
  check(req.status === 200 && /^\d{6}$/.test(req.body?.dev_code || ''), `otp request -> ${req.status}`)
  const ver = await hit('/api/auth/otp/verify', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ phone, code: req.body?.dev_code }),
  })
  check(ver.status === 200 && ver.body?.access_token, `otp verify -> ${ver.status}`)
  AUTH_HEADERS = { Authorization: 'Bearer ' + (ver.body?.access_token || '') }
}

section('B1. demo data showcases the gate (3 clear + 1 unclear)')
const demo = (await hit('/api/demo', { method: 'POST' })).body
demo.items.forEach((item) => seenStatuses.add(item.status))
const counts = demo.items.reduce((acc, item) => {
  acc[item.status] = (acc[item.status] || 0) + 1
  return acc
}, {})
check(counts.clear === 3 && counts.unclear === 1, `demo counts = ${JSON.stringify(counts)}`)
const unclear = demo.items.find((item) => item.status === 'unclear')
check(unclear?.reason === 'Dose unreadable', `demo unclear reason = ${unclear?.reason}`)

section('B2. baseline: unclear is excluded from schedule, reminders and PDF data')
const base = await scheduleOf(demo.id)
const baseSchedule = base.body
const placedBase = [...Object.values(baseSchedule.slots).flat(), ...baseSchedule.as_needed]
check(baseSchedule.excluded.length === 1 && baseSchedule.excluded[0].id === unclear.id,
  'unclear item must be the only excluded entry')
check(!('instruction' in baseSchedule.excluded[0]), 'excluded entry must never be translated')
check(!JSON.stringify({ s: baseSchedule.slots, a: baseSchedule.as_needed }).includes('Cetirizine'),
  'UNCLEAR medicine leaked into slots/as-needed')
check(placedBase.every((e) => SAFE.has(e.status)), 'unsafe status in schedule')
placedBase.forEach((e) => seenStatuses.add(e.status))

const baseReminders = (await remindersOf(demo.id)).body
check(baseReminders.length === 5, `baseline reminders = ${baseReminders.length}`)
check(baseReminders.every((r) => r.medicine !== 'Cetirizine'), 'UNCLEAR medicine in reminders')
check(baseReminders.every((r) => r.medicine !== 'Cough Syrup'), 'SOS medicine must not be reminded')

const pdf0 = Buffer.from(await (await fetch(
  `${BASE}/api/prescriptions/${demo.id}/timetable.pdf?lang=en`, { headers: AUTH_HEADERS }
)).arrayBuffer())
check(pdf0.subarray(0, 5).toString() === '%PDF-', 'baseline PDF invalid')

section('B3. injection: `fields.status = "clear"` must be ignored')
const inj1 = await patchItem(demo.id, unclear.id, {
  action: 'edit', fields: { frequency: '0-0-1', status: 'clear' },
})
check(inj1.status === 200 ? inj1.body.status === 'unclear' : inj1.status === 422,
  `fields.status injection -> ${inj1.status}/${inj1.body?.status}`)
check(inj1.body?.status !== 'clear', 'fields.status injection produced CLEAR')

const inj2 = await patchItem(demo.id, unclear.id, {
  action: 'edit', status: 'clear', fields: { frequency: '0-0-1' },
})
check(inj2.status === 200 ? inj2.body.status === 'unclear' : inj2.status === 422,
  `top-level status injection -> ${inj2.status}/${inj2.body?.status}`)
check(inj2.body?.status !== 'clear', 'top-level status injection produced CLEAR')

section('B4. bogus actions are rejected; the item stays unclear')
const inj3 = await patchItem(demo.id, unclear.id, { action: 'promote', fields: { status: 'clear' } })
check(inj3.status === 422, `action=promote -> ${inj3.status} (want 422)`)
const still = (await hit(`/api/prescriptions/${demo.id}`)).body.items.find((i) => i.id === unclear.id)
check(still.status === 'unclear', `item after bogus actions = ${still.status}`)

section('B5. complete edit with injected status → "edited", never "clear"')
const inj4 = await patchItem(demo.id, unclear.id, {
  action: 'edit',
  fields: { medicine_name: 'Cetirizine', strength: '10 mg', form: 'tab',
    frequency: '0-0-1', status: 'clear' },
})
check(inj4.status === 200 ? inj4.body.status === 'edited' : inj4.status === 422,
  `complete edit -> ${inj4.status}/${inj4.body?.status}`)
check(inj4.body?.status !== 'clear' && inj4.body?.status !== 'confirmed',
  `injected edit produced ${inj4.body?.status}`)

section('B6. confirm with injected status → "confirmed", never "clear"')
const inj5 = await patchItem(demo.id, unclear.id, { action: 'confirm', status: 'clear' })
check(inj5.status === 200 ? inj5.body.status === 'confirmed' : inj5.status === 422,
  `confirm injection -> ${inj5.status}/${inj5.body?.status}`)
check(inj5.body?.status !== 'clear', 'confirm injection produced CLEAR')

section('B7. after confirmation the item is scheduled — and only then')
const after = (await scheduleOf(demo.id)).body
const placedAfter = [...Object.values(after.slots).flat(), ...after.as_needed]
check(after.excluded.length === 0, 'confirmed item still excluded')
check(placedAfter.some((e) => e.medicine === 'Cetirizine'), 'confirmed item missing from schedule')
check(placedAfter.length === 7, `placed after confirm = ${placedAfter.length} (want 7)`)
check(placedAfter.every((e) => SAFE.has(e.status)), 'unsafe status after confirm')
const afterReminders = (await remindersOf(demo.id)).body
check(afterReminders.length === 6, `reminders after confirm = ${afterReminders.length} (want 6)`)
check(afterReminders.some((r) => r.medicine === 'Cetirizine'), 'confirmed medicine missing from reminders')
const pdf1 = Buffer.from(await (await fetch(
  `${BASE}/api/prescriptions/${demo.id}/timetable.pdf?lang=en`, { headers: AUTH_HEADERS }
)).arrayBuffer())
check(!pdf0.equals(pdf1), 'PDF unchanged after confirmation (exclusion not reflected)')

section('B8. edit via source_text → edited @100, slots derived')
const demo2 = (await hit('/api/demo', { method: 'POST' })).body
demo2.items.forEach((i) => seenStatuses.add(i.status))
const unclear2 = demo2.items.find((i) => i.status === 'unclear')
const full = await patchItem(demo2.id, unclear2.id, {
  action: 'edit', fields: { source_text: 'Tab Cetirizine 10 mg 0-0-1 x 5 days' },
})
check(full.status === 200 && full.body.status === 'edited', `source_text edit -> ${full.status}/${full.body?.status}`)
check(full.body?.confidence === 100, `edited confidence = ${full.body?.confidence}`)
check(JSON.stringify(full.body?.slots) === '["night"]', `edited slots = ${JSON.stringify(full.body?.slots)}`)
seenStatuses.add(full.body?.status)

section('B9. PATCH responses never returned "clear"')
const patchStatuses = [inj1, inj2, inj4, inj5].map((r) => r.body?.status).filter(Boolean)
check(patchStatuses.every((s) => s !== 'clear'), `patch statuses = ${patchStatuses.join(',')}`)
console.log(`   observed PATCH statuses: ${[...new Set(patchStatuses)].join(', ')}`)

section('B10. upload gates: blank image → 422, oversize → 413, empty → 400')
const blank = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==',
  'base64',
)
const blankForm = new FormData()
blankForm.append('file', new Blob([blank], { type: 'image/png' }), 'blank.png')
const blankRes = await fetch(`${BASE}/api/prescriptions`, { method: 'POST', body: blankForm, headers: AUTH_HEADERS })
check(blankRes.status === 422, `blank image -> ${blankRes.status} (want 422, never 201)`)

const bigForm = new FormData()
bigForm.append('file', new Blob([Buffer.alloc(10 * 1024 * 1024 + 1024)], { type: 'image/png' }), 'big.png')
const bigRes = await fetch(`${BASE}/api/prescriptions`, { method: 'POST', body: bigForm, headers: AUTH_HEADERS })
check(bigRes.status === 413, `oversize -> ${bigRes.status} (want 413)`)

const emptyForm = new FormData()
emptyForm.append('file', new Blob([], { type: 'image/png' }), 'empty.png')
const emptyRes = await fetch(`${BASE}/api/prescriptions`, { method: 'POST', body: emptyForm, headers: AUTH_HEADERS })
check(emptyRes.status === 400, `empty file -> ${emptyRes.status} (want 400)`)

section('B11. language gate + status vocabulary')
const badLang = await scheduleOf(demo.id, 'fr')
check(badLang.status === 422, `lang=fr -> ${badLang.status}`)
const hiSchedule = await scheduleOf(demo.id, 'hi')
check(hiSchedule.status === 200 && hiSchedule.body.lang === 'hi', 'lang=hi schedule failed')
for (const item of demo.items) seenStatuses.add(item.status)
check([...seenStatuses].every((s) => ['clear', 'unclear', 'confirmed', 'edited'].includes(s)),
  `unknown status observed: ${[...seenStatuses].join(',')}`)
console.log(`   statuses observed across the audit: ${[...seenStatuses].join(', ')}`)

// ===========================================================================
// verdict
// ===========================================================================
console.log('\n========================================')
if (failures.length === 0) {
  console.log(`SAFETY AUDIT PASSED — ${checks} checks, 0 failures`)
} else {
  console.log(`FAILURES (${failures.length} of ${checks} checks):`)
  failures.forEach((failure) => console.log('  x ' + failure))
  process.exitCode = 1
}
