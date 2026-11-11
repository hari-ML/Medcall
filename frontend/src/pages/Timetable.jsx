import React, { useCallback, useEffect, useMemo, useState } from 'react'
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
 * Timetable screen (Cozy design system): the four-slot daily schedule
 * (translated by the backend in the selected language), a live search over
 * medicine names and times, the as-needed list, the excluded-lines warning
 * (safety: unclear lines are never scheduled), "Mark as taken" toggles,
 * server + browser reminders and the printable PDF.
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
  const [query, setQuery] = useState('')

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

  const normalizedQuery = query.trim().toLowerCase()

  /** Match a medicine line by name, instruction text or any time it carries. */
  const matches = useCallback(
    (entry) => {
      if (!normalizedQuery) return true
      return [entry.medicine, entry.instruction, entry.time, entry.slot]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(normalizedQuery))
    },
    [normalizedQuery],
  )

  const filteredSlots = useMemo(() => {
    const out = {}
    for (const slot of SLOT_ORDER) {
      out[slot] = (schedule?.slots?.[slot] || []).filter(matches)
    }
    return out
  }, [schedule, matches])

  const filteredAsNeeded = useMemo(
    () => (schedule?.as_needed || []).filter(matches),
    [schedule, matches],
  )

  if (loading) {
    return (
      <p className="py-16 text-center text-sm text-cozy-quiet" role="status">
        {t('loading')}
      </p>
    )
  }

  if (error && !schedule) {
    return (
      <div className="mx-auto max-w-xl space-y-4 text-center">
        <div role="alert" className="alert-error text-sm">
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
  const visibleCount = SLOT_ORDER.reduce(
    (count, slot) => count + filteredSlots[slot].length,
    0,
  ) + filteredAsNeeded.length
  const excluded = schedule?.excluded || []

  return (
    <div className="space-y-8">
      {/* header + actions */}
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <Link to={`/review/${Number.isFinite(pid) ? pid : ''}`} className="btn-quiet btn-sm inline-flex">
            ← {t('back')}
          </Link>
          <h1 className="mt-5 text-lg font-medium leading-tight text-cozy-white">
            {schedule.title || t('ttTitle')}
          </h1>
          <p className="mt-1 text-sm text-cozy-quiet">{t('ttSubtitle', { date: schedule.date })}</p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <button type="button" className="btn-primary" onClick={handlePrint}>
            {t('printTimetable')}
          </button>

          {permission === 'unsupported' ? (
            <button type="button" className="btn-disabled" disabled>
              {t('remindersUnsupported')}
            </button>
          ) : permission === 'denied' ? (
            <button type="button" className="btn-disabled" disabled>
              {t('remindersBlocked')}
            </button>
          ) : active ? (
            <span className="chip-ok">{t('remindersOn')}</span>
          ) : (
            <button type="button" className="btn-secondary" onClick={handleEnableReminders}>
              {t('enableReminders')}
            </button>
          )}

          <Link to={`/language/${Number.isFinite(pid) ? pid : ''}`} className="btn-quiet btn-sm">
            {t('changeLanguage')}
          </Link>
        </div>
      </header>

      {error ? (
        <div role="alert" className="alert-error text-sm">
          {error}
        </div>
      ) : null}

      {/* search — #262626 input, radius 11px, name or time */}
      <div>
        <label className="label" htmlFor="tt-search">
          {t('searchLabel')}
        </label>
        <div className="relative">
          <input
            id="tt-search"
            type="search"
            className="input pr-12"
            value={query}
            placeholder={t('searchPlaceholder')}
            onChange={(event) => setQuery(event.target.value)}
            autoComplete="off"
          />
          {query ? (
            <button
              type="button"
              className="absolute inset-y-0 right-0 flex items-center px-4 text-cozy-quiet transition-colors duration-fast ease-cozy hover:text-cozy-white"
              onClick={() => setQuery('')}
              aria-label={t('clearSearch')}
            >
              ✕
            </button>
          ) : null}
        </div>
      </div>

      {/* server-side dose reminders (WhatsApp / SMS / voice, consent-gated) */}
      <section className="card">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-base font-medium text-cozy-white">{t('serverRemindersTitle')}</h2>
            <p className="mt-1 text-sm text-cozy-quiet">{t('serverRemindersHint')}</p>
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
                {enrollBusy ? t('loading') : t('sendReminders')}
              </button>
            )}
            <Link to="/reminders" className="btn-secondary">
              {t('openReminders')}
            </Link>
          </div>
        </div>

        {enrollError ? (
          <div role="alert" className="alert-error mt-4 text-sm">
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
                <p className="text-sm font-medium text-cozy-white">
                  {t('enrollSkipped', { n: enrollment.skipped.length })}
                </p>
                <ul className="mt-2 space-y-2">
                  {enrollment.skipped.map((row) => (
                    <li
                      key={row.item_id}
                      className="rounded-md border border-cozy-border bg-cozy-input p-3 text-xs text-cozy-quiet"
                    >
                      <span className="font-medium text-cozy-white">{row.medicine}</span> —{' '}
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
          <p className="mt-3 text-sm font-medium text-cozy-white">
            {t('excludedCount', { n: excluded.length })}
          </p>
          <ul className="mt-2 space-y-2">
            {excluded.map((entry) => (
              <li key={entry.id} className="rounded-md border border-cozy-border bg-cozy-input p-3">
                <div className="text-sm font-medium text-cozy-white">{entry.medicine}</div>
                <div className="mt-1 text-xs text-cozy-quiet">{localizeReason(entry.reason)}</div>
                {entry.source_text ? (
                  <div className="mt-1 text-xs text-cozy-subtle">“{entry.source_text}”</div>
                ) : null}
              </li>
            ))}
          </ul>
          <Link
            to={`/review/${Number.isFinite(pid) ? pid : ''}`}
            className="btn-secondary btn-sm mt-4 inline-flex"
          >
            {t('backToReview')}
          </Link>
        </WarningCard>
      ) : null}

      {/* no search results */}
      {normalizedQuery && visibleCount === 0 ? (
        <section className="card text-center">
          <p className="text-sm text-cozy-quiet">{t('noMatchingMedicines')}</p>
          <button type="button" className="btn-outlined btn-sm mt-4" onClick={() => setQuery('')}>
            {t('clearSearch')}
          </button>
        </section>
      ) : null}

      {/* four fixed slots */}
      {placedCount > 0 && visibleCount > 0 ? (
        <div className="grid gap-6 sm:grid-cols-2">
          {SLOT_ORDER.map((slot) => {
            const entries = filteredSlots[slot]
            if (normalizedQuery && entries.length === 0) return null
            return (
              <DoseCard
                key={slot}
                slot={slot}
                time={schedule.slot_times?.[slot]}
                entries={entries}
                taken={taken}
                onToggle={handleToggle}
                emptyNote={schedule.empty_slot_note}
              />
            )
          })}
        </div>
      ) : null}

      {placedCount === 0 ? (
        <section className="card text-center text-sm text-cozy-quiet">{t('noMedicines')}</section>
      ) : null}

      {/* as-needed (SOS/PRN): no fixed time, no reminder */}
      {filteredAsNeeded.length ? (
        <section className="card">
          <h2 className="text-base font-medium text-cozy-white">{schedule.as_needed_heading}</h2>
          <ul className="mt-4 space-y-3">
            {filteredAsNeeded.map((entry) => (
              <li key={entry.id} className="rounded-md border border-cozy-border bg-cozy-input p-4">
                <div className="text-sm font-medium text-cozy-white">{entry.medicine}</div>
                <p className="mt-1 text-sm leading-relaxed text-cozy-quiet">{entry.instruction}</p>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  )
}
