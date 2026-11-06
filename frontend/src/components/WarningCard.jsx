import React from 'react'

/**
 * Amber warning panel used wherever the safety rule surfaces:
 *  - MedicineLine: a line that is "unclear" and must not be scheduled yet
 *  - Timetable page: the excluded list ("Not in this timetable")
 *
 * role="alert" so screen readers announce the safety message.
 */
export default function WarningCard({ title, body, children, className = '' }) {
  return (
    <div
      role="alert"
      className={`rounded-card border-2 border-amber-400 bg-amber-50 p-5 ${className}`}
    >
      <div className="flex items-start gap-3">
        <span aria-hidden="true" className="text-2xl">
          ⚠️
        </span>
        <div className="min-w-0 flex-1">
          {title ? (
            <h3 className="text-lg font-bold text-amber-900">{title}</h3>
          ) : null}
          {body ? <p className="mt-1 text-lg leading-relaxed text-amber-800">{body}</p> : null}
          {children}
        </div>
      </div>
    </div>
  )
}
