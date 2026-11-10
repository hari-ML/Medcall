/**
 * MedRecall API client (axios).
 * All calls go through the Vite dev proxy (/api -> http://localhost:8000),
 * so no CORS handling is needed in the browser.
 */
import axios from 'axios'

const client = axios.create({
  baseURL: '/api',
  timeout: 120000,
})

// ---------------------------------------------------------------------------
// Auth injection (Phase 7).
// The AuthProvider registers a bridge here so api.js never imports auth.jsx
// (no circular import): every request gets the current access token, and a
// 401 on a protected route triggers ONE silent refresh + retry before the
// session is declared lost.
// ---------------------------------------------------------------------------

let authBridge = null

export function attachAuthBridge(bridge) {
  authBridge = bridge
}

client.interceptors.request.use((config) => {
  const token = authBridge?.getAccessToken?.()
  if (token) config.headers = { ...config.headers, Authorization: `Bearer ${token}` }
  return config
})

client.interceptors.response.use(
  (response) => response,
  async (error) => {
    const config = error?.config
    const status = error?.response?.status
    const url = String(config?.url || '')
    const isAuthFlow = url.includes('/auth/') // bad OTP/refresh must surface as-is
    if (status === 401 && config && !config._retried && !isAuthFlow && authBridge) {
      config._retried = true
      try {
        await authBridge.refreshAccessToken()
        config.headers = {
          ...config.headers,
          Authorization: `Bearer ${authBridge.getAccessToken() || ''}`,
        }
        return client(config)
      } catch {
        authBridge.sessionLost?.()
      }
    }
    return Promise.reject(error)
  },
)

/** Extract the backend's {"detail": "..."} message (or a friendly fallback). */
export function errorMessage(error) {
  const detail = error?.response?.data?.detail
  if (typeof detail === 'string' && detail.trim()) return detail
  if (Array.isArray(detail) && detail.length) {
    // fastapi validation errors: [{loc, msg, ...}]
    return detail.map((d) => d?.msg || '').filter(Boolean).join('; ') || null
  }
  if (error?.message === 'Network Error') return null // caller shows generic
  return null
}

export class ApiError extends Error {
  constructor(message, status, raw) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.raw = raw
  }
}

function throwApiError(error) {
  const message = errorMessage(error)
  const status = error?.response?.status ?? 0
  throw new ApiError(message || 'Something went wrong. Please try again.', status, error)
}

/** Upload a prescription file with progress reporting (0-100). */
export async function uploadPrescription(file, onProgress) {
  const form = new FormData()
  form.append('file', file)
  try {
    const response = await client.post('/prescriptions', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: (event) => {
        if (!onProgress) return
        const pct = event.total ? Math.round((event.loaded * 100) / event.total) : 0
        onProgress(pct)
      },
    })
    return response.data
  } catch (error) {
    throwApiError(error)
  }
}

/** Prefilled demo prescription (no OCR, works with zero dependencies). */
export async function createDemo() {
  try {
    const response = await client.post('/demo')
    return response.data
  } catch (error) {
    throwApiError(error)
  }
}

export async function getPrescription(id) {
  try {
    const response = await client.get(`/prescriptions/${id}`)
    return response.data
  } catch (error) {
    throwApiError(error)
  }
}

export async function confirmItem(prescriptionId, itemId) {
  try {
    const response = await client.patch(
      `/prescriptions/${prescriptionId}/items/${itemId}`,
      { action: 'confirm' },
    )
    return response.data
  } catch (error) {
    throwApiError(error)
  }
}

export async function editItem(prescriptionId, itemId, fields) {
  try {
    const response = await client.patch(
      `/prescriptions/${prescriptionId}/items/${itemId}`,
      { action: 'edit', fields },
    )
    return response.data
  } catch (error) {
    throwApiError(error)
  }
}

export async function getSchedule(prescriptionId, lang = 'en') {
  try {
    const response = await client.post(`/prescriptions/${prescriptionId}/schedule`, null, {
      params: { lang },
    })
    return response.data
  } catch (error) {
    throwApiError(error)
  }
}

export async function getReminders(prescriptionId, lang = 'en') {
  try {
    const response = await client.get(`/prescriptions/${prescriptionId}/reminders`, {
      params: { lang },
    })
    return response.data
  } catch (error) {
    throwApiError(error)
  }
}

/** URL for the printable PDF (open in a new tab / print dialog). */
export function timetablePdfUrl(prescriptionId, lang = 'en') {
  return `/api/prescriptions/${prescriptionId}/timetable.pdf?lang=${encodeURIComponent(lang)}`
}

export async function getHealth() {
  try {
    const response = await client.get('/health')
    return response.data
  } catch (error) {
    throwApiError(error)
  }
}

/** Base URL for uploaded prescription images (proxied to the backend). */
export const UPLOADS_BASE = '/uploads'

// ---------------------------------------------------------------------------
// Auth (Phase 7): phone + OTP login, session refresh, profile, consent
// ---------------------------------------------------------------------------

/** Request a one-time code (dev mode returns it as `dev_code`). */
export async function requestOtp(phone) {
  try {
    const response = await client.post('/auth/otp/request', { phone })
    return response.data
  } catch (error) {
    throwApiError(error)
  }
}

/** Verify the code → access token (+ patient on first login). */
export async function verifyOtp({ phone, code, full_name: fullName }) {
  try {
    const response = await client.post('/auth/otp/verify', {
      phone,
      code,
      ...(fullName ? { full_name: fullName } : {}),
    })
    return response.data
  } catch (error) {
    throwApiError(error)
  }
}

/** Rotate the refresh cookie into a fresh access token (401 if none/invalid). */
export async function refreshSession() {
  try {
    const response = await client.post('/auth/refresh', null, { withCredentials: true })
    return response.data
  } catch (error) {
    throwApiError(error)
  }
}

/** End the session server-side (consumes the refresh cookie). */
export async function logoutSession() {
  try {
    await client.post('/auth/logout', null, { withCredentials: true })
  } catch (error) {
    throwApiError(error)
  }
}

export async function getProfile() {
  try {
    const response = await client.get('/patients/me')
    return response.data
  } catch (error) {
    throwApiError(error)
  }
}

export async function updateProfile(fields) {
  try {
    const response = await client.patch('/patients/me', fields)
    return response.data
  } catch (error) {
    throwApiError(error)
  }
}

export async function getConsent() {
  try {
    const response = await client.get('/patients/me/consent')
    return response.data
  } catch (error) {
    throwApiError(error)
  }
}

export async function setConsent(channel, granted) {
  try {
    const response = await client.post('/patients/me/consent', { channel, granted })
    return response.data
  } catch (error) {
    throwApiError(error)
  }
}

// ---------------------------------------------------------------------------
// Reminders (Phase 3 API, wired to the UI in Phase 7)
// ---------------------------------------------------------------------------

/** Start the reminder engine for one prescription (idempotent server-side). */
export async function enrollReminders(prescriptionId) {
  try {
    const response = await client.post(`/prescriptions/${prescriptionId}/reminders/enroll`)
    return response.data
  } catch (error) {
    throwApiError(error)
  }
}

/** Stop the reminder engine (history is kept server-side). */
export async function unenrollReminders(prescriptionId) {
  try {
    await client.delete(`/prescriptions/${prescriptionId}/reminders/enroll`)
  } catch (error) {
    throwApiError(error)
  }
}

/** Upcoming occurrences (patient-local times) — returns a list. */
export async function getUpcoming(days = 7) {
  try {
    const response = await client.get('/reminders/upcoming', { params: { days } })
    return response.data
  } catch (error) {
    throwApiError(error)
  }
}

/** Past occurrences (sent / blocked / failed / missed) — returns a list. */
export async function getHistory() {
  try {
    const response = await client.get('/reminders/history')
    return response.data
  } catch (error) {
    throwApiError(error)
  }
}

/** One manual generate + dispatch tick (returns counts). */
export async function runReminders() {
  try {
    const response = await client.post('/reminders/run')
    return response.data
  } catch (error) {
    throwApiError(error)
  }
}

// ---------------------------------------------------------------------------
// Care agent (Phase 5 API, wired to the UI in Phase 7)
// ---------------------------------------------------------------------------

/** Grounded answer from the caller's own verified timetable. */
export async function agentChat(message, lang) {
  try {
    const response = await client.post('/agent/chat', lang ? { message, lang } : { message })
    return response.data
  } catch (error) {
    throwApiError(error)
  }
}

export async function agentSuggestions(lang) {
  try {
    const response = await client.get('/agent/suggestions', { params: { lang } })
    return response.data
  } catch (error) {
    throwApiError(error)
  }
}
