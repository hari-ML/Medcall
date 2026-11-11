import React, { useEffect, useRef, useState } from 'react'
import { agentChat, agentSuggestions, errorMessage } from '../api'
import { useI18n } from '../i18n'

/**
 * Care agent screen (Cozy design system): a live chat over the patient's OWN
 * verified timetable. The backend composes every answer (deterministic,
 * en/ta/hi, optional guarded LLM) and marks it with `escalate` /
 * `safety_blocked` / `disclaimer` / `sources`.
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
  }, [messages, busy])

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
      <header>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-lg font-medium leading-tight text-cozy-white">{t('agentTitle')}</h1>
          <span className="chip">
            <span aria-hidden="true" className="h-2 w-2 rounded-full bg-cozy-white" />
            {t('liveChat')}
          </span>
        </div>
        <p className="mt-2 text-sm leading-relaxed text-cozy-quiet">{t('agentIntro')}</p>
        <p className="mt-2 text-xs text-cozy-subtle">{t('agentLiveHint')}</p>
      </header>

      {/* conversation */}
      <section className="card min-h-[18rem] space-y-4">
        {messages.length === 0 ? (
          <p className="py-8 text-center text-sm text-cozy-quiet">{t('agentEmpty')}</p>
        ) : null}

        {messages.map((message, index) =>
          message.role === 'you' ? (
            <div key={index} className="flex justify-end">
              <div className="max-w-[85%] rounded-lg rounded-br-sm bg-cozy-white px-4 py-3 text-cozy-canvas shadow-sm">
                <div className="mb-1 text-xs font-medium opacity-70">{t('agentYou')}</div>
                <p className="whitespace-pre-wrap text-sm leading-relaxed">{message.text}</p>
              </div>
            </div>
          ) : (
            <div key={index} className="flex justify-start">
              <div className="max-w-[95%] space-y-2 rounded-lg rounded-bl-sm border border-cozy-border bg-cozy-elevated px-4 py-3">
                <div className="text-xs font-medium text-cozy-quiet">{t('appName')}</div>

                {message.answer?.escalate ? (
                  <div
                    role="alert"
                    className="rounded-md border border-cozy-white bg-cozy-card p-3 text-sm font-medium text-cozy-white"
                  >
                    {t('agentEscalate')}
                  </div>
                ) : null}

                {message.answer?.safety_blocked ? (
                  <div className="rounded-md border border-cozy-borderStrong bg-cozy-card p-3 text-sm text-cozy-quiet">
                    {t('agentBlockedNote')}
                  </div>
                ) : null}

                <p className="whitespace-pre-wrap text-sm leading-relaxed text-cozy-white">
                  {message.answer?.reply}
                </p>

                {message.answer?.sources?.length ? (
                  <p className="text-xs text-cozy-subtle">
                    {t('agentSources')}{' '}
                    {message.answer.sources.map((source) => source.medicine).join(' · ')}
                  </p>
                ) : null}

                {message.answer?.disclaimer ? (
                  <p className="border-t border-cozy-border pt-2 text-xs italic text-cozy-quiet">
                    {message.answer.disclaimer}
                  </p>
                ) : null}
              </div>
            </div>
          ),
        )}

        {busy ? (
          <div className="flex justify-start" role="status" aria-live="polite">
            <p className="rounded-full border border-cozy-border bg-cozy-input px-4 py-2 text-xs text-cozy-quiet">
              {t('agentTyping')}
            </p>
          </div>
        ) : null}
        <div ref={bottomRef} />
      </section>

      {error ? (
        <div role="alert" className="alert-error text-sm">
          {error}
        </div>
      ) : null}

      {/* suggestions */}
      {suggestions.length ? (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-cozy-subtle">{t('agentSuggestions')}</span>
          {suggestions.map((question) => (
            <button
              key={question}
              type="button"
              className="chip transition-colors duration-fast ease-cozy hover:border-cozy-white hover:text-cozy-white"
              onClick={() => send(question)}
              disabled={busy}
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
