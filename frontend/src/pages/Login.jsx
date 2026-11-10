import React, { useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { errorMessage } from '../api'
import { useAuth } from '../auth'
import { useI18n } from '../i18n'

/**
 * Phone + OTP sign-in (Phase 7).
 *
 * Step 1: phone number → POST /api/auth/otp/request (dev mode shows the code
 * on screen so the flow works without an SMS provider — production returns
 * 503 until one is wired, and the backend never echoes codes there).
 * Step 2: 6-digit code (+ optional name on first sign-in) → session.
 *
 * The form renders even when already signed in (with a "continue" shortcut),
 * so server rendering is deterministic.
 */
export default function Login() {
  const { t } = useI18n()
  const { isAuthed, patient, requestCode, completeLogin } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const from = location.state?.from || '/'

  const [phone, setPhone] = useState('')
  const [code, setCode] = useState('')
  const [name, setName] = useState('')
  const [devCode, setDevCode] = useState(null)
  const [expiresIn, setExpiresIn] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  async function handleSendCode(event) {
    event.preventDefault()
    setError(null)
    setBusy(true)
    try {
      const data = await requestCode(phone.trim())
      setDevCode(data?.dev_code || null)
      setExpiresIn(data?.expires_in || null)
      if (data?.dev_code) setCode(data.dev_code) // dev convenience
    } catch (err) {
      setError(errorMessage(err) || t('errorGeneric'))
    } finally {
      setBusy(false)
    }
  }

  async function handleVerify(event) {
    event.preventDefault()
    setError(null)
    setBusy(true)
    try {
      await completeLogin({
        phone: phone.trim(),
        code: code.trim(),
        full_name: name.trim() || undefined,
      })
      navigate(from, { replace: true })
    } catch (err) {
      setError(errorMessage(err) || t('errorGeneric'))
    } finally {
      setBusy(false)
    }
  }

  function handleBackToPhone(event) {
    event.preventDefault()
    setDevCode(null)
    setCode('')
    setError(null)
  }

  return (
    <div className="mx-auto max-w-xl space-y-6">
      <div className="text-center">
        <h1 className="text-3xl font-bold text-slate-800">{t('loginTitle')}</h1>
        <p className="mt-2 text-lg leading-relaxed text-slate-600">{t('loginIntro')}</p>
      </div>

      {isAuthed ? (
        <div className="rounded-card border-2 border-emerald-200 bg-emerald-50 p-4 text-center">
          <p className="font-semibold text-emerald-800">
            {t('signedInAs', { phone: patient?.full_name || patient?.phone || '' })}
          </p>
          <Link to={from} className="btn-primary mt-3 inline-flex">
            {t('next')} →
          </Link>
        </div>
      ) : null}

      {error ? (
        <div role="alert" className="rounded-card border-2 border-red-300 bg-red-50 p-4 text-red-800">
          {error}
        </div>
      ) : null}

      {devCode ? (
        <div className="rounded-card border-2 border-sky-200 bg-sky-50 p-4 text-center text-sky-900">
          {t('devCodeHint', { code: devCode })}
          {expiresIn ? <p className="mt-1 text-sm">{t('otpSent', { n: Math.round(expiresIn / 60) })}</p> : null}
        </div>
      ) : null}

      <form onSubmit={devCode ? handleVerify : handleSendCode} className="card space-y-5">
        <div>
          <label htmlFor="login-phone" className="label">
            {t('phoneLabel')}
          </label>
          <input
            id="login-phone"
            type="tel"
            inputMode="tel"
            autoComplete="tel"
            required
            value={phone}
            onChange={(event) => setPhone(event.target.value)}
            placeholder={t('phonePlaceholder')}
            className="input"
          />
        </div>

        {devCode ? (
          <>
            <div>
              <label htmlFor="login-code" className="label">
                {t('codeLabel')}
              </label>
              <input
                id="login-code"
                type="text"
                inputMode="numeric"
                autoComplete="one-time-code"
                pattern="[0-9]{6}"
                maxLength={6}
                required
                value={code}
                onChange={(event) => setCode(event.target.value.replace(/\D/g, ''))}
                placeholder={t('codePlaceholder')}
                className="input text-center text-2xl tracking-[0.4em]"
              />
            </div>
            <div>
              <label htmlFor="login-name" className="label">
                {t('nameLabel')}
              </label>
              <input
                id="login-name"
                type="text"
                autoComplete="name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder={t('namePlaceholder')}
                className="input"
              />
            </div>
          </>
        ) : null}

        <div className="flex flex-wrap items-center justify-between gap-3">
          {devCode ? (
            <button type="button" className="btn-quiet" onClick={handleBackToPhone}>
              ← {t('backToPhone')}
            </button>
          ) : (
            <span className="text-sm text-slate-500">{t('otpNoPassword')}</span>
          )}
          <button type="submit" className="btn-primary" disabled={busy}>
            {busy ? t('loading') : devCode ? t('verifyAndEnter') : t('sendCode')}
          </button>
        </div>
      </form>
    </div>
  )
}
