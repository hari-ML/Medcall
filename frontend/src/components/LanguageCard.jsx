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
      className={`w-full rounded-lg border bg-cozy-card p-5 text-left shadow-md transition-colors duration-fast ease-cozy ${
        selected
          ? 'border-cozy-white'
          : 'border-cozy-border hover:border-cozy-borderStrong'
      }`}
    >
      <div className="flex items-center justify-between gap-3">
        <span className="text-base font-medium text-cozy-white">{meta.native}</span>
        <span
          aria-hidden="true"
          className={`flex h-6 w-6 items-center justify-center rounded-full border text-xs ${
            selected
              ? 'border-cozy-white bg-cozy-white text-cozy-canvas'
              : 'border-cozy-borderStrong text-transparent'
          }`}
        >
          ✓
        </span>
      </div>
      <p className="mt-3 text-sm leading-relaxed text-cozy-quiet">{preview}</p>
      <p className="mt-3 text-xs text-cozy-subtle">
        {morning} · {t('preview')}
        {selected ? <span className="ml-2 text-cozy-white">· {t('selected')}</span> : null}
      </p>
    </button>
  )
}
