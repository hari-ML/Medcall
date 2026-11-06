import React from 'react'
import { SLOT_NAMES, useI18n } from '../i18n'

const SLOT_ICONS = {
  morning: '☀️',
  afternoon: '🌤️',
  evening: '🌇',
  night: '🌙',
}

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
      <header className="flex items-center justify-between gap-2 border-b border-slate-100 pb-3">
        <h3 className="flex items-center gap-2 text-xl font-bold text-slate-800">
          <span aria-hidden="true">{SLOT_ICONS[slot] || '⏰'}</span>
          {slotName}
        </h3>
        {time ? <span className="chip-teal">{t('time')} {time}</span> : null}
      </header>

      {entries.length === 0 ? (
        <p className="mt-4 text-lg italic text-slate-500">{emptyNote || '—'}</p>
      ) : (
        <ul className="mt-4 flex-1 space-y-4">
          {entries.map((entry) => {
            const key = doseKey(entry)
            const isTaken = Boolean(taken[key])
            return (
              <li key={key} className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                <div className="text-lg font-bold text-slate-800">{entry.medicine}</div>
                <p className="mt-1 leading-relaxed text-slate-700">{entry.instruction}</p>
                {onToggle ? (
                  <button
                    type="button"
                    onClick={() => onToggle(key)}
                    aria-pressed={isTaken}
                    className={
                      isTaken
                        ? 'mt-3 inline-flex w-full items-center justify-center gap-2 rounded-xl bg-emerald-600 px-4 py-3 text-base font-semibold text-white shadow-sm hover:bg-emerald-700'
                        : 'btn-secondary btn-sm mt-3 w-full'
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
