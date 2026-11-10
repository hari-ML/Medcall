import React from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { LangProvider } from './i18n'
import { AuthProvider, RequireAuth } from './auth'
import Header from './components/Header'
import Disclaimer from './components/Disclaimer'
import Home from './pages/Home'
import Login from './pages/Login'
import Upload from './pages/Upload'
import Review from './pages/Review'
import Language from './pages/Language'
import Timetable from './pages/Timetable'
import Reminders from './pages/Reminders'
import Agent from './pages/Agent'

/**
 * App shell: language provider → auth provider → header (logo + nav +
 * language switcher) → routed pages → persistent disclaimer footer.
 *
 * Routes:
 *   /                 Home        — next dose + today's progress + entry points
 *   /login            Login       — phone + OTP sign-in (public)
 *   /upload           Upload      — photo/PDF drop zone (or demo)
 *   /review/:id       Review      — extracted lines, confirm/edit unclear ones
 *   /language/:id     Language    — pick English / தமிழ் / हिन्दी
 *   /timetable/:id    Timetable   — 4-slot schedule, reminders, printable PDF
 *   /reminders        Reminders   — consent switches, upcoming + delivery history
 *   /agent            Agent       — grounded chat over the verified timetable
 *
 * Everything except /login requires a session (phone + OTP, Phase 2).
 * `initialSession` is the SSR/verification seam (mirrors `initialLang`).
 */
export default function App({ initialLang, initialSession }) {
  return (
    <LangProvider initialLang={initialLang}>
      <AuthProvider initialSession={initialSession}>
        <div className="flex min-h-screen flex-col">
          <Header />
          <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8">
            <Routes>
              <Route path="/login" element={<Login />} />
              <Route path="/" element={<RequireAuth><Home /></RequireAuth>} />
              <Route path="/upload" element={<RequireAuth><Upload /></RequireAuth>} />
              <Route path="/review/:id" element={<RequireAuth><Review /></RequireAuth>} />
              <Route path="/language/:id" element={<RequireAuth><Language /></RequireAuth>} />
              <Route path="/timetable/:id" element={<RequireAuth><Timetable /></RequireAuth>} />
              <Route path="/reminders" element={<RequireAuth><Reminders /></RequireAuth>} />
              <Route path="/agent" element={<RequireAuth><Agent /></RequireAuth>} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </main>
          <Disclaimer />
        </div>
      </AuthProvider>
    </LangProvider>
  )
}
