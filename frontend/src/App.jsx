import React from 'react'
import { Route, Routes } from 'react-router-dom'
import { LangProvider } from './i18n'
import { AuthProvider, RequireAuth, useAuth } from './auth'
import Header from './components/Header'
import Disclaimer from './components/Disclaimer'
import BottomNav from './components/BottomNav'
import Home from './pages/Home'
import Login from './pages/Login'
import Upload from './pages/Upload'
import Review from './pages/Review'
import Language from './pages/Language'
import Timetable from './pages/Timetable'
import Reminders from './pages/Reminders'
import Agent from './pages/Agent'
import NotFound from './pages/NotFound'

/**
 * App shell: language provider → auth provider → header (logo + nav +
 * language switcher) → routed pages → persistent disclaimer footer, with the
 * floating bottom navigation shown once signed in.
 *
 * Routes:
 *   /                 Home        — next dose + adherence + entry points
 *   /login            Login       — phone + OTP, sign-in / register switcher
 *   /register         Login       — same screen, register mode
 *   /upload           Upload      — camera/gallery/PDF + demo alternative
 *   /review/:id       Review      — extracted lines, confirm/edit unclear ones
 *   /language/:id     Language    — pick English / தமிழ் / हिन्दी
 *   /timetable/:id    Timetable   — 4-slot schedule, search, reminders, PDF
 *   /reminders        Reminders   — consent switches, test send, history
 *   /agent            Agent       — grounded chat over the verified timetable
 *   *                 NotFound    — 404 screen
 *
 * Everything except /login, /register and the 404 page requires a session.
 * `initialSession` is the SSR/verification seam (mirrors `initialLang`).
 */
function Shell() {
  const { isAuthed } = useAuth()

  return (
    <div className="flex min-h-screen flex-col bg-cozy-canvas">
      <Header />
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 pb-14 pt-8 md:pb-8">
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Login initialMode="register" />} />
          <Route
            path="/"
            element={
              <RequireAuth>
                <Home />
              </RequireAuth>
            }
          />
          <Route
            path="/upload"
            element={
              <RequireAuth>
                <Upload />
              </RequireAuth>
            }
          />
          <Route
            path="/review/:id"
            element={
              <RequireAuth>
                <Review />
              </RequireAuth>
            }
          />
          <Route
            path="/language/:id"
            element={
              <RequireAuth>
                <Language />
              </RequireAuth>
            }
          />
          <Route
            path="/timetable/:id"
            element={
              <RequireAuth>
                <Timetable />
              </RequireAuth>
            }
          />
          <Route
            path="/reminders"
            element={
              <RequireAuth>
                <Reminders />
              </RequireAuth>
            }
          />
          <Route
            path="/agent"
            element={
              <RequireAuth>
                <Agent />
              </RequireAuth>
            }
          />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>
      <Disclaimer />
      {isAuthed ? <BottomNav /> : null}
    </div>
  )
}

export default function App({ initialLang, initialSession }) {
  return (
    <LangProvider initialLang={initialLang}>
      <AuthProvider initialSession={initialSession}>
        <Shell />
      </AuthProvider>
    </LangProvider>
  )
}
