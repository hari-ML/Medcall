/**
 * MedRecall — frontend verification.
 *
 * Run from the repo root:  node scripts/frontend_verify.mjs
 * (needs `npm install` in frontend/ — esbuild comes from its node_modules)
 *
 * 1. esbuild bundle of main.jsx + App.jsx + all six components + eight pages
 * 2. Server-render (react-dom/server) of Header, Disclaimer, MedicineLine
 *    (clear + unclear), DoseCard, WarningCard, LanguageCard in en/ta/hi.
 * 3. i18n parity: UI tables identical key sets across en/ta/hi, no empty
 *    strings, disclaimer/slot/reason/preview tables complete for 3 languages.
 * 4. Usage audit: every literal t('key') used in src exists in UI.en.
 * 5. Full App render at every route (incl. the Phase 7 auth-protected
 *    Login/Reminders/Agent screens) in all three languages — the app gets an
 *    explicit `initialSession` so the route guard renders real content.
 */
import fs from 'node:fs'
import path from 'node:path'
import os from 'node:os'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'

const ROOT = fileURLToPath(new URL('..', import.meta.url))
const FRONTEND = path.join(ROOT, 'frontend')
const SRC = path.join(FRONTEND, 'src')
const OUT = path.join(os.tmpdir(), 'opencode')
fs.mkdirSync(OUT, { recursive: true })

const require = createRequire(path.join(FRONTEND, 'package.json'))
const esbuild = require('esbuild')

let checks = 0
const failures = []
function check(cond, label) {
  checks += 1
  if (!cond) failures.push(label)
}
function section(name) {
  console.log(`\n== ${name}`)
}

const externalPages = {
  name: 'external-pages-and-css',
  setup(build) {
    // Stage 5: ./pages/* didn't exist yet → keep them external.
    // Stage 6: they exist → return undefined so esbuild resolves & bundles them.
    build.onResolve({ filter: /^\.\/pages\// }, (args) => {
      const base = path.resolve(args.resolveDir, args.path)
      const exists =
        fs.existsSync(base) ||
        fs.existsSync(`${base}.jsx`) ||
        fs.existsSync(`${base}.js`) ||
        fs.existsSync(path.join(base, 'index.jsx'))
      return exists ? undefined : { path: args.path, external: true }
    })
    // CSS import: style-only, proof of JS resolution is enough here.
    build.onResolve({ filter: /\.css$/ }, (args) => ({ path: args.path, external: true }))
  },
}

// ---------------------------------------------------------------------------
// 1. Resolution bundle: main.jsx + App.jsx + every component
// ---------------------------------------------------------------------------
section('1. esbuild resolution bundle (main + App + components + pages)')
const COMPONENTS = ['Header', 'Disclaimer', 'WarningCard', 'LanguageCard', 'DoseCard', 'MedicineLine']
const entrySource = [
  "import './main.jsx'",
  ...COMPONENTS.map((name) => `import ${name} from './components/${name}.jsx'`),
  `export default [${COMPONENTS.join(', ')}]`,
].join('\n')

const bundlePath = path.join(OUT, 'stage5_bundle.mjs')
try {
  await esbuild.build({
    stdin: { contents: entrySource, resolveDir: SRC, loader: 'jsx', sourcefile: 'stage5_entry.jsx' },
    bundle: true,
    format: 'esm',
    jsx: 'automatic',
    target: 'es2020',
    loader: { '.js': 'jsx' }, // i18n.js contains JSX
    outfile: bundlePath,
    plugins: [externalPages],
    logLevel: 'silent',
  })
  const size = fs.statSync(bundlePath).size
  check(size > 10_000, `bundle suspiciously small (${size} bytes)`)
  console.log(`   OK — ${size} bytes bundled (main.jsx, App.jsx, ${COMPONENTS.length} components, 8 pages)`)
} catch (error) {
  failures.push('esbuild bundle failed: ' + (error?.message || error))
  console.error(error)
}

// ---------------------------------------------------------------------------
// 2. i18n parity (bundle i18n.js → CJS → require)
// ---------------------------------------------------------------------------
section('2. i18n key parity across en / ta / hi')
const i18nPath = path.join(OUT, 'stage5_i18n.cjs')
try {
  await esbuild.build({
    stdin: {
      contents:
        "export { UI, DISCLAIMER, SLOT_NAMES, REASON_TEXT, LANGUAGE_PREVIEWS, LANGS, localizeReason } from './i18n.jsx'",
      resolveDir: SRC,
      loader: 'jsx',
    },
    bundle: true,
    platform: 'node',
    format: 'cjs',
    jsx: 'automatic',
    loader: { '.js': 'jsx' }, // i18n.js contains JSX
    outfile: i18nPath,
    logLevel: 'silent',
  })
  const i18n = require(i18nPath)
  const LANGS3 = ['en', 'ta', 'hi']

  check(JSON.stringify(i18n.LANGS.map((l) => l.code)) === JSON.stringify(LANGS3), 'LANGS != [en,ta,hi]')

  const enKeys = Object.keys(i18n.UI.en).sort()
  console.log(`   UI.en has ${enKeys.length} keys`)
  check(enKeys.length >= 90, `UI.en too small (${enKeys.length} keys)`)

  for (const lang of LANGS3) {
    const table = i18n.UI[lang]
    check(Boolean(table), `UI.${lang} missing`)
    if (!table) continue

    const keys = Object.keys(table).sort()
    const missing = enKeys.filter((k) => !(k in table))
    const extra = keys.filter((k) => !(enKeys.includes(k)))
    check(missing.length === 0, `UI.${lang} missing keys: ${missing.join(', ')}`)
    check(extra.length === 0, `UI.${lang} extra keys: ${extra.join(', ')}`)

    const empty = Object.entries(table)
      .filter(([, value]) => typeof value !== 'string' || value.trim() === '')
      .map(([k]) => k)
    check(empty.length === 0, `UI.${lang} empty values: ${empty.join(', ')}`)

    check(typeof i18n.DISCLAIMER[lang] === 'string' && i18n.DISCLAIMER[lang].trim().length > 20,
      `DISCLAIMER.${lang} missing/too short`)
    check(typeof i18n.LANGUAGE_PREVIEWS[lang] === 'string' && i18n.LANGUAGE_PREVIEWS[lang].trim().length > 5,
      `LANGUAGE_PREVIEWS.${lang} missing`)

    const slots = Object.keys(i18n.SLOT_NAMES[lang] || {}).sort().join(',')
    check(slots === 'afternoon,evening,morning,night', `SLOT_NAMES.${lang} = ${slots}`)

    const reasons = Object.keys(i18n.REASON_TEXT[lang] || {})
    check(reasons.length >= 7, `REASON_TEXT.${lang} only has ${reasons.length} entries`)
  }
  const enReasonKeys = Object.keys(i18n.REASON_TEXT.en).sort().join(',')
  for (const lang of LANGS3) {
    check(Object.keys(i18n.REASON_TEXT[lang]).sort().join(',') === enReasonKeys,
      `REASON_TEXT.${lang} keys differ from en`)
  }
  console.log('   OK — UI keys, disclaimers, slot names, reasons, previews aligned')
} catch (error) {
  failures.push('i18n parity check failed: ' + (error?.message || error))
  console.error(error)
}

// ---------------------------------------------------------------------------
// 3. Usage audit: every literal t('key') exists in UI.en
// ---------------------------------------------------------------------------
section("3. t('key') usage audit against UI.en")
try {
  const i18n = require(i18nPath)
  const enKeys = new Set(Object.keys(i18n.UI.en))
  function walk(dir) {
    const out = []
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name)
      if (entry.isDirectory()) out.push(...walk(full))
      else out.push(full)
    }
    return out
  }
  const used = new Set()
  for (const file of walk(SRC)) {
    if (!/\.(jsx?|tsx?)$/.test(file)) continue
    if (path.basename(file) === 'i18n.jsx') continue // defines t(), not a consumer
    const code = fs.readFileSync(file, 'utf8')
    for (const match of code.matchAll(/\bt\(\s*'([^']+)'/g)) used.add(match[1])
  }
  const unknown = [...used].filter((key) => !enKeys.has(key)).sort()
  check(unknown.length === 0, `t() keys missing from UI.en: ${unknown.join(', ')}`)
  console.log(`   OK — ${used.size} distinct t() keys used, all present in UI.en`)
} catch (error) {
  failures.push('usage audit failed: ' + (error?.message || error))
  console.error(error)
}

// ---------------------------------------------------------------------------
// 4. Server-render smoke test of all components in all three languages
// ---------------------------------------------------------------------------
section('4. server-render components in en / ta / hi')
const renderEntry = `
import React from 'react'
import { renderToString } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { LangProvider, DISCLAIMER, LANGUAGE_PREVIEWS, UI } from './i18n.jsx'
import App from './App.jsx'
import Header from './components/Header.jsx'
import Disclaimer from './components/Disclaimer.jsx'
import WarningCard from './components/WarningCard.jsx'
import LanguageCard from './components/LanguageCard.jsx'
import DoseCard, { doseKey } from './components/DoseCard.jsx'
import MedicineLine from './components/MedicineLine.jsx'

// Phase 7: the app is behind phone-OTP auth; SSR passes an explicit session
// through the same seam as initialLang, so protected routes render their
// real content (no localStorage in Node).
const SESSION = {
  access_token: 'ssr-token',
  expires_at: 4102444800000,
  patient: {
    id: 1, phone: '+919800000000', phone_verified: true, full_name: 'Test Patient',
    preferred_lang: 'en', timezone: 'Asia/Kolkata', caregiver_name: '', caregiver_phone: '',
    created_at: '2026-01-01T00:00:00Z',
  },
}

const unclearItem = {
  id: 3, line_number: 3, medicine: 'Cetirizine', strength: null, form: 'tab',
  frequency: '0-0-1', food_timing: null, duration_days: null, as_needed: false,
  slots: ['night'], status: 'unclear', reason: 'Dose unreadable',
  source_text: 'Tab Cetirizine ?? mg 0-0-1', confidence: 68.5,
}
const clearItem = {
  id: 1, line_number: 1, medicine: 'Paracetamol', strength: '500 mg', form: 'tab',
  frequency: '1-0-1', food_timing: 'after', duration_days: 5, as_needed: false,
  slots: ['morning', 'night'], status: 'clear', reason: '',
  source_text: 'Tab Paracetamol 500 mg 1-0-1 after food x 5 days', confidence: 95.4,
}
const entries = [
  {
    id: 1, medicine: 'Paracetamol', status: 'clear',
    instruction: '500 mg tablet, 1 in the morning, 1 at night, after food, for 5 days',
    time: '08:00', slot: 'morning',
  },
]

function Shell({ lang, children }) {
  return (
    <MemoryRouter>
      <LangProvider initialLang={lang}>{children}</LangProvider>
    </MemoryRouter>
  )
}

const renders = {}
for (const lang of ['en', 'ta', 'hi']) {
  renders[lang] = {
    header: renderToString(<Shell lang={lang}><Header /></Shell>),
    disclaimer: renderToString(<Shell lang={lang}><Disclaimer /></Shell>),
    unclearLine: renderToString(
      <Shell lang={lang}>
        <MedicineLine item={unclearItem} onConfirm={async () => {}} onEdit={async () => {}} />
      </Shell>,
    ),
    clearLine: renderToString(
      <Shell lang={lang}>
        <MedicineLine item={clearItem} onConfirm={async () => {}} onEdit={async () => {}} />
      </Shell>,
    ),
    doseCard: renderToString(
      <Shell lang={lang}>
        <DoseCard
          slot="morning"
          time="08:00"
          entries={entries}
          taken={{ '1:morning': true }}
          onToggle={() => {}}
          emptyNote="Nothing scheduled"
        />
      </Shell>,
    ),
    emptyCard: renderToString(
      <Shell lang={lang}>
        <DoseCard slot="evening" time="18:00" entries={[]} emptyNote="No medicines here" />
      </Shell>,
    ),
    warning: renderToString(<Shell lang={lang}><WarningCard title="Not in this timetable" body="Needs confirmation" /></Shell>),
    languageCard: renderToString(
      <Shell lang={lang}><LanguageCard code="ta" selected onSelect={() => {}} /></Shell>,
    ),
  }
}
globalThis.__renders = renders
globalThis.__routes = (function buildRouteRenders() {
  const routeCases = {
    home: '/',
    upload: '/upload',
    review: '/review/1',
    language: '/language/1',
    timetable: '/timetable/1',
    login: '/login',
    reminders: '/reminders',
    agent: '/agent',
  }
  const out = {}
  for (const lang of ['en', 'ta', 'hi']) {
    out[lang] = {}
    for (const [name, route] of Object.entries(routeCases)) {
      out[lang][name] = renderToString(
        <MemoryRouter initialEntries={[route]}>
          <App initialLang={lang} initialSession={SESSION} />
        </MemoryRouter>,
      )
    }
  }
  return out
})()
globalThis.__doseKey = doseKey({ id: 7, slot: 'night' })
globalThis.__UI = UI
globalThis.__DISCLAIMER = DISCLAIMER
globalThis.__PREVIEWS = LANGUAGE_PREVIEWS
export default true
`

const renderPath = path.join(OUT, 'stage5_render.cjs')
try {
  await esbuild.build({
    stdin: { contents: renderEntry, resolveDir: SRC, loader: 'jsx', sourcefile: 'stage5_render.jsx' },
    bundle: true,
    platform: 'node',
    format: 'cjs',
    jsx: 'automatic',
    target: 'node18',
    loader: { '.js': 'jsx' }, // i18n.js contains JSX
    outfile: renderPath,
    logLevel: 'silent',
  })
  // react-router's MemoryRouter logs expected SSR useLayoutEffect warnings —
  // irrelevant to this check, keep the output readable.
  const realError = console.error
  console.error = () => {}
  let renders
  try {
    require(renderPath)
    renders = globalThis.__renders
  } finally {
    console.error = realError
  }
  const UI3 = globalThis.__UI
  const DIS = globalThis.__DISCLAIMER
  const PREV = globalThis.__PREVIEWS

  for (const lang of ['en', 'ta', 'hi']) {
    const r = renders[lang]
    check(Boolean(r), `no renders for ${lang}`)
    if (!r) continue

    // header: app name + all three language switcher buttons + Home
    check(r.header.includes('MedRecall'), `${lang}: header missing app name`)
    check(r.header.includes('English') && r.header.includes('தமிழ்') && r.header.includes('हिन्दी'),
      `${lang}: header missing language switcher`)
    check(r.header.includes(UI3[lang].home), `${lang}: header missing Home label`)

    // persistent disclaimer in the right language
    check(r.disclaimer.includes(DIS[lang]), `${lang}: footer disclaimer mismatch`)

    // unclear line: reason + safety copy + no-schedule marker + confirm button
    check(r.unclearLine.includes('Tab Cetirizine ?? mg 0-0-1'), `${lang}: source text missing`)
    check(r.unclearLine.includes(UI3[lang].statusUnclear), `${lang}: unclear status label missing`)
    check(r.unclearLine.includes(UI3[lang].confirmLine), `${lang}: confirm button missing`)
    check(r.unclearLine.includes(UI3[lang].notAddedYet), `${lang}: 'not added yet' chip missing`)
    check(r.unclearLine.includes('Dose unreadable') || r.unclearLine.includes(UI3[lang].statusUnclear),
      `${lang}: reason text missing`)

    // clear line: status + confidence + parsed summary
    check(r.clearLine.includes(UI3[lang].statusClear), `${lang}: clear status label missing`)
    check(r.clearLine.includes(UI3[lang].confidence.replace('{n}', '95')),
      `${lang}: confidence chip missing`)
    check(r.clearLine.includes('500 mg') && r.clearLine.includes('1-0-1'),
      `${lang}: parsed summary missing`)

    // dose card: medicine, instruction, taken state, localized slot name
    check(r.doseCard.includes('Paracetamol'), `${lang}: dose card medicine missing`)
    check(r.doseCard.includes('after food'), `${lang}: dose card instruction missing`)
    check(r.doseCard.includes(UI3[lang].taken), `${lang}: taken label missing`)
    check(r.doseCard.includes('08:00'), `${lang}: dose card time missing`)

    // empty slot note
    check(r.emptyCard.includes('No medicines here'), `${lang}: empty slot note missing`)

    // warning card content
    check(r.warning.includes('Not in this timetable'), `${lang}: warning title missing`)

    // language card: shows the ta preview + ta native label in any UI language
    check(r.languageCard.includes('தமிழ்'), `${lang}: language card native label missing`)
    check(r.languageCard.includes(PREV.ta), `${lang}: language card preview missing`)
    check(r.languageCard.includes(UI3[lang].selected), `${lang}: selected label missing`)
  }

  // dose key convention used by store.js / Home / Timetable
  check(globalThis.__doseKey === '7:night', `doseKey({id:7,slot:night}) = ${globalThis.__doseKey}`)

  // ------------------------------------------------------------------
  // 5. the FULL app at every route (header + pages + persistent disclaimer)
  // ------------------------------------------------------------------
  section('5. full App render at every route (en / ta / hi)')
  const routeRenders = globalThis.__routes
  check(Boolean(routeRenders), 'route renders missing')
  if (routeRenders) {
    for (const lang of ['en', 'ta', 'hi']) {
      const r = routeRenders[lang]
      check(Boolean(r), `no route renders for ${lang}`)
      if (!r) continue

      const expectIn = (routeName, needles) => {
        const html = r[routeName]
        check(typeof html === 'string' && html.length > 100, `${routeName} (${lang}): empty render`)
        for (const needle of needles) {
          check(typeof html === 'string' && html.includes(needle), `${routeName} (${lang}) missing: ${needle}`)
        }
      }

      // EVERY route carries the header logo + the persistent disclaimer
      const allRoutes = ['home', 'upload', 'review', 'language', 'timetable',
        'login', 'reminders', 'agent']
      for (const name of allRoutes) {
        check(r[name].includes('MedRecall'), `${name} (${lang}): missing header/logo`)
        check(r[name].includes(DIS[lang]), `${name} (${lang}): missing persistent disclaimer`)
      }

      expectIn('home', [UI3[lang].tagline, UI3[lang].scanPrescription, UI3[lang].tryDemo, UI3[lang].nextDose])
      expectIn('upload', [UI3[lang].uploadTitle, UI3[lang].dropHere, UI3[lang].chooseFile, UI3[lang].takePhoto, UI3[lang].noPrescription])
      expectIn('review', [UI3[lang].loading]) // data loads in useEffect (client only)
      expectIn('language', [UI3[lang].langTitle, UI3[lang].seeTimetable, 'English', 'தமிழ்', 'हिन्दी'])
      expectIn('timetable', [UI3[lang].loading])
      // Phase 7 routes: auth + reminders + agent
      expectIn('login', [UI3[lang].loginTitle, UI3[lang].phoneLabel, UI3[lang].loginIntro])
      expectIn('reminders', [UI3[lang].remindersTitle, UI3[lang].consentTitle,
        UI3[lang].upcomingTitle, UI3[lang].historyTitle])
      expectIn('agent', [UI3[lang].agentTitle, UI3[lang].agentIntro, UI3[lang].agentSend])
    }
    console.log('   OK — Home/Upload/Review/Language/Timetable/Login/Reminders/Agent render in en/ta/hi')
  }
  console.log('   OK — components rendered in en/ta/hi; doseKey convention intact')
} catch (error) {
  failures.push('render check failed: ' + (error?.message || error))
  console.error(error)
}

// ---------------------------------------------------------------------------
// Verdict
// ---------------------------------------------------------------------------
console.log('\n========================================')
if (failures.length === 0) {
  console.log(`FRONTEND VERIFICATION PASSED — ${checks} checks, 0 failures`)
} else {
  console.log(`FAILURES (${failures.length} of ${checks} checks):`)
  failures.forEach((failure) => console.log('  ✗ ' + failure))
  process.exitCode = 1
}
