import React, { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  enrollReminders,
  getReminders,
  getSchedule,
  timetablePdfUrl,
  unenrollReminders,
} from '../api'
import DoseCard from '../components/DoseCard'
import WarningCard from '../components/WarningCard'
import { SLOT_ORDER, useI18n } from '../i18n'
import {
  permissionState,
  remindersActive,
  requestPermission,
  startReminders,
} from '../reminders'
import { loadTaken, toggleTaken } from '../store'

/**
 * Timetable screen: the four-slot daily schedule (translated by the backend
 * in the selected language), the as-needed list, the excluded-lines warning
 * (safety: unclear lines are never scheduled), "Mark as taken" toggles,
 * browser reminders and the printable PDF.
 *
 * The schedule is refetched whenever the language changes, so the timetable,
 * reminders and PDF always match the selected language.
 */
export default function Timetable() {
  const { id } = useParams()
  const pid = Number(id)
  const { t, lang, localizeReason } = useI18n()

  const [schedule, setSchedule] = useState(null)
  const [reminders, setReminders] = useState([])
  const [taken, setTaken] = useState({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [permission, setPermission] = useState(() => permissionState())
  const [active, setActive] = useState(() => remindersActive())
  const [enrollment, setEnrollment] = useState(null)
  const [enrollBusy, setEnrollBusy] = useState(false)
  const [enrollError, setEnrollError] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [scheduleData, reminderData] = await Promise.all([
        getSchedule(pid, lang),
        getReminders(pid, lang),
      ])
      setSchedule(scheduleData)
      setReminders(reminderData)
      setTaken(loadTaken(pid))
      // language switched while reminders were running → restart in new language
      if (remindersActive()) {
        startReminders(reminderData, { lang })
        setActive(true)
      }
    } catch (err) {
      setError(err?.message || t('errorGeneric'))
    } finally {
      setLoading(false)
    }
  }, [pid, lang, t])

  useEffect(() => {
    if (Number.isFinite(pid)) load()
    else setError('404')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pid])

  function handleToggle(key) {
    setTaken({ ...toggleTaken(pid, key) })
  }

  async function handleEnableReminders() {
    const result = await requestPermission()
    setPermission(result)
    if (result === 'granted') {
      startReminders(reminders, { lang })
      setActive(true)
    }
  }

  function handlePrint() {
    window.open(timetablePdfUrl(pid, lang), '_blank', 'noopener')
  }

  // Server-side reminder engine (Phase 3): one schedule per verified fixed
  // slot. The backend skips unclear/as-needed lines by itself — whatever it
  // returns in `skipped` is shown with its reason, never silently dropped.
  async function handleEnroll() {
    setEnrollBusy(true)
    setEnrollError(null)
    try {
      setEnrollment(await enrollReminders(pid))
    } catch (err) {
      setEnrollError(err?.message || t('errorGeneric'))
    } finally {
      setEnrollBusy(false)
    }
  }

  async function handleUnenroll() {
    setEnrollBusy(true)
    setEnrollError(null)
    try {
      await unenrollReminders(pid)
      setEnrollment(null)
    } catch (err) {
      setEnrollError(err?.message || t('errorGeneric'))
    } finally {
      setEnrollBusy(false)
    }
  }

  if (loading) {
    return (
      <p className="py-16 text-center text-xl text-slate-500" role="status">
        {t('loading')}
      </p>
    )
  }

  if (error && !schedule) {
    return (
      <div className="mx-auto max-w-xl space-y-4 text-center">
        <div role="alert" className="rounded-card border-2 border-red-300 bg-red-50 p-5 text-lg text-red-800">
          {error === '404' ? t('errorGeneric') : error}
        </div>
        <div className="flex justify-center gap-3">
          <button type="button" className="btn-secondary" onClick={load}>
            {t('retry')}
          </button>
          <Link to="/" className="btn-quiet">
            {t('home')}
          </Link>
        </div>
      </div>
    )
  }

  const placedCount = SLOT_ORDER.reduce(
    (count, slot) => count + (schedule?.slots?.[slot]?.length || 0),
    0,
  ) + (schedule?.as_needed?.length || 0)
  const excluded = schedule?.excluded || []

  return (
    <div className="space-y-8">
      {/* header + actions */}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <Link to={`/review/${Number.isFinite(pid) ? pid : ''}`} className="btn-quiet btn-sm inline-flex">
            ← {t('back')}
          </Link>
          <h1 className="mt-4 text-3xl font-bold text-slate-800">
            {schedule.title || t('ttTitle')}
          </h1>
          <p className="mt-1 text-lg text-slate-600">{t('ttSubtitle', { date: schedule.date })}</p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <button type="button" className="btn-primary" onClick={handlePrint}>
            🖨 {t('printTimetable')}
          </button>

          {permission === 'unsupported' ? (
            <button type="button" className="btn-disabled" disabled>
              🔔 {t('remindersUnsupported')}
            </button>
          ) : permission === 'denied' ? (
            <button type="button" className="btn-disabled" disabled>
              🔔 {t('remindersBlocked')}
            </button>
          ) : active ? (
            <span className="chip-ok">🔔 {t('remindersOn')}</span>
          ) : (
            <button type="button" className="btn-secondary" onClick={handleEnableReminders}>
              🔔 {t('enableReminders')}
            </button>
          )}

          <Link to={`/language/${Number.isFinite(pid) ? pid : ''}`} className="btn-quiet btn-sm">
            🌐 {t('changeLanguage')}
          </Link>
        </div>
      </div>

      {error ? (
        <div role="alert" className="rounded-card border-2 border-red-300 bg-red-50 p-4 text-lg text-red-800">
          {error}
        </div>
      ) : null}

      {/* server-side dose reminders (WhatsApp / SMS / voice, consent-gated) */}
      <section className="card">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-xl font-bold text-slate-800">📲 {t('serverRemindersTitle')}</h2>
            <p className="mt-1 text-slate-600">{t('serverRemindersHint')}</p>
          </div>
          <div className="flex flex-wrap gap-3">
            {enrollment ? (
              <button
                type="button"
                className="btn-danger-soft"
                onClick={handleUnenroll}
                disabled={enrollBusy}
              >
                {enrollBusy ? t('loading') : t('stopReminders')}
              </button>
            ) : (
              <button
                type="button"
                className="btn-primary"
                onClick={handleEnroll}
                disabled={enrollBusy}
              >
                {enrollBusy ? t('loading') : `📲 ${t('sendReminders')}`}
              </button>
            )}
            <Link to="/reminders" className="btn-secondary">
              {t('openReminders')}
            </Link>
          </div>
        </div>

        {enrollError ? (
          <div role="alert" className="mt-3 rounded-xl border-2 border-red-300 bg-red-50 p-3 text-red-800">
            {enrollError}
          </div>
        ) : null}

        {enrollment ? (
          <div className="mt-4 space-y-3">
            <p className="chip-ok">
              {enrollment.scheduled_doses > 0
                ? t('enrollScheduled', { n: enrollment.scheduled_doses })
                : t('enrollNone')}
            </p>
            {enrollment.skipped?.length ? (
              <div>
                <p className="font-semibold text-amber-900">
                  {t('enrollSkipped', { n: enrollment.skipped.length })}
                </p>
                <ul className="mt-2 space-y-2">
                  {enrollment.skipped.map((row) => (
                    <li key={row.item_id} className="rounded-xl bg-amber-50 p-3 text-amber-900">
                      <span className="font-semibold">{row.medicine}</span> —{' '}
                      {localizeReason(row.reason)}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>
        ) : null}
      </section>

      {/* SAFETY: excluded (unclear) lines — shown, never scheduled */}
      {excluded.length > 0 ? (
        <WarningCard title={t('excludedWarning')} body={t('excludedHint')}>
          <p className="mt-3 font-semibold text-amber-900">
            {t('excludedCount', { n: excluded.length })}
          </p>
          <ul className="mt-2 space-y-2">
            {excluded.map((entry) => (
              <li key={entry.id} className="rounded-xl bg-white p-3 shadow-sm">
                <div className="font-semibold text-slate-800">{entry.medicine}</div>
                <div className="text-lg font-medium text-amber-800">
                  {localizeReason(entry.reason)}
                </div>
                {entry.source_text ? (
                  <div className="text-base text-slate-500">“{entry.source_text}”</div>
                ) : null}
              </li>
            ))}
          </ul>
          <Link to={`/review/${Number.isFinite(pid) ? pid : ''}`} className="btn-secondary btn-sm mt-4 inline-flex">
            ✏️ {t('backToReview')}
          </Link>
        </WarningCard>
      ) : null}

      {/* four fixed slots */}
      {placedCount > 0 ? (
        <div className="grid gap-6 sm:grid-cols-2">
          {SLOT_ORDER.map((slot) => (
            <DoseCard
              key={slot}
              slot={slot}
              time={schedule.slot_times?.[slot]}
              entries={schedule.slots?.[slot] || []}
              taken={taken}
              onToggle={handleToggle}
              emptyNote={schedule.empty_slot_note}
            />
          ))}
        </div>
      ) : (
        <section className="card text-center text-lg text-slate-600">{t('noMedicines')}</section>
      )}

      {/* as-needed (SOS/PRN): no fixed time, no reminder */}
      {schedule.as_needed?.length ? (
        <section className="card">
          <h2 className="text-xl font-bold text-slate-800">{schedule.as_needed_heading}</h2>
          <ul className="mt-4 space-y-3">
            {schedule.as_needed.map((entry) => (
              <li key={entry.id} className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                <div className="text-lg font-bold text-slate-800">{entry.medicine}</div>
                <p className="mt-1 leading-relaxed text-slate-700">{entry.instruction}</p>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  )
}
