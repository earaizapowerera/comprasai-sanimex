import { useCallback, useRef, useState } from 'react'
import { API_BASE } from '../lib/api.js'
import { answerLocally } from '../mock/chatFallback.js'

let seq = 0
function nextId() {
  seq += 1
  return `m${seq}`
}

/**
 * Cliente de chat streaming para /api/chat (T6, capa C3).
 *
 * Contrato esperado (SSE, text/event-stream, frames separados por \n\n):
 *   data: {"type":"tool_call","label":"Consultando inventarios..."}
 *   data: {"type":"token","content":"Hola"}
 *   data: {"type":"source","label":"...", "layer":"C1"}
 *   data: {"type":"done"}
 *   data: [DONE]
 * El parser es liberal: acepta texto plano como token, distintos nombres de
 * campo (content/delta/text/token), y cualquier `type` desconocido intenta
 * extraer texto igual. Si el endpoint no existe, no responde 2xx, o no trae
 * body/stream, se cae a una respuesta local grounded en datos reales
 * (mock/chatFallback.js) para que la pantalla nunca se vea rota.
 */
export function useChatStream() {
  const [messages, setMessages] = useState([])
  const [isStreaming, setIsStreaming] = useState(false)
  const [toolStatus, setToolStatus] = useState(null)

  const updateMessage = useCallback((id, patch) => {
    setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, ...(typeof patch === 'function' ? patch(m) : patch) } : m)))
  }, [])

  const send = useCallback(
    async (text) => {
      const trimmed = text.trim()
      if (!trimmed || isStreaming) return

      const history = messages.map((m) => ({ role: m.role, content: m.content }))
      const userMsg = { id: nextId(), role: 'user', content: trimmed }
      const assistantId = nextId()
      const assistantMsg = { id: assistantId, role: 'assistant', content: '', sources: [], pending: true, isFallback: false }

      setMessages((prev) => [...prev, userMsg, assistantMsg])
      setIsStreaming(true)
      setToolStatus(null)

      try {
        await streamFromAgent(trimmed, history, {
          onToken: (chunk) =>
            updateMessage(assistantId, (m) => ({ content: m.content + chunk, pending: false })),
          onToolStart: (label) => setToolStatus(label || 'Consultando datos…'),
          onToolEnd: () => setToolStatus(null),
          onSource: (source) =>
            updateMessage(assistantId, (m) => ({ sources: [...m.sources, source] })),
          onError: (msg) => {
            throw new Error(msg)
          },
        })
        updateMessage(assistantId, { pending: false })
      } catch {
        // Endpoint del agente (T6) no disponible todavía: fallback local grounded en datos reales.
        setToolStatus('Consultando datos…')
        try {
          const result = await answerLocally(trimmed)
          updateMessage(assistantId, {
            content: result.text,
            table: result.table ?? null,
            sources: result.sources ?? [],
            layer: result.layer ?? null,
            pending: false,
            isFallback: true,
          })
        } catch {
          updateMessage(assistantId, {
            content: 'No pude generar una respuesta en este momento. Intenta de nuevo.',
            pending: false,
            isFallback: true,
            error: true,
          })
        }
      } finally {
        setToolStatus(null)
        setIsStreaming(false)
      }
    },
    [messages, isStreaming, updateMessage],
  )

  return { messages, isStreaming, toolStatus, send }
}

async function streamFromAgent(message, history, handlers) {
  const res = await fetch(`${API_BASE}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify({ message, history }),
  })
  if (!res.ok || !res.body) throw new Error(`chat endpoint HTTP ${res.status}`)

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let sawEvent = false

  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let idx
    while ((idx = buffer.indexOf('\n\n')) !== -1) {
      const frame = buffer.slice(0, idx)
      buffer = buffer.slice(idx + 2)
      if (frame.trim()) {
        sawEvent = true
        if (handleFrame(frame, handlers)) return // señal de fin ([DONE] / type done)
      }
    }
  }
  if (!sawEvent) throw new Error('empty SSE stream')
}

function handleFrame(frame, handlers) {
  let eventName = 'message'
  const dataLines = []
  for (const line of frame.split('\n')) {
    if (line.startsWith('event:')) eventName = line.slice(6).trim()
    else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
  }
  const raw = dataLines.join('\n')
  if (!raw) return false
  if (raw === '[DONE]') return true

  let payload = raw
  try {
    payload = JSON.parse(raw)
  } catch {
    handlers.onToken(raw)
    return false
  }
  if (typeof payload === 'string') {
    handlers.onToken(payload)
    return false
  }

  const type = payload.type || eventName
  switch (type) {
    case 'token':
    case 'delta':
    case 'message':
      handlers.onToken(payload.content ?? payload.delta ?? payload.text ?? payload.token ?? '')
      return false
    case 'tool_start':
    case 'tool_call':
      handlers.onToolStart(payload.label ?? payload.tool ?? payload.name ?? 'Consultando datos…')
      return false
    case 'tool_end':
    case 'tool_result':
      handlers.onToolEnd()
      return false
    case 'source':
    case 'citation':
      handlers.onSource({ label: payload.label ?? payload.text ?? String(payload), layer: payload.layer ?? null })
      return false
    case 'error':
      handlers.onError(payload.message ?? 'Error del agente')
      return false
    case 'done':
      return true
    default: {
      const text = payload.content ?? payload.delta ?? payload.text
      if (text) handlers.onToken(text)
      return false
    }
  }
}
