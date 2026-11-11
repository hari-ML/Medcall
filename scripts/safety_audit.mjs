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

section('A11. delivery channels are dumb pipes + retries are bounded')
const channelFiles = walk(path.join(APP, 'channels')).filter((f) => f.endsWith('.py'))
const medicalImports = []
for (const file of channelFiles) {
  const text = read(file)
  if (/(?:from|import)\s+\.{0,2}(?:parser|translate|schedule|seed|uncertainty)\b/.test(text)) {
    medicalImports.push(path.basename(file))
  }
}
check(medicalImports.length === 0,
  `channel imports the medical pipeline: ${medicalImports.join(', ')}`)
const configSrc = read(path.join(APP, 'core/config.py'))
check(/use_fake_channels[\s\S]{0,200}not self\.is_production/.test(configSrc),
  'fake channels must be impossible in production')
const remindersSrc = read(path.join(APP, 'reminders.py'))
check(/next_attempt_at/.test(remindersSrc) && /ChannelDeliveryError/.test(remindersSrc),
  'dispatcher must back off transient provider failures')
const providerAdapters = ['whatsapp.py', 'sms.py', 'voice.py']
  .filter((name) => /post_provider\(/.test(read(path.join(APP, 'channels', name))))
check(providerAdapters.length === 3,
  `real adapters not using the shared HTTP layer: ${providerAdapters.join(',')}`)
check(/adapter\.send\(patient\.phone, body, lang=/.test(remindersSrc),
  'dispatcher must pass the verified body + language to the adapter')

section('A12. AI care agent is read-only, grounded and cannot prescribe')
const agentDir = path.join(APP, 'agent')
const agentFiles = ['types.py', 'context.py', 'intents.py', 'responder.py', 'llm.py',
  'service.py', '__init__.py'].map((name) => path.join(agentDir, name))
check(agentFiles.every((file) => fs.existsSync(file)),
  `agent package incomplete: ${agentFiles.filter((f) => !fs.existsSync(f)).map((f) => path.basename(f)).join(',')}`)
const forbiddenAgentImports = []
for (const file of agentFiles) {
  const text = read(file)
  if (/(?:from|import)\s+\.{0,2}(?:parser|ocr|seed|pdf|extract)\b/.test(text)) {
    forbiddenAgentImports.push(path.basename(file))
  }
}
check(forbiddenAgentImports.length === 0,
  `agent imports the medical pipeline: ${forbiddenAgentImports.join(', ')}`)
const agentContextSrc = read(path.join(agentDir, 'context.py'))
check(/build_schedule\(/.test(agentContextSrc) && /is_scheduleable\(/.test(agentContextSrc),
  'agent must reuse build_schedule + is_scheduleable')
check(/entry\.pop\("source_text", None\)/.test(agentContextSrc),
  'agent context must strip excluded source_text')
const agentResponderSrc = read(path.join(agentDir, 'responder.py'))
check(!/source_text/.test(agentResponderSrc), 'responder must never read source_text')
const agentLlmSrc = read(path.join(agentDir, 'llm.py'))
check(/def is_safe_answer/.test(agentLlmSrc), 'LLM output must pass is_safe_answer')
check(/Never prescribe, diagnose/.test(agentLlmSrc) && /Never state a dose/.test(agentLlmSrc),
  'LLM system prompt must forbid prescribing/diagnosis/invented doses')
const agentServiceSrc = read(path.join(agentDir, 'service.py'))
check(!/(?:db\.add|db\.commit|db\.delete)\(/.test(agentServiceSrc + agentContextSrc + agentResponderSrc),
  'agent layer must be read-only')
const agentIntentsSrc = read(path.join(agentDir, 'intents.py'))
check(/அவசரம்/.test(agentIntentsSrc) && /आपातकाल/.test(agentIntentsSrc),
  'agent safety intents must cover Tamil + Hindi')
const agentRouterSrc = read(path.join(APP, 'routers/agent.py'))
check((agentRouterSrc.match(/get_current_patient/g) || []).length >= 2,
  'agent routes must require authentication')
check(/@router\.post\("\/api\/agent\/chat"/.test(agentRouterSrc) &&
  /@router\.get\("\/api\/agent\/suggestions"/.test(agentRouterSrc),
  'agent routes missing')
check(/include_router\(agent\.router\)/.test(read(path.join(APP, 'main.py'))),
  'agent router not wired in main.py')
const agentSchemasSrc = read(path.join(APP, 'schemas.py'))
check(/class AgentChatIn/.test(agentSchemasSrc) && /class AgentChatOut/.test(agentSchemasSrc),
  'agent schemas missing')
check(/agent_llm_provider: str = Field\(default="none"/.test(configSrc),
  'LLM must be off by default')

section('A13. admin dashboard: read-only, separate credential, fails closed')
const adminRouterFile = path.join(APP, 'routers/admin.py')
check(fs.existsSync(adminRouterFile), 'admin router missing')
const adminRouterSrc = read(adminRouterFile)
check(!/(?:db\.add|db\.commit|db\.delete)\(/.test(adminRouterSrc),
  'admin layer must never write to the database')
check((adminRouterSrc.match(/get_current_admin/g) || []).length >= 5,
  'every admin read route must require get_current_admin')
check(!/payload\.password\s*==|==\s*payload\.password|settings\.admin_password\s*==|==\s*settings\.admin_password/.test(adminRouterSrc),
  'admin router must never compare the password in plaintext')
const securitySrc = read(path.join(APP, 'core/security.py'))
check(/def create_admin_token/.test(securitySrc) && /"type":\s*"admin"/.test(securitySrc),
  'admin token must carry type=admin')
check(/def verify_admin_credentials/.test(securitySrc) && /hmac\.compare_digest/.test(securitySrc),
  'admin credential check must be constant-time (hmac.compare_digest)')
check(/def admin_lockout_active/.test(securitySrc) && /ADMIN_MAX_FAILURES/.test(securitySrc),
  'admin login lockout helpers missing')
const depsSrc = read(path.join(APP, 'core/deps.py'))
check(/def get_current_admin/.test(depsSrc) && /decode_admin_token/.test(depsSrc),
  'get_current_admin must decode the admin token type')
check(/include_router\(admin\.router\)/.test(read(path.join(APP, 'main.py'))),
  'admin router not wired in main.py')
check(/admin_username: str = Field\(default=""/.test(configSrc) &&
  /admin_password: str = Field\(default=""/.test(configSrc),
  'admin credentials must default to empty (fail closed)')
check(/def admin_configured/.test(configSrc), 'admin_configured property missing')
check(/status_code=503/.test(adminRouterSrc) && /admin_configured/.test(adminRouterSrc),
  'unconfigured admin login must answer 503')
const adminSchemasSrc = read(path.join(APP, 'schemas.py'))
check(/class AdminLoginIn/.test(adminSchemasSrc) && /class AdminStatsOut/.test(adminSchemasSrc) &&
  /class AdminOccurrenceOut/.test(adminSchemasSrc),
  'admin schemas missing')

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

section('B0. register + log in as a throwaway audit patient (Phase 2/3 auth)')
{
  const phone = '+9198' + Array.from({ length: 7 }, () => Math.floor(Math.random() * 10)).join('')
  const req = await hit('/api/auth/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      phone,
      full_name: 'Audit Patient',
      preferred_lang: 'en',
      preferred_channel: 'whatsapp',
    }),
  })
  check(req.status === 201 && /^\d{6}$/.test(req.body?.dev_code || ''),
    `register -> ${req.status}`)
  check(req.body?.sent_via === 'whatsapp', `register sent_via -> ${req.body?.sent_via}`)
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

section('B12. reminder engine: enroll/send only from the verified timetable')
{
  const demo3 = (await hit('/api/demo', { method: 'POST' })).body
  const fixedSlot = (item) =>
    SAFE.has(item.status) && !item.as_needed && (item.slots || []).length > 0
  const eligible = demo3.items.filter(fixedSlot)
  const excludedIds = new Set(demo3.items.filter((i) => !fixedSlot(i)).map((i) => i.id))

  const enroll = await hit(`/api/prescriptions/${demo3.id}/reminders/enroll`, { method: 'POST' })
  check(enroll.status === 200 && enroll.body?.scheduled_doses > 0, `enroll -> ${enroll.status}/${enroll.body?.scheduled_doses}`)
  const enrolledIds = new Set((enroll.body?.items || []).map((entry) => entry.item_id))
  check(enrolledIds.size > 0 && [...enrolledIds].every((id) => eligible.some((i) => i.id === id)),
    'enrollment includes an unclear/as-needed item')
  const skippedIds = new Set((enroll.body?.skipped || []).map((entry) => entry.item_id))
  check([...excludedIds].every((id) => skippedIds.has(id)),
    `excluded items not all skipped: ${[...skippedIds].join(',')}`)

  const upcoming = await hit('/api/reminders/upcoming?days=2')
  const occurrences = Array.isArray(upcoming.body) ? upcoming.body : []
  check(upcoming.status === 200 && occurrences.length > 0, `upcoming -> ${upcoming.status}/${occurrences.length}`)
  check(occurrences.every((occ) => enrolledIds.has(occ.item_id)),
    'upcoming contains an occurrence for a non-enrolled item')
  check(occurrences.every((occ) => ['08:00', '13:00', '18:00', '21:00'].includes(occ.local_time)),
    'upcoming occurrence has a non-standard local time')

  const consentBefore = await hit('/api/patients/me/consent')
  check(Array.isArray(consentBefore.body) && consentBefore.body.every((c) => c.granted === false),
    'a brand-new patient should start with no consent')

  const runNoConsent = await hit('/api/reminders/run', { method: 'POST' })
  check(runNoConsent.status === 200 && runNoConsent.body?.sent === 0,
    `no-consent run sent something: ${JSON.stringify(runNoConsent.body)}`)

  await hit('/api/patients/me/consent', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ channel: 'whatsapp', granted: true }),
  })
  const runConsent = await hit('/api/reminders/run', { method: 'POST' })
  check(runConsent.status === 200 && (runConsent.body?.sent ?? 0) >= 0, `consented run -> ${runConsent.status}`)

  const history = await hit('/api/reminders/history')
  const sentOccurrences = (Array.isArray(history.body) ? history.body : []).filter((o) => o.status === 'sent')
  check(sentOccurrences.every((occ) => enrolledIds.has(occ.item_id) && !excludedIds.has(occ.item_id)),
    'a reminder was sent for an unclear/as-needed item')
  check(sentOccurrences.every((occ) => occ.body.startsWith('MedRecall:')),
    'sent reminder body missing the MedRecall prefix')
  console.log(`   enrolled dose times: ${enroll.body?.scheduled_doses}, due sends this run: ${runConsent.body?.sent}`)

  // leave no reminders running for the throwaway audit patient
  await hit(`/api/prescriptions/${demo3.id}/reminders/enroll`, { method: 'DELETE' })
}

section('B13. AI care agent answers only from the verified timetable')
{
  const agentChat = (message, lang) =>
    hit('/api/agent/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(lang ? { message, lang } : { message }),
    })

  const anonymous = await fetch(`${BASE}/api/agent/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message: 'What medicines do I take?' }),
  })
  check(anonymous.status === 401, `unauthenticated agent chat -> ${anonymous.status}`)

  // A fresh patient guarantees the agent sees exactly one demo prescription
  // (the audit patient above accumulates confirmed/edited prescriptions).
  const phone13 = '+9198' + Array.from({ length: 7 }, () => Math.floor(Math.random() * 10)).join('')
  const req13 = await hit('/api/auth/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      phone: phone13,
      full_name: 'Agent Audit Patient',
      preferred_lang: 'en',
      preferred_channel: 'whatsapp',
    }),
  })
  const verify13 = await hit('/api/auth/otp/verify', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ phone: phone13, code: req13.body?.dev_code }),
  })
  check(verify13.status === 200 && verify13.body?.access_token, `agent login -> ${verify13.status}`)
  AUTH_HEADERS = { Authorization: 'Bearer ' + (verify13.body?.access_token || '') }

  const demo13 = (await hit('/api/demo', { method: 'POST' })).body

  const list = await agentChat('What medicines do I take?')
  const listReply = list.body?.reply || ''
  check(list.status === 200 && list.body?.intent === 'list_medicines', `agent list -> ${list.status}/${list.body?.intent}`)
  check(listReply.includes('Paracetamol') && listReply.includes('Amoxicillin'),
    'agent list missing verified medicines')
  check(!listReply.includes('??'), 'agent echoed unverified source text')
  const cetirizineLine = listReply.split('\n').find((line) => line.includes('Cetirizine')) || ''
  check(Boolean(cetirizineLine) && !cetirizineLine.includes('21:00') && !/\bmg\b/.test(cetirizineLine),
    'agent gave a dose/time for an unclear item')

  const unclearAsk = await agentChat('When should I take Cetirizine?')
  check(unclearAsk.status === 200 && !/21:00|\bmg\b|0-0-1/.test(unclearAsk.body?.reply || ''),
    'agent invented a time/dose for an unclear item')

  const dose = await agentChat('Can I double my dose?')
  check(dose.body?.intent === 'dose_change' && dose.body?.safety_blocked === true,
    'dose-change question was not refused')
  check(!/1000\s*mg/.test(dose.body?.reply || ''), 'agent suggested an unverified dose')

  const missed = await agentChat('I missed my Paracetamol dose')
  check(/Do not take a double dose/.test(missed.body?.reply || ''),
    'missed-dose answer must warn against doubling')

  const timetable = await agentChat('What is my timetable today?')
  const timetableReply = timetable.body?.reply || ''
  check(['08:00', '13:00', '21:00'].every((time) => timetableReply.includes(time)),
    'agent timetable missing verified slot times')
  check(!timetableReply.includes('Cetirizine') && !timetableReply.includes('Cough Syrup'),
    'agent timetable contains an unclear/as-needed item')

  const tamil = await agentChat('என் மருந்துகள் என்ன?', 'ta')
  check(tamil.body?.lang === 'ta' && /[\u0B80-\u0BFF]/.test(tamil.body?.reply || ''),
    'agent Tamil answer missing Tamil text')

  const suggestions = await hit('/api/agent/suggestions?lang=hi')
  const hindiSuggestions = suggestions.body?.suggestions || []
  check(suggestions.status === 200 && hindiSuggestions.length >= 4,
    `agent suggestions -> ${suggestions.status}/${hindiSuggestions.length}`)
  check(hindiSuggestions.every((question) => /[\u0900-\u097F]/.test(question)),
    'agent suggestions not localized')

  const sources = list.body?.sources || []
  check(sources.length > 0 && sources.every((source) => source.prescription_id === demo13.id),
    'agent sources leak another prescription')
  check(sources.every((source) => ['clear', 'confirmed', 'edited', 'unclear'].includes(source.status)),
    'agent source has an unknown status')
}

section('B14. admin dashboard: separate credential, read-only, fails closed')
{
  const adminUser = process.env.MEDRECALL_ADMIN_USERNAME || ''
  const adminPass = process.env.MEDRECALL_ADMIN_PASSWORD || ''
  const adminPost = (url, payload, token) =>
    fetch(`${BASE}${url}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: 'Bearer ' + token } : {}),
      },
      body: JSON.stringify(payload),
    }).then(async (res) => ({ status: res.status, body: await res.json().catch(() => null) }))
  const adminGet = (url, token) =>
    fetch(`${BASE}${url}`, { headers: token ? { Authorization: 'Bearer ' + token } : {} })
      .then(async (res) => ({ status: res.status, body: await res.json().catch(() => null) }))

  if (!adminUser || !adminPass) {
    // Unconfigured in this audit process -> the dashboard must fail closed.
    const login = await adminPost('/api/admin/login', { username: 'admin', password: 'x' })
    check(login.status === 503, `unconfigured admin login -> ${login.status} (want 503)`)
    check((await adminGet('/api/admin/stats')).status === 401,
      'unconfigured admin stats must be 401')
    check((await adminGet('/api/admin/patients')).status === 401,
      'unconfigured admin patients must be 401')
  } else {
    // Wrong credentials with a RANDOM username (never the configured one):
    // the lockout is per-username, in-memory server-side, so repeated audit
    // runs must never accumulate failures against the real admin account.
    const bogus = 'audit-' + Math.random().toString(36).slice(2, 10)
    const bad = await adminPost('/api/admin/login', { username: bogus, password: 'wrong-' + bogus })
    check(bad.status === 401, `bad admin login -> ${bad.status} (want 401)`)

    const ok = await adminPost('/api/admin/login', { username: adminUser, password: adminPass })
    check(ok.status === 200 && ok.body?.access_token, `admin login -> ${ok.status}`)
    const token = ok.body?.access_token || ''

    const stats = await adminGet('/api/admin/stats', token)
    check(stats.status === 200 && stats.body?.patients >= 1 && stats.body?.prescriptions >= 1,
      `admin stats -> ${stats.status}`)
    check(Object.keys(stats.body?.items_by_status || {}).length > 0,
      'admin stats missing item statuses')

    const patients = await adminGet('/api/admin/patients?page=1&page_size=10', token)
    check(patients.status === 200 && patients.body?.items?.length >= 1,
      `admin patients -> ${patients.status}`)

    const firstId = patients.body?.items?.[0]?.id
    const detail = await adminGet(`/api/admin/patients/${firstId}`, token)
    check(detail.status === 200 && detail.body?.patient?.id === firstId,
      `admin patient detail -> ${detail.status}`)

    const rxId = detail.body?.prescriptions?.[0]?.id
    const rx = await adminGet(`/api/admin/prescriptions/${rxId}`, token)
    check(rx.status === 200 && rx.body?.id === rxId, `admin prescription view -> ${rx.status}`)

    const reminders = await adminGet('/api/admin/reminders?limit=5', token)
    check(reminders.status === 200 && Array.isArray(reminders.body?.items),
      `admin reminders -> ${reminders.status}`)
    check((reminders.body?.items || []).every(
      (row) => ['pending', 'sent', 'blocked', 'failed', 'missed', 'cancelled'].includes(row.status)),
      'admin feed row has an unknown status')

    // Token families must never cross the patient/admin boundary.
    const patientTok = (AUTH_HEADERS.Authorization || '').replace('Bearer ', '')
    check((await adminGet('/api/admin/stats', patientTok)).status === 401,
      'patient token on admin route must be 401')
    check((await adminGet('/api/patients/me', token)).status === 401,
      'admin token on patient route must be 401')
    check((await adminGet('/api/admin/stats')).status === 401,
      'anonymous admin route must be 401')
  }
}

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
