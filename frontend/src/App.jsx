import React from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { LangProvider } from './i18n'
import Header from './components/Header'
import Disclaimer from './components/Disclaimer'
import Home from './pages/Home'
import Upload from './pages/Upload'
import Review from './pages/Review'
import Language from './pages/Language'
import Timetable from './pages/Timetable'

/**
 * App shell: language provider → header (logo + language switcher) →
 * routed pages → persistent disclaimer footer on every screen.
 *
 * Routes:
 *   /                 Home        — next dose + today's progress + entry points
 *   /upload           Upload      — photo/PDF drop zone (or demo)
 *   /review/:id       Review      — extracted lines, confirm/edit unclear ones
 *   /language/:id     Language    — pick English / தமிழ் / हिन्दी
 *   /timetable/:id    Timetable   — 4-slot schedule, reminders, printable PDF
 */
export default function App({ initialLang }) {
  return (
    <LangProvider initialLang={initialLang}>
      <div className="flex min-h-screen flex-col">
        <Header />
        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8">
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/upload" element={<Upload />} />
            <Route path="/review/:id" element={<Review />} />
            <Route path="/language/:id" element={<Language />} />
            <Route path="/timetable/:id" element={<Timetable />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
        <Disclaimer />
      </div>
    </LangProvider>
  )
}
