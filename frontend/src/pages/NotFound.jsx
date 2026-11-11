import React from 'react'
import { Link } from 'react-router-dom'
import { useI18n } from '../i18n'

/**
 * 404 screen (Cozy design system).
 *
 * One clear message, two actions: Primary "Return to home" and Outlined
 * "Scan prescription". The layout keeps the persistent header, disclaimer
 * and bottom navigation of the app shell.
 */
export default function NotFound() {
  const { t } = useI18n()

  return (
    <section className="mx-auto flex max-w-2xl flex-col items-center py-14 text-center">
      <h1 className="text-lg font-medium tracking-tight text-cozy-white">{t('notFoundTitle')}</h1>
      <p className="mt-3 max-w-md text-sm leading-relaxed text-cozy-quiet">{t('notFoundBody')}</p>
      <div className="mt-8 flex w-full max-w-sm flex-col gap-3 sm:flex-row sm:justify-center">
        <Link to="/" className="btn-primary">
          {t('returnHome')}
        </Link>
        <Link to="/upload" className="btn-outlined">
          {t('scanPrescription')}
        </Link>
      </div>
    </section>
  )
}
