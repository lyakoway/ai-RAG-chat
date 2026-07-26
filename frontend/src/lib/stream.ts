import type { Source } from './types'

export interface ChatStreamRequest {
  message: string
  conversation_id?: string | null
  model: string
  category?: string | null
  document_ids?: string[] | null
}

export interface ChatStreamHandlers {
  onSources?: (conversationId: string, sources: Source[]) => void
  onToken?: (delta: string) => void
  onDone?: (messageId: string, conversationId: string) => void
  onError?: (message: string) => void
}

/**
 * POST /api/chat and parse the Server-Sent-Events stream.
 * Returns an AbortController so the caller can cancel generation.
 */
export function streamChat(
  req: ChatStreamRequest,
  handlers: ChatStreamHandlers,
): AbortController {
  const controller = new AbortController()

  ;(async () => {
    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(req),
        signal: controller.signal,
      })
      if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`)

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })

        // SSE frames are separated by a blank line.
        let sep: number
        while ((sep = buffer.indexOf('\n\n')) !== -1) {
          const frame = buffer.slice(0, sep)
          buffer = buffer.slice(sep + 2)
          dispatch(frame, handlers)
        }
      }
    } catch (err) {
      if (controller.signal.aborted) return // user cancelled — not an error
      const fallback =
        localStorage.getItem('lang') === 'en' ? 'Connection error' : 'Ошибка соединения'
      handlers.onError?.(err instanceof Error ? err.message : fallback)
    }
  })()

  return controller
}

function dispatch(frame: string, handlers: ChatStreamHandlers) {
  let event = 'message'
  let data = ''
  for (const line of frame.split('\n')) {
    if (line.startsWith('event:')) event = line.slice(6).trim()
    else if (line.startsWith('data:')) data += line.slice(5).trim()
  }
  if (!data) return
  const payload = JSON.parse(data)
  switch (event) {
    case 'sources':
      handlers.onSources?.(payload.conversation_id, payload.sources)
      break
    case 'token':
      handlers.onToken?.(payload.delta)
      break
    case 'done':
      handlers.onDone?.(payload.message_id, payload.conversation_id)
      break
    case 'error':
      handlers.onError?.(payload.message)
      break
  }
}
