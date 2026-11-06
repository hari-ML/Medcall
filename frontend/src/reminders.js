/**
 * Browser notification reminders (Notification API).
 *
 * Reminders fire ONLY while the MedRecall tab is open — this is a client-side
 * scheduler (interval tick every 20 s), matching the MVP scope. Each reminder
 * fires at most once per day per item; "already fired" state persists in
 * localStorage so a page refresh does not re-notify.
 *
 * Only reminders returned by the backend are used — the backend already
 * excludes unclear and as-needed (SOS) medicines.
 */
const FIRED_STORAGE_KEY = 'medrecall:fired'
const TICK_MS = 20000
const GRACE_MINUTES = 45 // fire if we are within 45 min after the dose time

let intervalId = null
let currentReminders = []

export function notificationsSupported() {
  return typeof window !== 'undefined' && 'Notification' in window
}

/** Ask for permission once; returns 'granted' | 'denied' | 'default' | 'unsupported'. */
export async function requestPermission() {
  if (!notificationsSupported()) return 'unsupported'
  if (Notification.permission === 'granted') return 'granted'
  if (Notification.permission === 'denied') return 'denied'
  try {
    const result = await Notification.requestPermission()
    return result
  } catch {
    return 'denied'
  }
}

export function permissionState() {
  if (!notificationsSupported()) return 'unsupported'
  return Notification.permission // 'granted' | 'denied' | 'default'
}

function todayKey() {
  const now = new Date()
  const mm = String(now.getMonth() + 1).padStart(2, '0')
  const dd = String(now.getDate()).padStart(2, '0')
  return `${now.getFullYear()}-${mm}-${dd}`
}

function loadFired() {
  try {
    const raw = localStorage.getItem(FIRED_STORAGE_KEY)
    const data = raw ? JSON.parse(raw) : {}
    // keep only recent dates (max 3) so the key stays small
    const keys = Object.keys(data).sort().reverse().slice(0, 3)
    const cleaned = {}
    keys.forEach((k) => {
      cleaned[k] = data[k]
    })
    return cleaned
  } catch {
    return {}
  }
}

function saveFired(data) {
  try {
    localStorage.setItem(FIRED_STORAGE_KEY, JSON.stringify(data))
  } catch {
    /* ignore */
  }
}

function minutesSinceMidnight(hhmm) {
  const [h, m] = String(hhmm).split(':').map((n) => parseInt(n, 10))
  if (Number.isNaN(h) || Number.isNaN(m)) return null
  return h * 60 + m
}

function reminderKey(reminder) {
  return `${reminder.time}|${reminder.medicine}`
}

function showNotification(reminder, lang) {
  const title = `MedRecall · ${reminder.time} · ${reminder.medicine}`
  const body = reminder.instruction
  try {
    // tag keeps one notification per medicine+time (no duplicates on re-tick)
    const n = new Notification(title, {
      body,
      tag: reminderKey(reminder),
      lang,
      requireInteraction: true,
    })
    n.onclick = () => {
      window.focus()
      n.close()
    }
  } catch {
    /* some browsers throw on constructor in insecure contexts */
  }
}

/** Find reminders due in this tick (time passed, within grace window, not yet fired today). */
export function dueReminders(reminders, now = new Date(), firedStore = null) {
  const store = firedStore || loadFired()
  const firedToday = store[todayKey()] || []
  const nowMinutes = now.getHours() * 60 + now.getMinutes()

  return reminders.filter((reminder) => {
    const doseMinutes = minutesSinceMidnight(reminder.time)
    if (doseMinutes == null) return false
    const diff = nowMinutes - doseMinutes
    if (diff < 0 || diff > GRACE_MINUTES) return false
    return !firedToday.includes(reminderKey(reminder))
  })
}

function markFired(reminders) {
  const store = loadFired()
  const key = todayKey()
  const existing = store[key] || []
  const merged = [...new Set([...existing, ...reminders.map(reminderKey)])]
  store[key] = merged
  saveFired(store)
}

function tick() {
  if (!currentReminders.length || permissionState() !== 'granted') return
  const due = dueReminders(currentReminders)
  if (!due.length) return
  due.forEach((reminder) => showNotification(reminder))
  markFired(due)
}

/**
 * Start scheduling reminders. Returns a stop function.
 * Calling start again replaces any previous schedule (no double timers).
 */
export function startReminders(reminders, { lang = 'en' } = {}) {
  stopReminders()
  if (!notificationsSupported() || permissionState() !== 'granted') {
    return () => {}
  }
  currentReminders = Array.isArray(reminders) ? reminders.filter((r) => r?.time) : []
  tick() // fire anything already due
  intervalId = window.setInterval(tick, TICK_MS)
  return stopReminders
}

export function stopReminders() {
  if (intervalId != null) {
    window.clearInterval(intervalId)
    intervalId = null
  }
  currentReminders = []
}

export function remindersActive() {
  return intervalId != null
}

/** Reset today's "already fired" marks (used by tests / debugging). */
export function resetFiredToday() {
  const store = loadFired()
  delete store[todayKey()]
  saveFired(store)
}
