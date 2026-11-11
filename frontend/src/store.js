/**
 * "Mark as taken" persistence (localStorage, per prescription per day).
 * Feeds the Home dashboard progress bar and the timetable toggles.
 */
const STORAGE_KEY = 'medrecall:taken'

export function todayStr(date = new Date()) {
  const mm = String(date.getMonth() + 1).padStart(2, '0')
  const dd = String(date.getDate()).padStart(2, '0')
  return `${date.getFullYear()}-${mm}-${dd}`
}

function loadAll() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : {}
  } catch {
    return {}
  }
}

function saveAll(data) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(data))
  } catch {
    /* ignore */
  }
}

/** {itemId: true} for the given prescription on the given day. */
export function loadTaken(prescriptionId, date = todayStr()) {
  const all = loadAll()
  return (all[prescriptionId] && all[prescriptionId][date]) || {}
}

/** Toggle one dose; returns the new taken map (and persists it). */
export function toggleTaken(prescriptionId, itemId, date = todayStr()) {
  const all = loadAll()
  if (!all[prescriptionId]) all[prescriptionId] = {}
  if (!all[prescriptionId][date]) all[prescriptionId][date] = {}
  const day = all[prescriptionId][date]
  if (day[itemId]) {
    delete day[itemId]
  } else {
    day[itemId] = true
  }
  saveAll(all)
  return { ...day }
}

/** How many of the given dose entries are marked taken today. */
export function takenCount(prescriptionId, doseItemIds, date = todayStr()) {
  const taken = loadTaken(prescriptionId, date)
  return doseItemIds.filter((id) => taken[id]).length
}

// ---------------------------------------------------------------------------
// "Snooze 30m" — per dose, per day. Snoozing never changes a medicine or a
// prescribed time; it only postpones the dashboard's next-dose prompt locally.
// ---------------------------------------------------------------------------

const SNOOZE_KEY = 'medrecall:snoozed'

function loadAllSnoozes() {
  try {
    const raw = localStorage.getItem(SNOOZE_KEY)
    return raw ? JSON.parse(raw) : {}
  } catch {
    return {}
  }
}

function saveAllSnoozes(data) {
  try {
    localStorage.setItem(SNOOZE_KEY, JSON.stringify(data))
  } catch {
    /* ignore */
  }
}

/** {doseKey: epochMillis} for the given prescription on the given day. */
export function loadSnoozes(prescriptionId, date = todayStr()) {
  const all = loadAllSnoozes()
  return (all[prescriptionId] && all[prescriptionId][date]) || {}
}

/** Postpone one dose prompt for `minutes`; returns the new snooze map. */
export function snoozeDose(prescriptionId, doseKey, minutes = 30, date = todayStr()) {
  const all = loadAllSnoozes()
  if (!all[prescriptionId]) all[prescriptionId] = {}
  if (!all[prescriptionId][date]) all[prescriptionId][date] = {}
  all[prescriptionId][date][doseKey] = Date.now() + Math.max(1, minutes) * 60_000
  saveAllSnoozes(all)
  return { ...all[prescriptionId][date] }
}

// ---------------------------------------------------------------------------
// "Last opened prescription" — lets the Home dashboard show today's progress
// without asking the user for an id.
// ---------------------------------------------------------------------------

const LAST_KEY = 'medrecall:last'

export function getLastPrescription() {
  try {
    const raw = localStorage.getItem(LAST_KEY)
    const value = raw ? Number.parseInt(raw, 10) : NaN
    return Number.isFinite(value) ? value : null
  } catch {
    return null
  }
}

export function setLastPrescription(id) {
  try {
    if (id == null) localStorage.removeItem(LAST_KEY)
    else localStorage.setItem(LAST_KEY, String(id))
  } catch {
    /* ignore */
  }
}
