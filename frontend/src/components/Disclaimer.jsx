import React from 'react'
import { useI18n } from '../i18n'

/**
 * The persistent disclaimer band, rendered on EVERY page (App mounts it once
 * below the routed content so it is always present).
 *
 * "MedRecall explains. It never prescribes. Always confirm with your doctor
 *  or pharmacist." — localized via i18n.
 */
export default function Disclaimer() {
  const { disclaimer } = useI18n()

  return (
    <footer className="mt-10 border-t-4 border-brand-700 bg-brand-50">
      <div className="mx-auto flex w-full max-w-6xl items-start gap-3 px-4 py-5">
        <span aria-hidden="true" className="text-2xl">
          ⚠️
        </span>
        <p className="text-lg font-medium leading-relaxed text-brand-900">{disclaimer}</p>
      </div>
    </footer>
  )
}
