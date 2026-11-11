import React from 'react'
import { SLOT_NAMES, useI18n } from '../i18n'

/**
 * Unique key for one scheduled dose (one medicine in one slot on one day).
 * The SAME key convention is used by store.js (Mark-as-taken persistence),
 * the Home progress bar and the Timetable page.
 */
export function doseKey(entry) {
  return `${entry.id}:${entry.slot || ''}`
}

/**
 * One slot card on the Timetable: localized slot name + default time and the
 * medicines placed there (each translated by the backend), with a big
 * "Mark as taken" toggle.
 *
 * @param slot      'morning' | 'afternoon' | 'evening' | 'night'
 * @param time      '08:00' etc.
 * @param entries   [{id, medicine, status, instruction, time, slot}]
 * @param taken     {doseKey: true} — doses already marked taken today
 * @param onToggle  (doseKey) => void   (omit to hide the buttons)
 * @param emptyNote localized "nothing scheduled" text (from the API payload)
 */
export default function DoseCard({ slot, time, entries = [], taken = {}, onToggle, emptyNote }) {
  const { t, lang } = useI18n()
  const slotName = (SLOT_NAMES[lang] || SLOT_NAMES.en)[slot] || slot

  return (
    <section className="card flex flex-col">
      <header className="flex items-center justify-between gap-2 border-b border-cozy-border pb-3">
        <h3 className="flex items-center gap-2 text-base font-medium text-cozy-white">
          <span aria-hidden="true" className="h-2 w-2 rounded-full bg-cozy-white" />
          {slotName}
        </h3>
        {time ? (
          <span className="chip-teal">
            {t('time')} {time}
          </span>
        ) : null}
      </header>

      {entries.length === 0 ? (
        <p className="mt-4 text-sm italic text-cozy-subtle">{emptyNote || '—'}</p>
      ) : (
        <ul className="mt-4 flex-1 space-y-4">
          {entries.map((entry) => {
            const key = doseKey(entry)
            const isTaken = Boolean(taken[key])
            return (
              <li key={key} className="rounded-md border border-cozy-border bg-cozy-elevated p-4">
                <div className="text-base font-medium text-cozy-white">{entry.medicine}</div>
                <p className="mt-1 text-sm leading-relaxed text-cozy-quiet">{entry.instruction}</p>
                {onToggle ? (
                  <button
                    type="button"
                    onClick={() => onToggle(key)}
                    aria-pressed={isTaken}
                    className={
                      isTaken
                        ? 'mt-3 inline-flex w-full items-center justify-center gap-2 rounded-md border border-cozy-borderStrong bg-cozy-secondary px-4 py-2 text-xs font-medium text-cozy-white transition-colors duration-fast ease-cozy hover:bg-cozy-elevated'
                        : 'btn-primary btn-sm mt-3 w-full'
                    }
                  >
                    ✓ {isTaken ? t('taken') : t('markAsTaken')}
                  </button>
                ) : null}
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
