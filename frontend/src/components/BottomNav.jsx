import React from 'react'
import { NavLink } from 'react-router-dom'
import { useI18n } from '../i18n'
import { getLastPrescription } from '../store'

/**
 * Floating bottom navigation (Cozy design system).
 *
 * A dark pill (#2A2A2A, radius 24px) pinned to the bottom of the viewport
 * with four destinations. The active route is a solid white circle with a
 * #121212 icon; inactive icons are #A3A3A3. Labels are screen-reader only —
 * the pill stays compact on small phones.
 */
const ITEMS = [
  {
    to: '/',
    end: true,
    key: 'home',
    icon: (
      <path d="M3 10.5 12 3l9 7.5M5 9.5V21h5v-6h4v6h5V9.5" />
    ),
  },
  {
    to: '/timetable/latest',
    key: 'navTimetable',
    icon: (
      <>
        <rect x="3" y="6" width="18" height="15" rx="3" />
        <path d="M3 10h18M8 3v4M16 3v4" />
      </>
    ),
  },
  {
    to: '/reminders',
    key: 'navReminders',
    icon: (
      <path d="M18 9a6 6 0 1 0-12 0c0 5-2 6-2 6h16s-2-1-2-6M10.5 20a2 2 0 0 0 3 0" />
    ),
  },
  {
    to: '/agent',
    key: 'navAgent',
    icon: <path d="M21 12a8 8 0 0 1-8 8H7l-4 3v-7a8 8 0 0 1 8-8h2a8 8 0 0 1 8 4Z" />,
  },
]

export default function BottomNav() {
  const { t } = useI18n()
  // Timetable lives under a prescription id; SSR has no stored id and falls
  // back to the upload screen (never a dead link).
  const last = getLastPrescription()
  const timetablePath = last ? `/timetable/${last}` : '/upload'

  return (
    <nav aria-label="Primary" className="bottom-nav">
      {ITEMS.map((item) => (
        <NavLink
          key={item.key}
          to={item.key === 'navTimetable' ? timetablePath : item.to}
          end={item.end}
          className={({ isActive }) => (isActive ? 'bottom-nav-active' : 'bottom-nav-link')}
          title={t(item.key)}
        >
          {({ isActive }) => (
            <>
              <svg
                viewBox="0 0 24 24"
                className="h-6 w-6"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                {item.icon}
              </svg>
              <span className="sr-only">{t(item.key)}</span>
              <span className="sr-only">{isActive ? ' — current page' : ''}</span>
            </>
          )}
        </NavLink>
      ))}
    </nav>
  )
}
