import React, { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { confirmItem, editItem, getPrescription, UPLOADS_BASE } from '../api'
import MedicineLine from '../components/MedicineLine'
import { useI18n } from '../i18n'

/** Backend image_url is normally '/uploads/...' (proxied); tolerate bare names. */
function resolveImageUrl(url) {
  if (!url) return null
  return url.startsWith('/') ? url : `${UPLOADS_BASE}/${url}`
}

/**
 * Review screen (Cozy design system): the original prescription next to every
 * extracted line so the user can verify them. Unclear lines carry the warning
 * + confirm/edit actions (via MedicineLine). "Generate schedule" is blocked
 * while lines are pending UNLESS the user explicitly chooses "schedule only
 * confirmed items" — MedRecall never guesses either way (the backend excludes
 * unclear items from schedule/PDF/reminders regardless).
 */
export default function Review() {
  const { id } = useParams()
  const pid = Number(id)
  const navigate = useNavigate()
  const { t } = useI18n()

  const [prescription, setPrescription] = useState(null)
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [onlyConfirmed, setOnlyConfirmed] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await getPrescription(pid)
      setPrescription(data)
      setItems(data.items || [])
    } catch (err) {
      setError(err?.message || t('errorGeneric'))
    } finally {
      setLoading(false)
    }
  }, [pid, t])

  useEffect(() => {
    if (Number.isFinite(pid)) load()
    else setError('404')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pid])

  function replaceItem(updated) {
    setItems((previous) => previous.map((item) => (item.id === updated.id ? updated : item)))
  }

  /** Confirm button callback for MedicineLine (errors surfaced here). */
  async function handleConfirm(item) {
    try {
      replaceItem(await confirmItem(pid, item.id))
      return undefined
    } catch (err) {
      setError(err?.message || t('errorGeneric'))
      return false
    }
  }

  /** Edit callback: return updated item, or false so the form stays open. */
  async function handleEdit(item, fields) {
    try {
      const updated = await editItem(pid, item.id, fields)
      replaceItem(updated)
      return updated
    } catch (err) {
      setError(err?.message || t('errorGeneric'))
      return false
    }
  }

  const pending = items.filter((item) => item.status === 'unclear').length
  const ready = items.length - pending
  const canGenerate = items.length > 0 && (pending === 0 || onlyConfirmed)

  if (loading) {
    return (
      <p className="py-16 text-center text-sm text-cozy-quiet" role="status">
        {t('loading')}
      </p>
    )
  }

  if (error && !prescription) {
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

  return (
    <div className="space-y-6">
      <header>
        <Link to="/" className="btn-quiet btn-sm inline-flex">
          ← {t('back')}
        </Link>
        <h1 className="mt-5 text-lg font-medium leading-tight text-cozy-white">
          {t('reviewTitle')}
        </h1>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-cozy-quiet">
          {t('reviewSubtitle')}
        </p>
        <div className="mt-4 flex flex-wrap gap-2">
          <span className="chip-ok">✓ {t('linesReady', { n: ready })}</span>
          {pending > 0 ? (
            <span className="chip-warn">! {t('linesPending', { n: pending })}</span>
          ) : null}
        </div>
      </header>

      {error ? (
        <div role="alert" className="alert-error text-sm">
          {error}
        </div>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-2">
        {/* original image — the reference for verification */}
        <section className="lg:sticky lg:top-24 lg:self-start">
          <h2 className="mb-3 text-base font-medium text-cozy-white">{t('originalImage')}</h2>
          {resolveImageUrl(prescription?.image_url) ? (
            <img
              src={resolveImageUrl(prescription.image_url)}
              alt={t('originalImage')}
              className="w-full rounded-lg border border-cozy-border bg-cozy-card shadow-md"
            />
          ) : null}
        </section>

        {/* extracted lines */}
        <section>
          <h2 className="mb-3 text-base font-medium text-cozy-white">{t('extractedLines')}</h2>
          <div className="space-y-5">
            {items.map((item) => (
              <MedicineLine
                key={item.id}
                item={item}
                onConfirm={handleConfirm}
                onEdit={handleEdit}
              />
            ))}
            {items.length === 0 ? (
              <p className="card text-sm text-cozy-quiet">{t('noMedicines')}</p>
            ) : null}
          </div>
        </section>
      </div>

      {/* generate action */}
      <section className="card">
        {pending > 0 ? (
          <label className="mb-4 flex cursor-pointer items-start gap-3 text-sm text-cozy-quiet">
            <input
              type="checkbox"
              className="mt-1 h-5 w-5 accent-cozy-white"
              checked={onlyConfirmed}
              onChange={(event) => setOnlyConfirmed(event.target.checked)}
            />
            <span>{t('scheduleOnlyConfirmed')}</span>
          </label>
        ) : null}

        {!canGenerate ? (
          <p className="mb-4 rounded-md border border-cozy-white bg-cozy-card p-4 text-sm font-medium text-cozy-white">
            ! {t('resolveFirst')}
          </p>
        ) : null}

        <button
          type="button"
          className={canGenerate ? 'btn-primary' : 'btn-disabled'}
          disabled={!canGenerate}
          onClick={() => navigate(`/language/${pid}`)}
        >
          {t('generateSchedule')} →
        </button>
      </section>
    </div>
  )
}
