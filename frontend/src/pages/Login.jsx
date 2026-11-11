import React, { useEffect, useRef, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { errorMessage } from '../api'
import { useAuth } from '../auth'
import { useI18n } from '../i18n'

const OTP_LENGTH = 6
const RESEND_SECONDS = 30

// Registration language choices are plain labels: the UI itself only has
// en/ta/hi tables, but the backend accepts Telugu and falls back to English.
const REGISTER_LANGS = [
  { code: 'en', label: 'English' },
  { code: 'hi', label: 'हिन्दी' },
  { code: 'ta', label: 'தமிழ்' },
  { code: 'te', label: 'తెలుగు' },
]

const REGISTER_CHANNELS = [
  { code: 'whatsapp', key: 'channelWhatsapp' },
  { code: 'sms', key: 'channelSms' },
]

function digitsOnly(value, max = 10) {
  return String(value || '').replace(/\D/g, '').slice(0, max)
}

/**
 * Phone + OTP authentication (Phase 7, MedRecall 2.0).
 *
 * Two modes share one screen:
 *  - sign in: a registered 10-digit mobile number → POST /auth/otp/request
 *  - register: full name, language, channel, optional caregiver → /auth/register
 *
 * The six-box code input auto-advances, supports backspace and paste, shows a
 * 30-second resend countdown and maps every structured backend auth error to
 * a specific, localized state (404 not registered, 409 already registered,
 * 401 bad/expired code, 429 rate limited / too many attempts).
 *
 * The form renders even when already signed in (with a session banner), so
 * server rendering is deterministic.
 */
export default function Login({ initialMode = 'signin' }) {
  const { t } = useI18n()
  const {
    isAuthed,
    patient,
    sessionNotice,
    clearSessionNotice,
    register,
    requestCode,
    completeLogin,
    logout,
  } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const from = location.state?.from || '/'

  const [mode, setMode] = useState(initialMode === 'register' ? 'register' : 'signin')
  const [step, setStep] = useState('details') // 'details' | 'otp'
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null) // {code, attemptsLeft, retryAfter, fallback}
  const [info, setInfo] = useState(null) // {devCode, sentVia}

  // form fields
  const [phone, setPhone] = useState('')
  const [fullName, setFullName] = useState('')
  const [preferredLang, setPreferredLang] = useState('en')
  const [preferredChannel, setPreferredChannel] = useState('whatsapp')
  const [caregiver, setCaregiver] = useState('')
  const [touchedPhone, setTouchedPhone] = useState(false)

  // OTP state
  const [digits, setDigits] = useState(Array(OTP_LENGTH).fill(''))
  const [cooldown, setCooldown] = useState(0)
  const [shake, setShake] = useState(false)
  const boxRefs = useRef([])

  const phoneValid = phone.length === 10
  const caregiverValid = caregiver.length === 0 || caregiver.length === 10
  const code = digits.join('')

  // 30s resend countdown (also used by the 429 cooldown).
  useEffect(() => {
    if (cooldown <= 0) return undefined
    const timer = window.setTimeout(() => setCooldown((value) => value - 1), 1000)
    return () => window.clearTimeout(timer)
  }, [cooldown])

  // Focus the first OTP box whenever the code step opens.
  useEffect(() => {
    if (step === 'otp') boxRefs.current[0]?.focus()
  }, [step])

  function resetFlow(nextMode) {
    setMode(nextMode)
    setStep('details')
    setDigits(Array(OTP_LENGTH).fill(''))
    setCooldown(0)
    setError(null)
    setInfo(null)
    setTouchedPhone(false)
    setBusy(false)
  }

  function messageFor(state) {
    if (!state) return ''
    switch (state.code) {
      case 'not_registered':
        return t('errNotRegistered')
      case 'already_registered':
        return t('errAlreadyRegistered')
      case 'invalid_otp':
        return t('errInvalidOtp')
      case 'otp_expired':
        return t('errOtpExpired')
      case 'rate_limited':
        return t('errRateLimited', { n: state.retryAfter || RESEND_SECONDS })
      case 'too_many_attempts':
        return t('errTooManyAttempts')
      case 'no_channel':
        return t('errNoChannel')
      case 'phone_invalid':
        return t('errPhoneInvalid')
      case 'caregiver_invalid':
        return t('errCaregiverInvalid')
      case 'name_required':
        return t('errNameRequired')
      case 'session_expired':
        return t('errSessionExpired')
      default:
        return state.fallback || t('errorGeneric')
    }
  }

  function applyApiError(err) {
    const state = {
      code: err?.code || '',
      attemptsLeft: err?.attemptsLeft,
      retryAfter: err?.retryAfter,
      fallback: err instanceof Error ? err.message : errorMessage(err),
    }
    setError(state)
    if (state.code === 'rate_limited' && state.retryAfter) setCooldown(state.retryAfter)
    return state
  }

  async function handleDetailsSubmit(event) {
    event.preventDefault()
    setTouchedPhone(true)
    setError(null)

    if (!phoneValid) {
      setError({ code: 'phone_invalid' })
      return
    }
    if (mode === 'register') {
      if (!fullName.trim()) {
        setError({ code: 'name_required' })
        return
      }
      if (!caregiverValid) {
        setError({ code: 'caregiver_invalid' })
        return
      }
    }

    setBusy(true)
    try {
      const data =
        mode === 'register'
          ? await register({
              phone,
              full_name: fullName.trim(),
              preferred_lang: preferredLang,
              preferred_channel: preferredChannel,
              caregiver_phone: caregiver || undefined,
            })
          : await requestCode(phone)
      setInfo({ devCode: data?.dev_code || '', sentVia: data?.sent_via || '' })
      setDigits(Array(OTP_LENGTH).fill(''))
      setCooldown(RESEND_SECONDS)
      setError(null)
      setStep('otp')
    } catch (err) {
      const state = applyApiError(err)
      if (state.code === 'already_registered') setMode('signin')
    } finally {
      setBusy(false)
    }
  }

  async function handleVerify(event) {
    event.preventDefault()
    if (busy) return
    if (code.length !== OTP_LENGTH) {
      setError({ code: 'invalid_otp', attemptsLeft: null })
      setShake(true)
      window.setTimeout(() => setShake(false), 400)
      boxRefs.current[0]?.focus()
      return
    }
    setBusy(true)
    setError(null)
    try {
      await completeLogin({ phone, code })
      navigate(from, { replace: true })
    } catch (err) {
      const state = applyApiError(err)
      if (state.code === 'invalid_otp') {
        setDigits(Array(OTP_LENGTH).fill(''))
        setShake(true)
        window.setTimeout(() => setShake(false), 400)
        boxRefs.current[0]?.focus()
      }
      if (state.code === 'otp_expired' || state.code === 'too_many_attempts') {
        setDigits(Array(OTP_LENGTH).fill(''))
      }
    } finally {
      setBusy(false)
    }
  }

  async function handleResend() {
    if (busy || cooldown > 0) return
    setBusy(true)
    setError(null)
    try {
      const data = await requestCode(phone)
      setInfo({ devCode: data?.dev_code || '', sentVia: data?.sent_via || '' })
      setDigits(Array(OTP_LENGTH).fill(''))
      setCooldown(RESEND_SECONDS)
      boxRefs.current[0]?.focus()
    } catch (err) {
      applyApiError(err)
    } finally {
      setBusy(false)
    }
  }

  function setBox(index, value) {
    const digit = digitsOnly(value, 1)
    setDigits((current) => {
      const next = [...current]
      next[index] = digit
      return next
    })
    if (digit && index < OTP_LENGTH - 1) boxRefs.current[index + 1]?.focus()
  }

  function handleBoxChange(index, event) {
    // Pasting into a box is handled by onPaste; here keep the last digit.
    const raw = event.target.value
    if (raw.length > 1) {
      fillFromPaste(raw)
      return
    }
    setBox(index, raw)
  }

  function handleBoxKeyDown(index, event) {
    if (event.key === 'Backspace') {
      if (digits[index]) {
        setDigits((current) => {
          const next = [...current]
          next[index] = ''
          return next
        })
      } else if (index > 0) {
        event.preventDefault()
        setDigits((current) => {
          const next = [...current]
          next[index - 1] = ''
          return next
        })
        boxRefs.current[index - 1]?.focus()
      }
    } else if (event.key === 'ArrowLeft' && index > 0) {
      event.preventDefault()
      boxRefs.current[index - 1]?.focus()
    } else if (event.key === 'ArrowRight' && index < OTP_LENGTH - 1) {
      event.preventDefault()
      boxRefs.current[index + 1]?.focus()
    }
  }

  function fillFromPaste(raw) {
    const pasted = digitsOnly(raw, OTP_LENGTH)
    if (!pasted) return
    const next = Array(OTP_LENGTH).fill('')
    pasted.split('').forEach((digit, index) => {
      next[index] = digit
    })
    setDigits(next)
    const focusIndex = Math.min(pasted.length, OTP_LENGTH - 1)
    boxRefs.current[focusIndex]?.focus()
  }

  function handlePaste(event) {
    event.preventDefault()
    fillFromPaste(event.clipboardData?.getData('text') || '')
  }

  function useDevelopmentCode() {
    if (!info?.devCode) return
    fillFromPaste(info.devCode)
  }

  const errorText = messageFor(error)
  const isOtpError = error?.code === 'invalid_otp'
  const suggestRegister = error?.code === 'not_registered'
  const suggestSignIn = error?.code === 'already_registered'

  return (
    <div className="mx-auto max-w-xl space-y-6">
      <header className="space-y-2">
        <span className="chip">{t('appName')}</span>
        <h1 className="text-lg font-medium leading-tight text-cozy-white">
          {mode === 'register' ? t('registerTitle') : t('loginTitle')}
        </h1>
        <p className="text-sm leading-relaxed text-cozy-quiet">
          {mode === 'register' ? t('registerIntro') : t('loginIntro')}
        </p>
      </header>

      {/* expired-session banner */}
      {sessionNotice ? (
        <div role="status" className="alert-info flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-sm font-medium text-cozy-white">{t('sessionExpiredTitle')}</p>
            <p className="mt-1 text-xs text-cozy-quiet">{t('errSessionExpired')}</p>
          </div>
          <button type="button" className="btn-outlined btn-sm" onClick={clearSessionNotice}>
            {t('dismiss')}
          </button>
        </div>
      ) : null}

      {/* already signed in */}
      {isAuthed ? (
        <div className="card space-y-4">
          <p className="text-sm text-cozy-quiet">
            {t('signedInAs', { phone: patient?.phone || '' })}
          </p>
          <div className="flex flex-wrap gap-3">
            <Link to={from} className="btn-primary btn-sm">
              {t('home')}
            </Link>
            <button type="button" className="btn-outlined btn-sm" onClick={() => logout()}>
              {t('switchAccount')}
            </button>
          </div>
        </div>
      ) : null}

      {/* sign-in / register switcher */}
      <div className="flex items-center gap-1 rounded-md border border-cozy-border bg-cozy-card p-1">
        <button
          type="button"
          className={mode === 'signin' ? 'tab-active' : 'tab'}
          aria-pressed={mode === 'signin'}
          onClick={() => resetFlow('signin')}
        >
          {t('signIn')}
        </button>
        <button
          type="button"
          className={mode === 'register' ? 'tab-active' : 'tab'}
          aria-pressed={mode === 'register'}
          onClick={() => resetFlow('register')}
        >
          {t('createAccount')}
        </button>
      </div>

      {error ? (
        <div
          role="alert"
          className={`alert-error flex flex-wrap items-start justify-between gap-3 ${
            isOtpError || shake ? 'animate-shake border-cozy-white' : 'border-cozy-white'
          }`}
        >
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium text-cozy-white">{errorText}</p>
            {error.attemptsLeft != null ? (
              <p className="mt-1 text-xs text-cozy-quiet">
                {t('attemptsLeft', { n: error.attemptsLeft })}
              </p>
            ) : null}
            {suggestRegister ? (
              <button
                type="button"
                className="btn-primary btn-sm mt-3"
                onClick={() => resetFlow('register')}
              >
                {t('switchToRegister')}
              </button>
            ) : null}
            {suggestSignIn ? (
              <button
                type="button"
                className="btn-primary btn-sm mt-3"
                onClick={() => resetFlow('signin')}
              >
                {t('switchToSignIn')}
              </button>
            ) : null}
          </div>
          <button
            type="button"
            className="btn-quiet btn-sm"
            onClick={() => setError(null)}
            aria-label={t('dismiss')}
          >
            ✕
          </button>
        </div>
      ) : null}

      {step === 'details' ? (
        <form className="card space-y-5" onSubmit={handleDetailsSubmit} noValidate>
          <div>
            <label className="label" htmlFor="auth-phone">
              {mode === 'register' ? t('mobileLabel') : t('phoneLabel')}
            </label>
            <div className="flex items-stretch gap-2">
              <span className="inline-flex items-center rounded-md border border-cozy-border bg-cozy-elevated px-3 text-sm text-cozy-quiet">
                +91
              </span>
              <input
                id="auth-phone"
                name="phone"
                type="tel"
                inputMode="numeric"
                autoComplete="tel-national"
                className={`input ${touchedPhone && !phoneValid ? 'border-cozy-white' : ''}`}
                value={phone}
                placeholder="98765 43210"
                onChange={(event) => setPhone(digitsOnly(event.target.value))}
                onBlur={() => setTouchedPhone(true)}
                aria-invalid={touchedPhone && !phoneValid}
                aria-describedby="phone-hint"
                disabled={busy}
              />
            </div>
            <p id="phone-hint" className="mt-1 text-xs text-cozy-subtle">
              {touchedPhone && !phoneValid ? (
                <span className="text-cozy-white">{t('errPhoneInvalid')}</span>
              ) : (
                t('mobileHint')
              )}
            </p>
          </div>

          {mode === 'register' ? (
            <>
              <div>
                <label className="label" htmlFor="auth-name">
                  {t('fullNameLabel')}
                </label>
                <input
                  id="auth-name"
                  name="full_name"
                  className="input"
                  autoComplete="name"
                  value={fullName}
                  placeholder={t('fullNamePlaceholder')}
                  onChange={(event) => setFullName(event.target.value)}
                  disabled={busy}
                />
              </div>

              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <label className="label" htmlFor="auth-lang">
                    {t('preferredLangLabel')}
                  </label>
                  <select
                    id="auth-lang"
                    className="input"
                    value={preferredLang}
                    onChange={(event) => setPreferredLang(event.target.value)}
                    disabled={busy}
                  >
                    {REGISTER_LANGS.map((option) => (
                      <option key={option.code} value={option.code}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="label" htmlFor="auth-channel">
                    {t('preferredChannelLabel')}
                  </label>
                  <select
                    id="auth-channel"
                    className="input"
                    value={preferredChannel}
                    onChange={(event) => setPreferredChannel(event.target.value)}
                    disabled={busy}
                  >
                    {REGISTER_CHANNELS.map((option) => (
                      <option key={option.code} value={option.code}>
                        {t(option.key)}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div>
                <label className="label" htmlFor="auth-caregiver">
                  {t('caregiverLabel')}{' '}
                  <span className="text-xs text-cozy-subtle">({t('optional')})</span>
                </label>
                <input
                  id="auth-caregiver"
                  name="caregiver_phone"
                  type="tel"
                  inputMode="numeric"
                  className={`input ${!caregiverValid ? 'border-cozy-white' : ''}`}
                  value={caregiver}
                  placeholder={t('caregiverPlaceholder')}
                  onChange={(event) => setCaregiver(digitsOnly(event.target.value))}
                  aria-describedby="caregiver-hint"
                  disabled={busy}
                />
                <p id="caregiver-hint" className="mt-1 text-xs text-cozy-subtle">
                  {!caregiverValid ? (
                    <span className="text-cozy-white">{t('errCaregiverInvalid')}</span>
                  ) : (
                    t('caregiverHint')
                  )}
                </p>
              </div>

              <button type="submit" className="btn-primary w-full" disabled={busy}>
                {busy ? t('loading') : t('registerButton')}
              </button>

              <p className="text-center text-sm text-cozy-quiet">
                {t('haveAccount')}{' '}
                <button
                  type="button"
                  className="link font-medium"
                  onClick={() => resetFlow('signin')}
                >
                  {t('switchToSignIn')}
                </button>
              </p>
            </>
          ) : (
            <>
              <p className="text-xs text-cozy-subtle">{t('otpNoPassword')}</p>
              <button type="submit" className="btn-primary w-full" disabled={busy}>
                {busy ? t('loading') : t('sendCode')}
              </button>
              <p className="text-center text-sm text-cozy-quiet">
                {t('noAccount')}{' '}
                <button
                  type="button"
                  className="link font-medium"
                  onClick={() => resetFlow('register')}
                >
                  {t('switchToRegister')}
                </button>
              </p>
            </>
          )}
        </form>
      ) : (
        <form className="card space-y-5" onSubmit={handleVerify}>
          <div>
            <h2 className="text-base font-medium text-cozy-white">{t('otpTitle')}</h2>
            <p className="mt-1 text-sm text-cozy-quiet">
              {t('otpIntro', { phone: `+91 ${phone}` })}
            </p>
            {info?.sentVia ? (
              <p className="mt-1 text-xs text-cozy-subtle">
                {t('codeSentVia', {
                  channel:
                    info.sentVia === 'sms' ? t('codeSentSms') : t('codeSentWhatsapp'),
                })}
              </p>
            ) : null}
          </div>

          <fieldset>
            <legend className="label">{t('otpBoxLabel')}</legend>
            <div
              className={`flex justify-between gap-2 ${shake ? 'animate-shake' : ''}`}
              onPaste={handlePaste}
            >
              {digits.map((digit, index) => (
                <input
                  key={index}
                  ref={(element) => {
                    boxRefs.current[index] = element
                  }}
                  className={`otp-box ${isOtpError ? 'otp-box-error border-cozy-white' : ''}`}
                  type="text"
                  inputMode="numeric"
                  autoComplete={index === 0 ? 'one-time-code' : 'off'}
                  maxLength={1}
                  value={digit}
                  aria-label={`${t('otpBoxLabel')} ${index + 1}`}
                  aria-invalid={isOtpError}
                  onChange={(event) => handleBoxChange(index, event)}
                  onKeyDown={(event) => handleBoxKeyDown(index, event)}
                  onFocus={(event) => event.target.select()}
                  disabled={busy}
                />
              ))}
            </div>
          </fieldset>

          {info?.devCode ? (
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-cozy-border bg-cozy-input p-3">
              <p className="text-xs text-cozy-quiet">
                {t('devCodeHint', { code: info.devCode })}
              </p>
              <button type="button" className="btn-outlined btn-sm" onClick={useDevelopmentCode}>
                {t('useDevCode')}
              </button>
            </div>
          ) : null}

          {error?.code === 'otp_expired' ? (
            <p className="text-xs text-cozy-white">{t('otpExpiredResend')}</p>
          ) : null}

          <button type="submit" className="btn-primary w-full" disabled={busy || code.length !== OTP_LENGTH}>
            {busy ? t('loading') : t('verifyCode')}
          </button>

          <div className="flex flex-wrap items-center justify-between gap-3">
            <button
              type="button"
              className="btn-quiet btn-sm"
              onClick={() => resetFlow(mode)}
              disabled={busy}
            >
              ← {t('changeDetails')}
            </button>
            <button
              type="button"
              className="btn-outlined btn-sm"
              onClick={handleResend}
              disabled={busy || cooldown > 0}
            >
              {cooldown > 0 ? t('resendCountdown', { n: cooldown }) : t('resendCode')}
            </button>
          </div>
        </form>
      )}
    </div>
  )
}
