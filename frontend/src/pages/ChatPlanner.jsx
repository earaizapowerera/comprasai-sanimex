import { useEffect, useRef, useState } from 'react'
import { useChatStream } from '../hooks/useChatStream.js'
import { IconSparkleChat, IconSend } from '../components/icons.jsx'
import './ChatPlanner.css'

const SUGGESTIONS = [
  '¿Qué SKU debo comprar con más urgencia esta semana?',
  '¿Qué sucursales tienen sobreinventario en Piso Porcelanato?',
  '¿Cuáles son los productos con más venta acumulada?',
  '¿Por qué se sugiere comprar el material PORC-NOGAL-60?',
]

export default function ChatPlanner() {
  const { messages, isStreaming, toolStatus, send } = useChatStream()
  const [draft, setDraft] = useState('')
  const panelRef = useRef(null)
  const inputRef = useRef(null)

  useEffect(() => {
    const el = panelRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages, toolStatus])

  function handleSubmit(e) {
    e.preventDefault()
    const text = draft
    if (!text.trim() || isStreaming) return
    setDraft('')
    send(text)
    // Mantener el foco en el composer tras enviar (accesibilidad §5 UX-SPEC).
    requestAnimationFrame(() => inputRef.current?.focus())
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit(e)
    }
  }

  function handleSuggestion(text) {
    if (isStreaming) return
    send(text)
  }

  return (
    <>
      <header className="app-page-header">
        <h1 className="h1 app-page-header__title">
          Chat del Planeador <span aria-hidden="true">✨</span>
        </h1>
        <p className="app-page-header__subtitle">
          Pregúntale a tus datos en lenguaje natural — inventario, cobertura, ventas y sugeridos.
        </p>
      </header>

      <div className="chat-page">
        <div className="chat-panel" ref={panelRef} role="log" aria-live="polite" aria-relevant="additions">
          {messages.length === 0 ? (
            <div className="chat-welcome">
              <span className="chat-welcome__icon" aria-hidden="true">
                <IconSparkleChat width={26} height={26} />
              </span>
              <h2 className="h3 chat-welcome__title">Hola, soy tu asistente de compras</h2>
              <p className="body chat-welcome__subtitle">
                Puedo explicarte por qué se sugiere comprar un SKU, dónde hay sobreinventario o
                quiebre, y qué productos se están vendiendo mejor — con los datos reales detrás de
                cada respuesta.
              </p>
              <div className="chat-suggestions">
                {SUGGESTIONS.map((s) => (
                  <button
                    key={s}
                    type="button"
                    className="chat-suggestion"
                    onClick={() => handleSuggestion(s)}
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="chat">
              {messages.map((m) => (
                <ChatMessage key={m.id} message={m} />
              ))}
              {toolStatus && (
                <div className="chat-tool-status">
                  <span className="chat-tool-status__dot" aria-hidden="true" />
                  {toolStatus}
                </div>
              )}
            </div>
          )}
        </div>

        <form className="chat-composer" onSubmit={handleSubmit}>
          <textarea
            ref={inputRef}
            className="chat-composer__input"
            rows={1}
            placeholder="Pregúntale al planeador… (Enter para enviar, Shift+Enter para salto de línea)"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={handleKeyDown}
            aria-label="Escribe tu pregunta para el asistente de compras"
            disabled={isStreaming}
          />
          <button
            type="submit"
            className="btn btn--ai chat-composer__send"
            disabled={isStreaming || !draft.trim()}
            aria-label="Enviar pregunta"
          >
            <IconSend width={18} height={18} />
          </button>
        </form>
      </div>
    </>
  )
}

function ChatMessage({ message }) {
  if (message.role === 'user') {
    return (
      <div className="msg msg--user" aria-label="Tu mensaje">
        {message.content}
      </div>
    )
  }

  if (message.pending) {
    return (
      <div className="msg msg--ai" aria-label="El asistente está escribiendo">
        <span className="typing">
          <span />
          <span />
          <span />
        </span>
      </div>
    )
  }

  return (
    <div className="msg msg--ai" aria-label="Respuesta del asistente">
      {message.error ? message.content : <p style={{ margin: 0 }}>{message.content}</p>}

      {message.table && <MessageTable table={message.table} />}

      {!!message.sources?.length && (
        <div className="msg__sources">
          {message.sources.map((s, i) => (
            <span className="msg__source-chip" key={i}>
              {s.layer && <span className={`layer layer--${s.layer.toLowerCase()}`}>{s.layer}</span>}
              {s.label}
            </span>
          ))}
        </div>
      )}

      {message.isFallback && (
        <p className="chat-fallback-note">
          Respuesta generada con consultas directas a los datos mientras el motor conversacional
          completo (T6) termina de integrarse.
        </p>
      )}
    </div>
  )
}

function MessageTable({ table }) {
  return (
    <table className="msg__table">
      <thead>
        <tr>
          {table.columns.map((c) => (
            <th key={c}>{c}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {table.rows.map((row, i) => (
          <tr key={i}>
            {row.map((cell, j) => (
              <td key={j}>{cell}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  )
}
