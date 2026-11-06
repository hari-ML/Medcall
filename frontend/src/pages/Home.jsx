import React, { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { createDemo, getReminders } from '../api'
import { useI18n } from '../i18n'
import { getLastPrescription, loadTaken, setLastPrescription, todayStr } from '../store'

function minutesOf(hhmm) {
  const [h, m] = String(hhmm || '0:0').split(':').map((n) => parseInt(n, 10))
  if (Number.isNaN(h)) return 24 * 60
  return h * 60 + (Number.isNaN(m) ? 0 : m)
}

function greetKeyForNow() {
  const hour = new Date().getHours()
  if (hour < 12) return 'greetingMorning'
  if (hour < 17) return 'greetingAfternoon'
  if (hour < 20) return 'greetingEvening'
  return 'greetingNight'
}

/** One dose key per (medicine, slot) — same convention as DoseCard/store.js. */
function doseKeysOf(reminders) {
  return reminders.map((reminder) => `${reminder.id}:${reminder.slot}`)
}

/**
 * Home dashboard: time-based greeting, the two big entry points
 * (Scan prescription / Try demo), the "next dose" card and today's
 * progress bar fed by localStorage "taken" marks.
 */
export default function Home() {
  const { t, lang } = useI18n()
  const navigate = useNavigate()

  const [lastId, setLastId] = useState(() => getLastPrescription())
  const [reminders, setReminders] = useState([])
  const [taken, setTaken] = useState({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  // today's reminders + taken marks for the last prescription
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
    if (lastId != null) setTaken(loadTaken(lastId))
  }, [lastId])

  const keys = useMemo(() => doseKeysOf(reminders), [reminders])
  const takenCount = keys.filter((key) => taken[key]).length
  const total = keys.length

  const nextDose = useMemo(() => {
    const now = new Date()
    const nowMinutes = now.getHours() * 60 + now.getMinutes()
    return (
      reminders
        .filter(
          (reminder) =>
            minutesOf(reminder.time) >= nowMinutes && !taken[`${reminder.id}:${reminder.slot}`],
        )
        .sort((a, b) => minutesOf(a.time) - minutesOf(b.time))[0] || null
    )
  }, [reminders, taken])

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

  const showProgress = lastId != null && total > 0
  const progressPercent = total ? Math.round((takenCount * 100) / total) : 0

  return (
    <div className="space-y-8">
      {/* hero: greeting + the two entry points */}
      <section className="rounded-card bg-brand-700 p-8 text-white shadow-md">
        <h1 className="text-3xl font-bold">{t(greetKeyForNow())}</h1>
        <p className="mt-2 text-lg text-brand-100">{t('tagline')}</p>
        <div className="mt-6 flex flex-wrap gap-4">
          <button
            type="button"
            className="btn bg-white text-brand-800 shadow-md hover:bg-brand-50 active:bg-brand-100"
            onClick={() => navigate('/upload')}
            disabled={busy}
          >
            📷 {t('scanPrescription')}
          </button>
          <button
            type="button"
            className="btn border-2 border-white text-white hover:bg-white/10 active:bg-white/20"
            onClick={handleDemo}
            disabled={busy}
          >
            {busy ? t('loading') : `⚡ ${t('tryDemo')}`}
          </button>
        </div>
        {error ? (
          <p className="mt-4 rounded-xl bg-white p-3 text-lg font-medium text-red-700">{error}</p>
        ) : null}
      </section>

      <div className="grid gap-6 md:grid-cols-2">
        {/* next dose */}
        <section className="card">
          <div className="text-sm font-semibold uppercase tracking-wide text-slate-500">
            {t('nextDose')}
          </div>
          {nextDose ? (
            <div className="mt-3">
              <div className="text-3xl font-bold text-brand-700">{nextDose.time}</div>
              <div className="mt-1 text-xl font-semibold text-slate-800">{nextDose.medicine}</div>
              <p className="mt-1 leading-relaxed text-slate-700">{nextDose.instruction}</p>
            </div>
          ) : (
            <p className="mt-3 text-lg text-slate-600">{t('noNextDose')}</p>
          )}
        </section>

        {/* today's progress */}
        <section className="card">
          <div className="text-lg font-semibold text-slate-700">
            {showProgress ? t('todayProgress', { taken: takenCount, total }) : t('progressEmpty')}
          </div>

          {showProgress ? (
            <>
              <div
                className="mt-4 h-4 w-full overflow-hidden rounded-full bg-slate-200"
                role="progressbar"
                aria-valuemin={0}
                aria-valuemax={total}
                aria-valuenow={takenCount}
              >
                <div
                  className="h-4 rounded-full bg-brand-600 transition-all duration-500"
                  style={{ width: `${progressPercent}%` }}
                />
              </div>
              <p className="mt-3">
                {takenCount === total ? (
                  <span className="chip-ok">{t('allTaken')}</span>
                ) : (
                  <span className="chip-teal">
                    {t('todayProgress', { taken: takenCount, total })}
                  </span>
                )}
              </p>
            </>
          ) : (
            <p className="mt-3 text-base text-slate-500">
              {lastId != null ? t('noMedicines') : ''}
            </p>
          )}

          {lastId != null ? (
            <Link to={`/timetable/${lastId}`} className="btn-secondary btn-sm mt-5 inline-flex">
              {t('viewTimetable')} →
            </Link>
          ) : null}
        </section>
      </div>
    </div>
  )
}
