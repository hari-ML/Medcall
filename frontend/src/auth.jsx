/**
 * MedRecall session layer (Phase 7): phone + OTP login, token persistence,
 * silent refresh, and route protection.
 *
 * - The access token lives in localStorage (`medrecall:session`); the rotating
 *   refresh token stays in the backend's httpOnly cookie (path /api/auth), so
 *   XSS can read only the short-lived access token.
 * - api.js gets the token through a registered bridge (no circular import)
 *   and performs ONE silent refresh + retry when a protected call 401s.
 * - SSR / verification renders pass `initialSession` to <App> (the same seam
 *   `initialLang` already provides), so server rendering never touches
 *   localStorage and never redirects.
 *
 * SAFETY: this layer only handles identity. It never touches item statuses,
 * never builds instructions and sends no medical content anywhere.
 */
import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import {
  attachAuthBridge,
  getProfile,
  logoutSession,
  refreshSession,
  requestOtp,
  verifyOtp,
} from './api'

const STORAGE_KEY = 'medrecall:session'
const AuthContext = createContext(null)

function readStoredSession() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    const parsed = raw ? JSON.parse(raw) : null
    return parsed && typeof parsed.access_token === 'string' ? parsed : null
  } catch {
    return null // localStorage unavailable (SSR) or corrupt data
  }
}

function writeStoredSession(session) {
  try {
    if (session) localStorage.setItem(STORAGE_KEY, JSON.stringify(session))
    else localStorage.removeItem(STORAGE_KEY)
  } catch {
    /* ignore */
  }
}

function withToken(session, data) {
  return {
    ...session,
    access_token: data.access_token,
    expires_at: Date.now() + (data.expires_in || 0) * 1000,
  }
}

/** Sensible no-op defaults so components render outside the provider (SSR). */
const FALLBACK = {
  session: null,
  patient: null,
  isAuthed: false,
  requestCode: async () => ({ message: '', expires_in: 0 }),
  completeLogin: async () => null,
  logout: async () => {},
}

export function AuthProvider({ children, initialSession }) {
  const [session, setSession] = useState(() => {
    if (initialSession) return initialSession // explicit override (tests / SSR)
    return readStoredSession()
  })

  const applySession = useCallback((next) => {
    setSession(next)
    writeStoredSession(next)
  }, [])

  // Register the api.js bridge: token getter + silent refresh + session-lost.
  useEffect(() => {
    attachAuthBridge({
      getAccessToken: () => session?.access_token || null,
      refreshAccessToken: async () => {
        const data = await refreshSession() // throws when the cookie is invalid
        setSession((prev) => {
          if (!prev) return prev
          const next = withToken(prev, data)
          writeStoredSession(next)
          return next
        })
      },
      sessionLost: () => setSession(null),
    })
    return () => attachAuthBridge(null)
  }, [session])

  // Expired token on first client render → try the refresh cookie once.
  useEffect(() => {
    if (!session?.access_token || session.expires_at == null) return
    if (Date.now() < session.expires_at - 60_000) return
    refreshSession()
      .then((data) => setSession((prev) => (prev ? withToken(prev, data) : prev)))
      .catch(() => {
        /* no valid cookie → the route guard will send the user to /login */
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const requestCode = useCallback(async (phone) => requestOtp(phone), [])

  const completeLogin = useCallback(
    async ({ phone, code, full_name: fullName }) => {
      const data = await verifyOtp({ phone, code, full_name: fullName })
      let patient = data.patient || null
      if (!patient) patient = await getProfile() // TokenOut-shaped response
      applySession({
        access_token: data.access_token,
        expires_at: Date.now() + (data.expires_in || 0) * 1000,
        patient,
      })
      return patient
    },
    [applySession],
  )

  const logout = useCallback(async () => {
    try {
      await logoutSession()
    } catch {
      /* already invalid — clear locally regardless */
    }
    applySession(null)
  }, [applySession])

  const value = useMemo(
    () => ({
      session,
      patient: session?.patient || null,
      isAuthed: Boolean(session?.access_token),
      requestCode,
      completeLogin,
      logout,
    }),
    [session, requestCode, completeLogin, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

/** Never throws outside the provider (Header is also rendered standalone). */
export function useAuth() {
  return useContext(AuthContext) || FALLBACK
}

/** Redirect to /login (remembering where the user was headed). */
export function RequireAuth({ children }) {
  const { isAuthed } = useAuth()
  const location = useLocation()
  if (!isAuthed) {
    return <Navigate to="/login" state={{ from: location.pathname + location.search }} replace />
  }
  return children
}
