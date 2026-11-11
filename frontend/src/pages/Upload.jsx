import React, { useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { createDemo, uploadPrescription } from '../api'
import { useI18n } from '../i18n'
import { setLastPrescription } from '../store'

const ACCEPTED_TYPES = ['image/jpeg', 'image/png', 'application/pdf']
const MAX_BYTES = 10 * 1024 * 1024

const STEP_KEYS = ['ocrStepUpload', 'ocrStepPreprocess', 'ocrStepRead', 'ocrStepExtract', 'ocrStepVerify']

function StepRow({ label, state }) {
  return (
    <li className="flex items-center gap-3">
      <span
        aria-hidden="true"
        className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-xs ${
          state === 'done'
            ? 'border-cozy-white bg-cozy-white text-cozy-canvas'
            : state === 'active'
              ? 'border-cozy-white text-cozy-white'
              : 'border-cozy-border text-cozy-subtle'
        }`}
      >
        {state === 'done' ? '✓' : state === 'active' ? '•' : ''}
      </span>
      <span
        className={`text-sm ${
          state === 'pending' ? 'text-cozy-subtle' : 'text-cozy-quiet'
        } ${state === 'active' ? 'animate-pulse text-cozy-white' : ''}`}
      >
        {label}
      </span>
    </li>
  )
}

/**
 * Upload screen (Cozy design system).
 *
 * Camera capture, gallery/file picker and drag & drop (JPG/PNG/PDF ≤ 10 MB),
 * plus the zero-dependency demo prescription. The progress panel follows the
 * real upload percentage and then the server-side OCR stages; it never
 * advances on a timer. On success we jump straight to /review/:id, where any
 * line below 80% confidence is highlighted for human review.
 */
export default function Upload() {
  const { t } = useI18n()
  const navigate = useNavigate()
  const fileInput = useRef(null)
  const cameraInput = useRef(null)

  const [dragging, setDragging] = useState(false)
  const [progress, setProgress] = useState(null) // null = idle, 0-100 = working
  const [error, setError] = useState(null)
  const [demoBusy, setDemoBusy] = useState(false)

  const uploading = progress !== null || demoBusy

  function validate(file) {
    if (!ACCEPTED_TYPES.includes(file.type)) return t('fileTypeInvalid')
    if (file.size > MAX_BYTES) return t('fileTooLarge')
    return null
  }

  async function handleFile(file) {
    if (!file || uploading) return
    const problem = validate(file)
    if (problem) {
      setError(problem)
      return
    }
    setError(null)
    setProgress(0)
    try {
      const prescription = await uploadPrescription(file, setProgress)
      setLastPrescription(prescription.id)
      navigate(`/review/${prescription.id}`)
    } catch (err) {
      setError(err?.message || t('errorGeneric'))
      setProgress(null)
    }
  }

  async function handleDemo() {
    if (uploading) return
    setDemoBusy(true)
    setError(null)
    try {
      const prescription = await createDemo()
      setLastPrescription(prescription.id)
      navigate(`/review/${prescription.id}`)
    } catch (err) {
      setError(err?.message || t('errorGeneric'))
      setDemoBusy(false)
    }
  }

  function pickFromInput(event) {
    const file = event.target.files?.[0]
    event.target.value = '' // allow re-selecting the same file
    handleFile(file)
  }

  function stepState(index) {
    if (progress === null) return 'pending'
    if (index === 0) return progress >= 100 ? 'done' : 'active'
    if (progress >= 100) {
      // The file is fully uploaded; the backend is now cleaning the image,
      // running OCR and extracting medicines. We can't know exact sub-stage
      // boundaries, so these steps stay active until the response arrives.
      if (index === STEP_KEYS.length - 1) return 'pending'
      return 'active'
    }
    return 'pending'
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <header>
        <Link to="/" className="btn-quiet btn-sm inline-flex">
          ← {t('back')}
        </Link>
        <h1 className="mt-5 text-lg font-medium leading-tight text-cozy-white">
          {t('uploadTitle')}
        </h1>
        <p className="mt-2 text-sm leading-relaxed text-cozy-quiet">{t('uploadHint')}</p>
      </header>

      {/* drop zone */}
      <div
        role="button"
        tabIndex={0}
        aria-label={t('dropHere')}
        onClick={() => !uploading && fileInput.current?.click()}
        onKeyDown={(event) => {
          if ((event.key === 'Enter' || event.key === ' ') && !uploading) {
            event.preventDefault()
            fileInput.current?.click()
          }
        }}
        onDragOver={(event) => {
          event.preventDefault()
          if (!uploading) setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault()
          setDragging(false)
          handleFile(event.dataTransfer?.files?.[0])
        }}
        className={`cursor-pointer rounded-lg border border-dashed bg-cozy-card p-10 text-center shadow-md transition-colors duration-fast ease-cozy ${
          dragging ? 'border-cozy-white bg-cozy-elevated' : 'border-cozy-borderStrong hover:border-cozy-white'
        } ${uploading ? 'pointer-events-none opacity-50' : ''}`}
      >
        <span className="mx-auto flex h-13 w-13 items-center justify-center rounded-full border border-cozy-borderStrong text-cozy-white">
          <svg
            viewBox="0 0 24 24"
            className="h-6 w-6"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            aria-hidden="true"
          >
            <path d="M4 8h3l2-3h6l2 3h3v12H4Z" />
            <circle cx="12" cy="13" r="4" />
          </svg>
        </span>
        <p className="mt-5 text-base font-medium text-cozy-white">
          {dragging ? t('dropActive') : t('dropHere')}
        </p>
        <p className="mt-1 text-xs text-cozy-subtle">{t('dropFormats')}</p>

        <div className="mt-6 flex flex-wrap justify-center gap-3">
          <button
            type="button"
            className="btn-secondary"
            onClick={(event) => {
              event.stopPropagation()
              cameraInput.current?.click()
            }}
            disabled={uploading}
          >
            {t('takePhoto')}
          </button>
          <button
            type="button"
            className="btn-primary"
            onClick={(event) => {
              event.stopPropagation()
              fileInput.current?.click()
            }}
            disabled={uploading}
          >
            {t('chooseFile')}
          </button>
        </div>
      </div>

      {/* stepped progress — driven by real upload + server OCR response */}
      {progress !== null ? (
        <section className="card" role="status" aria-live="polite">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-medium text-cozy-white">{t('uploading')}</h2>
            <span className="chip">{Math.round(progress)}%</span>
          </div>
          <div className="progress-track mt-3">
            <div className="progress-bar" style={{ width: `${Math.max(progress, 4)}%` }} />
          </div>
          <ol className="mt-5 space-y-3">
            {STEP_KEYS.map((key, index) => (
              <StepRow key={key} label={t(key)} state={stepState(index)} />
            ))}
          </ol>
          <p className="mt-4 text-xs text-cozy-subtle">{t('ocrStepHint')}</p>
        </section>
      ) : null}

      {demoBusy ? (
        <div className="card text-sm text-cozy-quiet" role="status">
          {t('loading')}
        </div>
      ) : null}

      {/* error */}
      {error ? (
        <div role="alert" className="alert-error text-sm">
          {error}
        </div>
      ) : null}

      {/* demo alternative */}
      <div className="card flex flex-wrap items-center justify-between gap-4">
        <div>
          <div className="text-base font-medium text-cozy-white">{t('noPrescription')}</div>
          <p className="mt-1 text-xs text-cozy-subtle">{t('dropFormats')}</p>
        </div>
        <button type="button" className="btn-outlined" onClick={handleDemo} disabled={uploading}>
          {demoBusy ? t('loading') : t('tryDemo')}
        </button>
      </div>

      {/* hidden inputs */}
      <input
        ref={fileInput}
        type="file"
        accept="image/jpeg,image/png,application/pdf"
        className="hidden"
        onChange={pickFromInput}
        aria-hidden="true"
        tabIndex={-1}
      />
      <input
        ref={cameraInput}
        type="file"
        accept="image/*"
        capture="environment"
        className="hidden"
        onChange={pickFromInput}
        aria-hidden="true"
        tabIndex={-1}
      />
    </div>
  )
}
