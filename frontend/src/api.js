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
