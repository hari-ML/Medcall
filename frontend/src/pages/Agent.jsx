import React, { useEffect, useRef, useState } from 'react'
import { agentChat, agentSuggestions, errorMessage } from '../api'
import { useI18n } from '../i18n'

/**
 * Care agent screen (Phase 7): a chat over the patient's OWN verified
 * timetable. The backend composes every answer (deterministic, en/ta/hi) and
 * marks it with `escalate` / `safety_blocked` / `disclaimer` / `sources`.
 *
 * SAFETY (client side): this page only renders what the API returns — it
 * never composes medical text, never fills in a dose/time, and always shows
 * the backend's disclaimer. Escalation and refusals get prominent banners.
 */
export default function Agent() {
  const { t, lang } = useI18n()
  const [messages, setMessages] = useState([])
  const [suggestions, setSuggestions] = useState([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const bottomRef = useRef(null)

  useEffect(() => {
    let cancelled = false
    agentSuggestions(lang)
      .then((data) => {
        if (!cancelled) setSuggestions(data?.suggestions || [])
      })
      .catch(() => {
        if (!cancelled) setSuggestions([]) // suggestions are a nicety, not a requirement
      })
    return () => {
      cancelled = true
    }
  }, [lang])

  useEffect(() => {
    bottomRef.current?.scrollIntoView?.({ block: 'nearest' })
  }, [messages])

  async function send(text) {
    const message = String(text || '').trim()
    if (!message || busy) return
    setInput('')
    setError(null)
    setBusy(true)
    setMessages((prev) => [...prev, { role: 'you', text: message }])
    try {
      const answer = await agentChat(message, lang)
      setMessages((prev) => [...prev, { role: 'agent', answer }])
    } catch (err) {
      setError(errorMessage(err) || t('errorGeneric'))
    } finally {
      setBusy(false)
    }
  }

  function handleSubmit(event) {
    event.preventDefault()
    send(input)
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-slate-800">{t('agentTitle')}</h1>
        <p className="mt-2 text-lg leading-relaxed text-slate-600">{t('agentIntro')}</p>
      </div>

      {/* conversation */}
      <section className="card min-h-[16rem] space-y-4">
        {messages.length === 0 ? (
          <p className="py-6 text-center text-slate-500">{t('agentEmpty')}</p>
        ) : null}

        {messages.map((message, index) =>
          message.role === 'you' ? (
            <div key={index} className="flex justify-end">
              <div className="max-w-[85%] rounded-2xl rounded-br-sm bg-brand-700 px-4 py-3 text-white">
                <div className="mb-1 text-sm font-semibold opacity-80">{t('agentYou')}</div>
                <p className="whitespace-pre-wrap">{message.text}</p>
              </div>
            </div>
          ) : (
            <div key={index} className="flex justify-start">
              <div className="max-w-[95%] space-y-2 rounded-2xl rounded-bl-sm border border-slate-200 bg-slate-50 px-4 py-3">
                <div className="text-sm font-semibold text-slate-500">{t('appName')}</div>

                {message.answer?.escalate ? (
                  <div role="alert" className="rounded-xl border-2 border-red-300 bg-red-50 p-3 font-semibold text-red-800">
                    🚨 {t('agentEscalate')}
                  </div>
                ) : null}

                {message.answer?.safety_blocked ? (
                  <div className="rounded-xl border-2 border-amber-300 bg-amber-50 p-3 font-semibold text-amber-900">
                    🛑 {t('agentBlockedNote')}
                  </div>
                ) : null}

                <p className="whitespace-pre-wrap text-slate-800">{message.answer?.reply}</p>

                {message.answer?.sources?.length ? (
                  <p className="text-sm text-slate-500">
                    {t('agentSources')}{' '}
                    {message.answer.sources.map((source) => source.medicine).join(' · ')}
                  </p>
                ) : null}

                {message.answer?.disclaimer ? (
                  <p className="border-t border-slate-200 pt-2 text-sm italic text-slate-500">
                    {message.answer.disclaimer}
                  </p>
                ) : null}
              </div>
            </div>
          ),
        )}

        {busy ? (
          <p className="text-slate-500" role="status">
            {t('loading')}
          </p>
        ) : null}
        <div ref={bottomRef} />
      </section>

      {error ? (
        <div role="alert" className="rounded-card border-2 border-red-300 bg-red-50 p-4 text-red-800">
          {error}
        </div>
      ) : null}

      {/* suggestions */}
      {suggestions.length ? (
        <div className="flex flex-wrap gap-2">
          <span className="self-center text-sm font-semibold text-slate-500">
            {t('agentSuggestions')}
          </span>
          {suggestions.map((question) => (
            <button
              key={question}
              type="button"
              className="chip hover:bg-brand-50"
              onClick={() => send(question)}
            >
              {question}
            </button>
          ))}
        </div>
      ) : null}

      {/* composer */}
      <form onSubmit={handleSubmit} className="flex flex-wrap gap-3">
        <label htmlFor="agent-input" className="sr-only">
          {t('agentPlaceholder')}
        </label>
        <input
          id="agent-input"
          type="text"
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder={t('agentPlaceholder')}
          maxLength={500}
          className="input flex-1"
        />
        <button type="submit" className="btn-primary" disabled={busy || !input.trim()}>
          {busy ? t('loading') : t('agentSend')}
        </button>
      </form>
    </div>
  )
}
