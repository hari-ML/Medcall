import React, { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  errorMessage,
  getConsent,
  getHistory,
  getUpcoming,
  runReminders,
  sendTestReminder,
  setConsent,
} from '../api'
import { useAuth } from '../auth'
import { useI18n } from '../i18n'

/**
 * Reminders screen (Cozy design system): consent switches (default deny —
 * nothing is sent until the patient switches a channel on), the preferred
 * channel, real WhatsApp/SMS test sends, the upcoming occurrences and the
 * delivery history, plus a manual "check now" tick.
 *
 * SAFETY: this page only *displays* backend rows and asks the provider for a
 * test message. It never schedules a dose, never edits an item, and
 * unclear/as-needed lines have no occurrences to show because the engine
 * refuses to create them. A test send obeys the same consent gate and can
 * never pretend delivery.
 */

const CHANNELS = ['whatsapp', 'sms', 'voice']
const TEST_CHANNELS = ['whatsapp', 'sms']

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

const ACTION_KEY = {
  taken: 'actionTaken',
  snooze: 'actionSnooze',
  skip: 'actionSkip',
  help: 'actionHelp',
}

function statusChip(t, status) {
  const key = STATUS_KEY[status]
  const label = key ? t(key) : status
  if (status === 'sent') return <span className="chip-ok">{label}</span>
  if (status === 'pending') return <span className="chip-teal">{label}</span>
  if (status === 'blocked' || status === 'missed' || status === 'failed') {
    return <span className="chip-warn">{label}</span>
  }
  return <span className="chip">{label}</span>
}

function actionChip(t, action) {
  if (!action) return null
  const key = ACTION_KEY[action]
  return <span className="chip-teal">{key ? t(key) : action}</span>
}

function OccurrenceRow({ row, t }) {
  return (
    <li className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-cozy-border bg-cozy-input p-4">
      <div className="min-w-0">
        <div className="text-sm font-medium text-cozy-white">
          {row.local_time} · {row.medicine}
        </div>
        <div className="mt-1 text-xs text-cozy-subtle">{row.scheduled_at}</div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {row.patient_action ? actionChip(t, row.patient_action) : null}
        <span className="chip">{row.channel}</span>
        {statusChip(t, row.status)}
      </div>
    </li>
  )
}

export default function Reminders() {
  const { t } = useI18n()
  const { patient } = useAuth()
  const [consent, setConsentState] = useState({})
  const [upcoming, setUpcoming] = useState([])
  const [history, setHistory] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [runResult, setRunResult] = useState(null)
  const [testBusy, setTestBusy] = useState('')
  const [testResult, setTestResult] = useState(null) // {kind, channel}

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

  async function handleTest(channel) {
    setTestBusy(channel)
    setTestResult(null)
    setError(null)
    try {
      await sendTestReminder(channel)
      setTestResult({ kind: 'sent', channel })
    } catch (err) {
      if (err?.status === 403) setTestResult({ kind: 'consent', channel })
      else setTestResult({ kind: 'failed', channel })
    } finally {
      setTestBusy('')
    }
  }

  const preferred = patient?.preferred_channel || ''

  return (
    <div className="space-y-8">
      <header>
        <h1 className="text-lg font-medium leading-tight text-cozy-white">{t('remindersTitle')}</h1>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-cozy-quiet">
          {t('remindersIntro')}
        </p>
        <p className="mt-3 text-xs text-cozy-subtle">{t('dispatchHint')}</p>
      </header>

      {error ? (
        <div role="alert" className="alert-error text-sm">
          {error}
        </div>
      ) : null}

      {/* consent — default deny */}
      <section className="card">
        <h2 className="text-base font-medium text-cozy-white">{t('consentTitle')}</h2>
        <p className="mt-1 text-sm text-cozy-quiet">{t('consentIntro')}</p>

        {preferred ? (
          <p className="mt-3 text-xs text-cozy-subtle">
            {t('preferredChannel')}: {t(CHANNEL_LABEL_KEY[preferred] || 'channelWhatsapp')}
          </p>
        ) : null}

        <ul className="mt-4 space-y-3">
          {CHANNELS.map((channel) => (
            <li
              key={channel}
              className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-cozy-border bg-cozy-input p-4"
            >
              <span className="text-sm font-medium text-cozy-white">
                {t(CHANNEL_LABEL_KEY[channel])}
              </span>
              <button
                type="button"
                role="switch"
                aria-checked={Boolean(consent[channel])}
                aria-label={t(CHANNEL_LABEL_KEY[channel])}
                onClick={() => handleToggle(channel, !consent[channel])}
                className={consent[channel] ? 'switch-on' : 'switch'}
              >
                {consent[channel] ? `✓ ${t('consentOn')}` : t('consentOff')}
              </button>
            </li>
          ))}
        </ul>

        {/* real test send — never fabricates success */}
        <div className="mt-5 border-t border-cozy-border pt-5">
          <p className="text-xs text-cozy-subtle">{t('testConsentHint')}</p>
          <div className="mt-3 flex flex-wrap gap-3">
            {TEST_CHANNELS.map((channel) => (
              <button
                key={channel}
                type="button"
                className="btn-outlined btn-sm"
                onClick={() => handleTest(channel)}
                disabled={!consent[channel] || Boolean(testBusy)}
              >
                {testBusy === channel
                  ? t('testSending')
                  : `${t('testSend')} · ${t(CHANNEL_LABEL_KEY[channel])}`}
              </button>
            ))}
          </div>
          {testResult ? (
            <p
              role="status"
              className={`mt-3 text-xs ${
                testResult.kind === 'sent' ? 'text-cozy-white' : 'text-cozy-quiet'
              }`}
            >
              {testResult.kind === 'sent'
                ? t('testSent', {
                    channel: t(CHANNEL_LABEL_KEY[testResult.channel]),
                  })
                : testResult.kind === 'consent'
                  ? t('testConsentHint')
                  : t('testFailed')}
            </p>
          ) : null}
        </div>

        <div className="mt-5 space-y-1 border-t border-cozy-border pt-5 text-xs text-cozy-subtle">
          <p>{t('whatsappButtonsHint')}</p>
          <p>{t('smsKeywordsHint')}</p>
        </div>
      </section>

      {/* upcoming */}
      <section className="card">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-base font-medium text-cozy-white">{t('upcomingTitle')}</h2>
          <button type="button" className="btn-secondary btn-sm" onClick={handleRun} disabled={busy}>
            {busy ? t('loading') : t('runNow')}
          </button>
        </div>
        {runResult ? (
          <p className="mt-3 rounded-md border border-cozy-border bg-cozy-input p-3 text-xs text-cozy-quiet">
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
          <p className="mt-4 text-sm text-cozy-quiet" role="status">
            {t('loading')}
          </p>
        ) : upcoming.length === 0 ? (
          <p className="mt-4 text-sm text-cozy-quiet">
            {t('remEmpty')}{' '}
            <Link to="/upload" className="link">
              {t('scanPrescription')}
            </Link>
          </p>
        ) : (
          <ul className="mt-4 space-y-3">
            {upcoming.map((row) => (
              <OccurrenceRow key={row.id} row={row} t={t} />
            ))}
          </ul>
        )}
      </section>

      {/* history */}
      <section className="card">
        <h2 className="text-base font-medium text-cozy-white">{t('historyTitle')}</h2>
        {loading ? (
          <p className="mt-4 text-sm text-cozy-quiet" role="status">
            {t('loading')}
          </p>
        ) : history.length === 0 ? (
          <p className="mt-4 text-sm text-cozy-quiet">{t('historyEmpty')}</p>
        ) : (
          <ul className="mt-4 space-y-3">
            {history.slice(0, 30).map((row) => (
              <OccurrenceRow key={row.id} row={row} t={t} />
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
