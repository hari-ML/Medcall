import React, { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { createDemo, getReminders } from '../api'
import { useI18n } from '../i18n'
import {
  getLastPrescription,
  loadSnoozes,
  loadTaken,
  setLastPrescription,
  snoozeDose,
  toggleTaken,
} from '../store'

function minutesOf(hhmm) {
  const [h, m] = String(hhmm || '0:0').split(':').map((n) => parseInt(n, 10))
  if (Number.isNaN(h)) return 24 * 60
  return h * 60 + (Number.isNaN(m) ? 0 : m)
}

function clockOf(millis) {
  const date = new Date(millis)
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}

function greetKeyForNow() {
  const hour = new Date().getHours()
  if (hour < 12) return 'greetingMorning'
  if (hour < 17) return 'greetingAfternoon'
  if (hour < 20) return 'greetingEvening'
  return 'greetingNight'
}

/** One dose key per (medicine, slot) — same convention as DoseCard/store.js. */
function doseKeyOf(reminder) {
  return `${reminder.id}:${reminder.slot}`
}

/**
 * Home dashboard (Cozy design system).
 *
 * Bento layout: greeting + two entry points (scan / demo), a next-dose hero
 * with Mark taken and Snooze 30m, and today's adherence track. With no
 * prescription yet, the empty state leads with the white circular "magic"
 * scan button. The next dose is always read from the backend timetable —
 * never invented — and snoozing only postpones the dashboard prompt.
 */
export default function Home() {
  const { t, lang } = useI18n()
  const navigate = useNavigate()

  const [lastId, setLastId] = useState(() => getLastPrescription())
  const [reminders, setReminders] = useState([])
  const [taken, setTaken] = useState({})
  const [snoozes, setSnoozes] = useState({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  // today's reminders + local taken/snooze marks for the last prescription
  useEffect(() => {
    let cancelled = false
    async function load() {
      if (lastId == null) {
        setReminders([])
        return
      }
      try {
        const list = await getReminders(lastId, lang)
        if (!cancelled) setReminders(list)
      } catch (err) {
        if (err?.status === 404) {
          // prescription no longer exists — forget it instead of erroring
          setLastPrescription(null)
          if (!cancelled) setLastId(null)
        }
        if (!cancelled) setReminders([])
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [lastId, lang])

  useEffect(() => {
    if (lastId != null) {
      setTaken(loadTaken(lastId))
      setSnoozes(loadSnoozes(lastId))
    }
  }, [lastId])

  const total = reminders.length
  const takenCount = reminders.filter((reminder) => taken[doseKeyOf(reminder)]).length

  const nextDose = useMemo(() => {
    const now = new Date()
    const nowMinutes = now.getHours() * 60 + now.getMinutes()
    const nowMillis = now.getTime()
    return (
      reminders
        .filter((reminder) => {
          const key = doseKeyOf(reminder)
          const snoozedUntil = snoozes[key]
          if (snoozedUntil && snoozedUntil > nowMillis) return false
          return minutesOf(reminder.time) >= nowMinutes && !taken[key]
        })
        .sort((a, b) => minutesOf(a.time) - minutesOf(b.time))[0] || null
    )
  }, [reminders, taken, snoozes])

  const snoozeUntil = useMemo(() => {
    const nowMillis = Date.now()
    return reminders
      .map((reminder) => snoozes[doseKeyOf(reminder)])
      .filter((value) => value && value > nowMillis)
      .sort((a, b) => a - b)[0] || null
  }, [reminders, snoozes])

  async function handleDemo() {
    setBusy(true)
    setError(null)
    try {
      const prescription = await createDemo()
      setLastPrescription(prescription.id)
      setLastId(prescription.id)
      navigate(`/review/${prescription.id}`)
    } catch (err) {
      setError(err?.message || t('errorGeneric'))
    } finally {
      setBusy(false)
    }
  }

  function handleMarkTaken() {
    if (!nextDose || lastId == null) return
    setTaken({ ...toggleTaken(lastId, doseKeyOf(nextDose)) })
  }

  function handleSnooze() {
    if (!nextDose || lastId == null) return
    setSnoozes({ ...snoozeDose(lastId, doseKeyOf(nextDose), 30) })
  }

  const showProgress = lastId != null && total > 0
  const progressPercent = total ? Math.round((takenCount * 100) / total) : 0
  const hasPrescription = lastId != null

  return (
    <div className="space-y-8">
      {/* greeting + entry points */}
      <section className="flex flex-wrap items-start justify-between gap-5">
        <div className="min-w-0">
          <h1 className="text-lg font-medium leading-tight text-cozy-white">
            {t(greetKeyForNow())}
          </h1>
          <p className="mt-2 max-w-xl text-sm leading-relaxed text-cozy-quiet">{t('tagline')}</p>
        </div>
        <div className="flex flex-wrap gap-3">
          <Link to="/upload" className="btn-primary">
            <svg
              viewBox="0 0 24 24"
              className="h-5 w-5"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              aria-hidden="true"
            >
              <path d="M4 8h3l2-3h6l2 3h3v12H4Z" />
              <circle cx="12" cy="13" r="4" />
            </svg>
            {t('scanPrescription')}
          </Link>
          <button type="button" className="btn-outlined" onClick={handleDemo} disabled={busy}>
            {busy ? t('loading') : t('tryDemo')}
          </button>
        </div>
      </section>

      {error ? (
        <div role="alert" className="alert-error text-sm">
          {error}
        </div>
      ) : null}

      {/* empty state — the 48px white circular magic scan button */}
      {!hasPrescription ? (
        <section className="card flex flex-col items-center py-14 text-center">
          <Link to="/upload" className="magic-button" aria-label={t('magicScanLabel')}>
            <svg
              viewBox="0 0 24 24"
              className="h-6 w-6"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              aria-hidden="true"
            >
              <path d="M12 5v14M5 12h14" />
            </svg>
          </Link>
          <p className="mt-6 text-base font-medium text-cozy-white">{t('noPrescriptions')}</p>
          <p className="mt-2 text-sm text-cozy-quiet">{t('startScan')}</p>
        </section>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-5">
        {/* next-dose hero */}
        <section className="card lg:col-span-3">
          <div className="flex items-center justify-between gap-3">
            <span className="chip">{t('nextDose')}</span>
            {nextDose ? <span className="chip-teal">{nextDose.time}</span> : null}
          </div>

          {nextDose ? (
            <>
              <div className="mt-5 flex flex-wrap items-baseline gap-3">
                <h2 className="text-lg font-medium leading-tight text-cozy-white">
                  {nextDose.medicine}
                </h2>
                <span className="text-sm text-cozy-quiet">
                  {t('nextDoseAt', { time: nextDose.time })}
                </span>
              </div>
              <p className="mt-3 text-sm leading-relaxed text-cozy-quiet">
                {nextDose.instruction}
              </p>
              <div className="mt-6 flex flex-wrap gap-3">
                <button type="button" className="btn-primary" onClick={handleMarkTaken}>
                  ✓ {t('markTaken')}
                </button>
                <button type="button" className="btn-secondary" onClick={handleSnooze}>
                  {t('snooze30')}
                </button>
              </div>
            </>
          ) : (
            <p className="mt-5 text-sm text-cozy-quiet">{t('noNextDose')}</p>
          )}

          {snoozeUntil ? (
            <p className="mt-4 text-xs text-cozy-subtle">
              {t('snoozedUntil', { time: clockOf(snoozeUntil) })}
            </p>
          ) : null}
        </section>

        {/* adherence */}
        <section className="card lg:col-span-2">
          <h2 className="text-base font-medium text-cozy-white">{t('adherence')}</h2>
          <p className="mt-1 text-xs text-cozy-subtle">{t('adherenceHint')}</p>

          {showProgress ? (
            <>
              <p className="mt-6 text-sm font-medium text-cozy-white">
                {t('takenToday', { taken: takenCount, total })}
              </p>
              <div
                className="progress-track mt-3"
                role="progressbar"
                aria-valuemin={0}
                aria-valuemax={total}
                aria-valuenow={takenCount}
                aria-label={t('adherence')}
              >
                <div className="progress-bar" style={{ width: `${progressPercent}%` }} />
              </div>
              <p className="mt-4">
                {takenCount === total ? (
                  <span className="chip-ok">{t('allTaken')}</span>
                ) : (
                  <span className="chip">{t('takenToday', { taken: takenCount, total })}</span>
                )}
              </p>
            </>
          ) : (
            <p className="mt-6 text-sm text-cozy-quiet">
              {lastId != null ? t('noDosesToday') : t('progressEmpty')}
            </p>
          )}

          {lastId != null ? (
            <Link to={`/timetable/${lastId}`} className="btn-outlined btn-sm mt-6 inline-flex">
              {t('viewTimetable')} →
            </Link>
          ) : null}
        </section>
      </div>
    </div>
  )
}
