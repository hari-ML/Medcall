import React from 'react'
import { Link, NavLink } from 'react-router-dom'
import { LANGS, useI18n } from '../i18n'

/** Teal capsule logo mark (pure SVG, no image assets needed). */
function LogoMark() {
  return (
    <span
      aria-hidden="true"
      className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-brand-700 text-white shadow-sm"
    >
      <svg viewBox="0 0 24 24" className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth="2">
        <g transform="rotate(-45 12 12)">
          <rect x="3" y="7.5" width="18" height="9" rx="4.5" />
          <line x1="12" y1="7.5" x2="12" y2="16.5" />
        </g>
      </svg>
    </span>
  )
}

/**
 * Persistent navbar: logo + app name, Home link and the language switcher
 * (English / தமிழ் / हिन्दी) — the chosen language drives the whole UI.
 */
export default function Header() {
  const { lang, setLang, t } = useI18n()

  return (
    <header className="sticky top-0 z-40 border-b border-slate-200 bg-white shadow-sm">
      <div className="mx-auto flex w-full max-w-6xl flex-wrap items-center justify-between gap-3 px-4 py-3">
        <Link
          to="/"
          className="flex items-center gap-3 rounded-xl"
          aria-label={`${t('appName')} — ${t('home')}`}
        >
          <LogoMark />
          <span className="flex flex-col leading-tight">
            <span className="text-xl font-extrabold tracking-tight text-brand-800">
              {t('appName')}
            </span>
            <span className="hidden text-sm text-slate-500 sm:block">{t('tagline')}</span>
          </span>
        </Link>

        <div className="flex items-center gap-4">
          <nav aria-label="Main">
            <NavLink
              to="/"
              end
              className={({ isActive }) =>
                `rounded-xl px-4 py-2 text-lg font-semibold transition-colors ${
                  isActive ? 'bg-brand-50 text-brand-800' : 'text-slate-600 hover:bg-slate-100'
                }`
              }
            >
              {t('home')}
            </NavLink>
          </nav>

          <div
            className="flex items-center gap-1 rounded-full bg-slate-100 p-1"
            role="group"
            aria-label="Language"
          >
            {LANGS.map((option) => (
              <button
                key={option.code}
                type="button"
                onClick={() => setLang(option.code)}
                aria-pressed={lang === option.code}
                aria-label={option.label}
                className={`rounded-full px-3 py-2 text-base font-semibold transition-colors ${
                  lang === option.code
                    ? 'bg-brand-700 text-white shadow'
                    : 'text-slate-600 hover:text-brand-700'
                }`}
              >
                {option.native}
              </button>
            ))}
          </div>
        </div>
      </div>
    </header>
  )
}
