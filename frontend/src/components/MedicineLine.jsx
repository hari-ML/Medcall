import React, { useState } from 'react'
import WarningCard from './WarningCard'
import { useI18n } from '../i18n'

const STATUS_CLASSES = {
  clear: 'chip-ok',
  confirmed: 'chip-teal',
  edited: 'chip-teal',
  unclear: 'chip-warn',
}

const FOOD_LABEL_KEYS = {
  before: 'foodBefore',
  after: 'foodAfter',
  with: 'foodWith',
  empty_stomach: 'foodEmpty',
}

const FORM_OPTIONS = ['', 'tab', 'cap', 'syrup', 'inj', 'drop', 'cream', 'ointment']
const FOOD_OPTIONS = [
  { value: '', key: 'foodUnspecified' },
  { value: 'before', key: 'foodBefore' },
  { value: 'after', key: 'foodAfter' },
  { value: 'with', key: 'foodWith' },
  { value: 'empty_stomach', key: 'foodEmpty' },
]

//: OCR confidence below this is highlighted for human review (0-100 scale).
const LOW_CONFIDENCE = 80

function statusLabel(t, status) {
  const map = {
    clear: t('statusClear'),
    unclear: t('statusUnclear'),
    confirmed: t('statusConfirmed'),
    edited: t('statusEdited'),
  }
  return map[status] || status
}

function blankDraft(item) {
  return {
    medicine_name: item.medicine || '',
    strength: item.strength || '',
    form: item.form || '',
    frequency: item.frequency || '',
    food_timing: item.food_timing || '',
    duration_days: item.duration_days ?? '',
  }
}

/**
 * One extracted prescription line on the Review screen.
 *
 * Safety behaviour (the heart of the app):
 *  - status `unclear` → warning with the exact reason + "We won't guess",
 *    buttons: Confirm / Edit manually / Ask pharmacist. It is clearly marked
 *    "Not added to timetable yet".
 *  - Confirm  → onConfirm(item)  (backend sets status `confirmed`)
 *  - Edit     → onEdit(item, fields) (backend re-parses/re-gates → `edited`
 *               if complete, stays `unclear` if still incomplete)
 *  Both callbacks return the updated item, or `false` to signal failure
 *  (the form stays open so no input is lost).
 *
 * A confidence below 80 is highlighted even for clear lines — the number is
 * informational only and never changes a status (the gate owns that).
 */
export default function MedicineLine({ item, onConfirm, onEdit, busy = false }) {
  const { t, localizeReason } = useI18n()
  const [draft, setDraft] = useState(null) // null = edit form closed
  const [copied, setCopied] = useState(false)
  const [localBusy, setLocalBusy] = useState(false)

  const isUnclear = item.status === 'unclear'
  const isLowConfidence = item.confidence != null && item.confidence < LOW_CONFIDENCE
  const disabled = busy || localBusy
  const lineLabel = t('line', { n: item.line_number ?? '?' })

  const summary = []
  if (item.strength) summary.push(item.strength)
  if (item.form) summary.push(item.form)
  if (item.frequency) summary.push(item.frequency)
  if (item.food_timing) summary.push(t(FOOD_LABEL_KEYS[item.food_timing] || 'foodUnspecified'))
  if (item.duration_days) summary.push(`${item.duration_days} d`)

  function pharmacistMessage() {
    return [
      'MedRecall could not confidently read this prescription line:',
      `"${item.source_text}"`,
      `Reason: ${localizeReason(item.reason)}`,
      'Please confirm the medicine, the dose and how many times a day to take it.',
    ].join('\n')
  }

  async function handleConfirm() {
    setLocalBusy(true)
    try {
      await onConfirm?.(item)
    } catch {
      /* the parent page surfaces API errors */
    } finally {
      setLocalBusy(false)
    }
  }

  async function handleSubmit(event) {
    event.preventDefault()
    if (!draft) return
    const fields = {}
    if (draft.medicine_name.trim()) fields.medicine_name = draft.medicine_name.trim()
    if (draft.strength.trim()) fields.strength = draft.strength.trim()
    if (draft.form) fields.form = draft.form
    if (draft.frequency.trim()) fields.frequency = draft.frequency.trim()
    if (draft.food_timing) fields.food_timing = draft.food_timing
    const days = parseInt(draft.duration_days, 10)
    if (!Number.isNaN(days) && days > 0) fields.duration_days = days
    if (Object.keys(fields).length === 0) return

    setLocalBusy(true)
    try {
      const updated = await onEdit?.(item, fields)
      if (updated !== false) setDraft(null) // close on success, stay open on failure
    } catch {
      /* the parent page surfaces API errors; keep the draft open */
    } finally {
      setLocalBusy(false)
    }
  }

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(pharmacistMessage())
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2500)
    } catch {
      /* clipboard unavailable — the message stays visible on screen anyway */
    }
  }

  return (
    <article
      className={`card ${isUnclear || isLowConfidence ? 'border-cozy-white' : ''}`}
      aria-label={lineLabel}
    >
      {/* header: line number + status + OCR confidence */}
      <header className="flex flex-wrap items-center gap-2">
        <span className="chip">{lineLabel}</span>
        <span className={STATUS_CLASSES[item.status] || 'chip'}>
          {statusLabel(t, item.status)}
        </span>
        {item.status !== 'edited' && item.confidence != null ? (
          <span className={`chip ${isLowConfidence ? 'border border-cozy-white text-cozy-white' : ''}`}>
            {t('confidence', { n: Math.round(item.confidence) })}
          </span>
        ) : null}
        {isLowConfidence ? (
          <span className="chip-warn">{t('lowConfidence', { n: Math.round(item.confidence) })}</span>
        ) : null}
        {isUnclear ? <span className="chip-warn">{t('notAddedYet')}</span> : null}
      </header>

      {/* the raw OCR text, so the user can compare it with the original image */}
      <p
        className={`mt-3 rounded-md border p-3 leading-relaxed text-cozy-quiet ${
          isLowConfidence ? 'border-cozy-white bg-cozy-input' : 'border-cozy-border bg-cozy-input'
        }`}
      >
        “{item.source_text}”
      </p>

      {isLowConfidence ? (
        <p className="mt-2 text-xs text-cozy-quiet">{t('lowConfidenceHint')}</p>
      ) : null}

      {/* what MedRecall understood (only meaningful parts shown) */}
      {summary.length ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {summary.map((part) => (
            <span key={part} className="chip-teal">
              {part}
            </span>
          ))}
        </div>
      ) : null}

      {isUnclear ? (
        <div className="mt-4 space-y-4">
          <WarningCard title={t('statusUnclear')} body={t('weWontGuess')}>
            <p className="mt-2 text-sm font-medium text-cozy-white">
              {localizeReason(item.reason)}
            </p>
          </WarningCard>

          <div className="flex flex-wrap gap-3">
            <button
              type="button"
              className="btn-primary btn-sm"
              onClick={handleConfirm}
              disabled={disabled}
            >
              ✓ {t('confirmLine')}
            </button>
            <button
              type="button"
              className="btn-outlined btn-sm"
              onClick={() => setDraft(draft ? null : blankDraft(item))}
              disabled={disabled}
            >
              {t('editManually')}
            </button>
            <button
              type="button"
              className="btn-quiet btn-sm"
              onClick={handleCopy}
              disabled={disabled}
            >
              {copied ? t('copied') : t('askPharmacist')}
            </button>
          </div>

          <div className="rounded-md border border-cozy-border bg-cozy-input p-4">
            <div className="text-xs font-medium text-cozy-subtle">{t('pharmacistMsgLabel')}</div>
            <p className="mt-1 whitespace-pre-line text-sm leading-relaxed text-cozy-quiet">
              {pharmacistMessage()}
            </p>
          </div>

          <p className="text-xs text-cozy-subtle">{t('confirmHint')}</p>
        </div>
      ) : (
        <div className="mt-4 flex justify-end">
          <button
            type="button"
            className="btn-quiet btn-sm"
            onClick={() => setDraft(blankDraft(item))}
            disabled={disabled}
          >
            {t('editManually')}
          </button>
        </div>
      )}

      {/* manual edit form — human input is re-parsed AND re-gated by the API */}
      {draft ? (
        <form className="mt-5 rounded-md border border-cozy-border bg-cozy-input p-5" onSubmit={handleSubmit}>
          <h4 className="text-base font-medium text-cozy-white">{t('editManually')}</h4>

          <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label className="label" htmlFor={`${item.id}-medicine`}>
                {t('fieldMedicine')}
              </label>
              <input
                id={`${item.id}-medicine`}
                className="input"
                value={draft.medicine_name}
                placeholder={t('placeholderMedicine')}
                onChange={(event) => setDraft({ ...draft, medicine_name: event.target.value })}
              />
            </div>
            <div>
              <label className="label" htmlFor={`${item.id}-strength`}>
                {t('fieldStrength')}
              </label>
              <input
                id={`${item.id}-strength`}
                className="input"
                value={draft.strength}
                placeholder={t('placeholderStrength')}
                onChange={(event) => setDraft({ ...draft, strength: event.target.value })}
              />
            </div>
            <div>
              <label className="label" htmlFor={`${item.id}-form`}>
                {t('fieldForm')}
              </label>
              <select
                id={`${item.id}-form`}
                className="input"
                value={draft.form}
                onChange={(event) => setDraft({ ...draft, form: event.target.value })}
              >
                {FORM_OPTIONS.map((option) => (
                  <option key={option} value={option}>
                    {option || '—'}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="label" htmlFor={`${item.id}-frequency`}>
                {t('fieldFrequency')}
              </label>
              <input
                id={`${item.id}-frequency`}
                className="input"
                value={draft.frequency}
                placeholder={t('placeholderFrequency')}
                onChange={(event) => setDraft({ ...draft, frequency: event.target.value })}
              />
            </div>
            <div>
              <label className="label" htmlFor={`${item.id}-food`}>
                {t('fieldFood')}
              </label>
              <select
                id={`${item.id}-food`}
                className="input"
                value={draft.food_timing}
                onChange={(event) => setDraft({ ...draft, food_timing: event.target.value })}
              >
                {FOOD_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {t(option.key)}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="label" htmlFor={`${item.id}-duration`}>
                {t('fieldDuration')}
              </label>
              <input
                id={`${item.id}-duration`}
                className="input"
                type="number"
                min="1"
                max="365"
                value={draft.duration_days}
                onChange={(event) => setDraft({ ...draft, duration_days: event.target.value })}
              />
            </div>
          </div>

          <div className="mt-5 flex flex-wrap gap-3">
            <button type="submit" className="btn-primary btn-sm" disabled={disabled}>
              {t('save')}
            </button>
            <button
              type="button"
              className="btn-quiet btn-sm"
              onClick={() => setDraft(null)}
              disabled={disabled}
            >
              {t('cancel')}
            </button>
          </div>
        </form>
      ) : null}
    </article>
  )
}
