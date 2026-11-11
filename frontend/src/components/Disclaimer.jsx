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
    <footer className="mt-10 border-t border-cozy-border bg-cozy-canvas">
      <div className="mx-auto flex w-full max-w-6xl items-start gap-3 px-4 py-5">
        <span
          aria-hidden="true"
          className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-cozy-white text-xs font-medium text-cozy-white"
        >
          !
        </span>
        <p className="text-sm font-medium leading-relaxed text-cozy-quiet">{disclaimer}</p>
      </div>
    </footer>
  )
}
