import React from 'react'
import { LANGUAGE_PREVIEWS, LANGS, SLOT_NAMES, useI18n } from '../i18n'

/**
 * One selectable language option (used on the Language screen).
 *
 * @param code      'en' | 'ta' | 'hi'
 * @param selected  whether this language is currently active
 * @param onSelect  (code) => void
 */
export default function LanguageCard({ code, selected, onSelect }) {
  const { t } = useI18n()
  const meta = LANGS.find((option) => option.code === code) || LANGS[0]
  const preview = LANGUAGE_PREVIEWS[code] || LANGUAGE_PREVIEWS.en
  const morning = (SLOT_NAMES[code] || SLOT_NAMES.en).morning

  return (
    <button
      type="button"
      onClick={() => onSelect(code)}
      aria-pressed={selected}
      aria-label={`${meta.label}${selected ? ` — ${t('selected')}` : ''}`}
      className={`card w-full text-left transition-colors ${
        selected
          ? 'border-2 border-brand-700 ring-4 ring-brand-100'
          : 'border border-slate-200 hover:border-brand-400'
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-2xl font-bold text-slate-800">{meta.native}</div>
          <div className="text-base text-slate-500">{meta.label}</div>
        </div>
        <span
          aria-hidden="true"
          className={`inline-flex h-9 w-9 items-center justify-center rounded-full text-lg font-bold ${
            selected ? 'bg-brand-700 text-white' : 'bg-slate-100 text-slate-400'
          }`}
        >
          ✓
        </span>
      </div>

      <div className="mt-4 rounded-xl bg-slate-50 p-4">
        <div className="text-sm font-semibold uppercase tracking-wide text-slate-500">
          {t('preview')}
        </div>
        <div className="mt-1 text-lg text-slate-800">{preview}</div>
        <div className="mt-2 text-base font-semibold text-brand-700">☀️ {morning}</div>
      </div>

      <div className="mt-4">
        {selected ? (
          <span className="chip-teal">✓ {t('selected')}</span>
        ) : (
          <span className="chip">{t('choose')}</span>
        )}
      </div>
    </button>
  )
}
