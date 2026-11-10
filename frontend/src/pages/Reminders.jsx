import React, { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { errorMessage, getConsent, getHistory, getUpcoming, runReminders, setConsent } from '../api'
import { useI18n } from '../i18n'

/**
 * Reminders screen (Phase 7): consent switches (default deny — nothing is
 * sent until the patient switches a channel on), the upcoming occurrences
 * and the delivery history, plus a manual "check now" tick.
 *
 * SAFETY: this page only *displays* backend rows. It never schedules a dose,
 * never edits an item, and unclear/as-needed lines have no occurrences to
 * show because the engine refuses to create them.
 */

const CHANNELS = ['whatsapp', 'sms', 'voice']

const CHANNEL_LABEL_KEY = {
  whatsapp: 'consentWhatsapp',
  sms: 'consentSms',
  voice: 'consentVoice',
}

// backend occurrence status -> i18n key (unknown statuses pass through)
const STATUS_KEY = {
  pending: 'remPending',
  sent: 'remSent',
  blocked: 'remBlocked',
  failed: 'remFailed',
  missed: 'remMissed',
  cancelled: 'remCancelled',
}

function statusChip(t, status) {
  const key = STATUS_KEY[status]
  const label = key ? t(key) : status
  if (status === 'sent') return <span className="chip-ok">{label}</span>
  if (status === 'pending') return <span className="chip-teal">{label}</span>
  if (status === 'blocked' || status === 'missed') return <span className="chip-warn">{label}</span>
  if (status === 'failed') return <span className="chip-warn">⚠ {label}</span>
  return <span className="chip">{label}</span>
}

export default function Reminders() {
  const { t } = useI18n()
  const [consent, setConsentState] = useState({})
  const [upcoming, setUpcoming] = useState([])
  const [history, setHistory] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [runResult, setRunResult] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [consentRows, upcomingRows, historyRows] = await Promise.all([
        getConsent(),
        getUpcoming(7),
        getHistory(),
      ])
      const map = {}
      ;(consentRows || []).forEach((row) => {
        map[row.channel] = Boolean(row.granted)
      })
      setConsentState(map)
      setUpcoming(upcomingRows || [])
      setHistory(historyRows || [])
    } catch (err) {
      setError(errorMessage(err) || t('errorGeneric'))
    } finally {
      setLoading(false)
    }
  }, [t])

  useEffect(() => {
    load()
  }, [load])

  async function handleToggle(channel, granted) {
    setError(null)
    setConsentState((prev) => ({ ...prev, [channel]: granted }))
    try {
      await setConsent(channel, granted)
      await load()
    } catch (err) {
      setError(errorMessage(err) || t('errorGeneric'))
      await load() // revert to the server's truth
    }
  }

  async function handleRun() {
    setBusy(true)
    setError(null)
    try {
      const result = await runReminders()
      setRunResult(result)
      await load()
    } catch (err) {
      setError(errorMessage(err) || t('errorGeneric'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold text-slate-800">{t('remindersTitle')}</h1>
        <p className="mt-2 text-lg text-slate-600">{t('remindersIntro')}</p>
      </div>

      {error ? (
        <div role="alert" className="rounded-card border-2 border-red-300 bg-red-50 p-4 text-red-800">
          {error}
        </div>
      ) : null}

      {/* consent — default deny */}
      <section className="card">
        <h2 className="text-xl font-bold text-slate-800">{t('consentTitle')}</h2>
        <p className="mt-1 text-slate-600">{t('consentIntro')}</p>
        <ul className="mt-4 space-y-3">
          {CHANNELS.map((channel) => (
            <li
              key={channel}
              className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-slate-50 p-4"
            >
              <span className="text-lg font-semibold text-slate-800">
                {t(CHANNEL_LABEL_KEY[channel])}
              </span>
              <button
                type="button"
                role="switch"
                aria-checked={Boolean(consent[channel])}
                aria-label={t(CHANNEL_LABEL_KEY[channel])}
                onClick={() => handleToggle(channel, !consent[channel])}
                className={consent[channel] ? 'chip-ok' : 'chip'}
              >
                {consent[channel] ? `✓ ${t('consentOn')}` : t('consentOff')}
              </button>
            </li>
          ))}
        </ul>
      </section>

      {/* upcoming */}
      <section className="card">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-xl font-bold text-slate-800">{t('upcomingTitle')}</h2>
          <button type="button" className="btn-secondary btn-sm" onClick={handleRun} disabled={busy}>
            {busy ? t('loading') : `↻ ${t('runNow')}`}
          </button>
        </div>
        {runResult ? (
          <p className="mt-3 rounded-xl bg-slate-50 p-3 text-base text-slate-600">
            {t('runSummary', {
              generated: runResult.generated,
              sent: runResult.sent,
              blocked: runResult.blocked,
              failed: runResult.failed,
              missed: runResult.missed,
            })}
          </p>
        ) : null}
        {loading ? (
          <p className="mt-4 text-slate-500" role="status">
            {t('loading')}
          </p>
        ) : upcoming.length === 0 ? (
          <p className="mt-4 text-slate-600">
            {t('remEmpty')}{' '}
            <Link to="/upload" className="font-semibold text-brand-700 underline">
              {t('scanPrescription')}
            </Link>
          </p>
        ) : (
          <ul className="mt-4 space-y-3">
            {upcoming.map((row) => (
              <li
                key={row.id}
                className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-slate-50 p-4"
              >
                <div>
                  <div className="text-lg font-bold text-slate-800">
                    {row.local_time} · {row.medicine}
                  </div>
                  <div className="text-base text-slate-500">{row.scheduled_at}</div>
                </div>
                <div className="flex items-center gap-2">
                  <span className="chip">{row.channel}</span>
                  {statusChip(t, row.status)}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* history */}
      <section className="card">
        <h2 className="text-xl font-bold text-slate-800">{t('historyTitle')}</h2>
        {loading ? (
          <p className="mt-4 text-slate-500" role="status">
            {t('loading')}
          </p>
        ) : history.length === 0 ? (
          <p className="mt-4 text-slate-600">{t('historyEmpty')}</p>
        ) : (
          <ul className="mt-4 space-y-3">
            {history.slice(0, 30).map((row) => (
              <li
                key={row.id}
                className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white p-4"
              >
                <div>
                  <div className="font-semibold text-slate-800">
                    {row.local_time} · {row.medicine}
                  </div>
                  <div className="text-base text-slate-500">{row.scheduled_at}</div>
                </div>
                <div className="flex items-center gap-2">
                  <span className="chip">{row.channel}</span>
                  {statusChip(t, row.status)}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
