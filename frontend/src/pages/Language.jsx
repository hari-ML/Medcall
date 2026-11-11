import React from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import LanguageCard from '../components/LanguageCard'
import { LANGS, useI18n } from '../i18n'

/**
 * Language screen (Cozy design system): pick English / தமிழ் / हिन्दी. The
 * choice switches the whole UI immediately (live preview on each card) and is
 * the language used for the schedule, reminders and printable PDF of this
 * prescription.
 */
export default function Language() {
  const { id } = useParams()
  const pid = Number(id)
  const navigate = useNavigate()
  const { lang, setLang, t } = useI18n()

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <header>
        <Link to={`/review/${Number.isFinite(pid) ? pid : ''}`} className="btn-quiet btn-sm inline-flex">
          ← {t('back')}
        </Link>
        <h1 className="mt-5 text-lg font-medium leading-tight text-cozy-white">
          {t('langTitle')}
        </h1>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-cozy-quiet">
          {t('langSubtitle')}
        </p>
      </header>

      <div className="grid gap-4 sm:grid-cols-3">
        {LANGS.map((option) => (
          <LanguageCard
            key={option.code}
            code={option.code}
            selected={lang === option.code}
            onSelect={setLang}
          />
        ))}
      </div>

      <div className="flex justify-center pt-2">
        <button
          type="button"
          className="btn-primary"
          disabled={!Number.isFinite(pid)}
          onClick={() => navigate(`/timetable/${pid}`)}
        >
          {t('seeTimetable')} →
        </button>
      </div>
    </div>
  )
}
