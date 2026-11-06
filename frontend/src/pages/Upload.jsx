import React, { useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { createDemo, uploadPrescription } from '../api'
import { useI18n } from '../i18n'
import { setLastPrescription } from '../store'

const ACCEPTED_TYPES = ['image/jpeg', 'image/png', 'application/pdf']
const MAX_BYTES = 10 * 1024 * 1024

/**
 * Upload screen: big drag & drop zone (JPG/PNG/PDF ≤ 10 MB), file picker,
 * camera capture, and the zero-dependency demo alternative. Client-side
 * validation mirrors the backend (415/413/400) so users get instant feedback;
 * on success we jump straight to /review/:id.
 */
export default function Upload() {
  const { t } = useI18n()
  const navigate = useNavigate()
  const fileInput = useRef(null)
  const cameraInput = useRef(null)

  const [dragging, setDragging] = useState(false)
  const [progress, setProgress] = useState(null) // null = idle, 0-100 = uploading
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

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <Link to="/" className="btn-quiet btn-sm inline-flex">
          ← {t('back')}
        </Link>
        <h1 className="mt-4 text-3xl font-bold text-slate-800">{t('uploadTitle')}</h1>
        <p className="mt-2 text-lg text-slate-600">{t('uploadHint')}</p>
      </div>

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
        className={`cursor-pointer rounded-card border-4 border-dashed p-10 text-center transition-colors ${
          dragging ? 'border-brand-600 bg-brand-50' : 'border-slate-300 bg-white hover:border-brand-400'
        } ${uploading ? 'pointer-events-none opacity-60' : ''}`}
      >
        <div className="text-5xl" aria-hidden="true">
          {dragging ? '📥' : '📄'}
        </div>
        <p className="mt-4 text-xl font-semibold text-slate-800">
          {dragging ? t('dropActive') : t('dropHere')}
        </p>
        <p className="mt-1 text-slate-500">{t('dropFormats')}</p>

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
            📸 {t('takePhoto')}
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
            📁 {t('chooseFile')}
          </button>
        </div>
      </div>

      {/* upload progress */}
      {progress !== null ? (
        <div className="card" role="status">
          <div className="text-lg font-semibold text-slate-700">
            {t('uploading')} {progress}%
          </div>
          <div className="mt-3 h-4 w-full overflow-hidden rounded-full bg-slate-200">
            <div
              className="h-4 rounded-full bg-brand-600 transition-all duration-300"
              style={{ width: `${Math.max(progress, 5)}%` }}
            />
          </div>
        </div>
      ) : null}

      {/* error */}
      {error ? (
        <div role="alert" className="rounded-card border-2 border-red-300 bg-red-50 p-4 text-lg text-red-800">
          {error}
        </div>
      ) : null}

      {/* demo alternative */}
      <div className="card flex flex-wrap items-center justify-between gap-4">
        <div>
          <div className="text-lg font-semibold text-slate-800">{t('noPrescription')}</div>
          <p className="text-base text-slate-500">{t('dropFormats')}</p>
        </div>
        <button type="button" className="btn-secondary" onClick={handleDemo} disabled={uploading}>
          {demoBusy ? t('loading') : `⚡ ${t('tryDemo')}`}
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
