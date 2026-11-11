import React from 'react'

/**
 * Warning panel used wherever the safety rule surfaces:
 *  - MedicineLine: a line that is "unclear" and must not be scheduled yet
 *  - Timetable page: the excluded list ("Not in this timetable")
 *
 * Cozy monochrome: a solid white border is the strongest signal on the dark
 * canvas. role="alert" so screen readers announce the safety message.
 */
export default function WarningCard({ title, body, children, className = '' }) {
  return (
    <div
      role="alert"
      className={`rounded-lg border border-cozy-white bg-cozy-card p-5 shadow-md ${className}`}
    >
      <div className="flex items-start gap-3">
        <span
          aria-hidden="true"
          className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-cozy-white text-xs font-medium text-cozy-white"
        >
          !
        </span>
        <div className="min-w-0 flex-1">
          {title ? (
            <h3 className="text-base font-medium text-cozy-white">{title}</h3>
          ) : null}
          {body ? <p className="mt-1 text-sm leading-relaxed text-cozy-quiet">{body}</p> : null}
          {children}
        </div>
      </div>
    </div>
  )
}
