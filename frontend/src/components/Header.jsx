import React from 'react'
import { Link, NavLink } from 'react-router-dom'
import { useAuth } from '../auth'
import { LANGS, useI18n } from '../i18n'

/** Monochrome capsule logo mark (pure SVG, token colours). */
function LogoMark() {
  return (
    <span
      aria-hidden="true"
      className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-cozy-white text-cozy-canvas shadow-sm"
    >
      <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2">
        <g transform="rotate(-45 12 12)">
          <rect x="3" y="7.5" width="18" height="9" rx="4.5" />
          <line x1="12" y1="7.5" x2="12" y2="16.5" />
        </g>
      </svg>
    </span>
  )
}

/**
 * Persistent top bar: logo + app name, desktop nav (Home / Reminders / Ask),
 * sign-in or sign-out, and the language switcher (English / தமிழ் / हिन्दी).
 * Phones use the floating BottomNav instead of the text links.
 */
export default function Header() {
  const { lang, setLang, t } = useI18n()
  const { isAuthed, patient, logout } = useAuth()

  const navLinkClass = ({ isActive }) =>
    `rounded-md px-3 py-2 text-xs font-medium transition-colors duration-fast ease-cozy ${
      isActive
        ? 'bg-cozy-white text-cozy-canvas'
        : 'text-cozy-quiet hover:bg-cozy-elevated hover:text-cozy-white'
    }`

  return (
    <header className="sticky top-0 z-40 border-b border-cozy-border bg-cozy-canvas/95 backdrop-blur">
      <div className="mx-auto flex w-full max-w-6xl flex-wrap items-center justify-between gap-3 px-4 py-3">
        <Link
          to="/"
          className="flex items-center gap-3 rounded-md p-1 transition-colors duration-fast ease-cozy hover:bg-cozy-elevated"
          aria-label={`${t('appName')} — ${t('home')}`}
        >
          <LogoMark />
          <span className="flex flex-col leading-tight">
            <span className="text-base font-medium tracking-tight text-cozy-white">
              {t('appName')}
            </span>
            <span className="hidden text-xs text-cozy-quiet sm:block">{t('tagline')}</span>
          </span>
        </Link>

        <div className="flex items-center gap-2">
          <nav aria-label="Main" className="hidden items-center gap-1 md:flex">
            <NavLink to="/" end className={navLinkClass}>
              {t('home')}
            </NavLink>
            <NavLink to="/reminders" className={navLinkClass}>
              {t('navReminders')}
            </NavLink>
            <NavLink to="/agent" className={navLinkClass}>
              {t('navAgent')}
            </NavLink>
          </nav>

          {isAuthed ? (
            <button
              type="button"
              onClick={() => logout()}
              className="btn-outlined btn-sm"
              title={t('signedInAs', { phone: patient?.phone || '' })}
            >
              {t('signOut')}
            </button>
          ) : (
            <Link to="/login" className="btn-primary btn-sm">
              {t('signIn')}
            </Link>
          )}

          <div
            className="flex items-center gap-1 rounded-full border border-cozy-border bg-cozy-elevated p-1"
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
                className={`rounded-full px-3 py-1 text-xs font-medium transition-colors duration-fast ease-cozy ${
                  lang === option.code
                    ? 'bg-cozy-white text-cozy-canvas shadow-sm'
                    : 'text-cozy-quiet hover:text-cozy-white'
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
