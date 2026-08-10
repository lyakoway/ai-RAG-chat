import { useCallback, useRef, useState } from 'react'
import { AnalyticsEvent, trackEvent } from '../lib/analytics'
import { streamChat } from '../lib/stream'
import type { AgentStep, ChatMessage, ChatMode, Source } from '../lib/types'

let tmpId = 0
const nextId = () => `tmp-${++tmpId}`

interface SendOptions {
  model: string
  category?: string | null
  documentIds?: string[] | null
  lang?: string
  mode?: ChatMode
}

interface UseChatArgs {
  conversationId: string | null
  setConversationId: (id: string) => void
  onFinished?: () => void // e.g. refresh conversation list
}

export function useChat({ conversationId, setConversationId, onFinished }: UseChatArgs) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [isStreaming, setStreaming] = useState(false)
  const abortRef = useRef<AbortController | null>(null)

  const reset = useCallback((initial: ChatMessage[] = []) => {
    abortRef.current?.abort()
    abortRef.current = null
    setStreaming(false)
    setMessages(initial)
  }, [])

  const stop = useCallback(() => {
    abortRef.current?.abort()
    abortRef.current = null
    setStreaming(false)
    setMessages((prev) =>
      prev.map((m) => (m.streaming ? { ...m, streaming: false } : m)),
    )
  }, [])

  const send = useCallback(
    (text: string, opts: SendOptions) => {
      if (!text.trim() || isStreaming) return

      const mode = opts.mode ?? 'rag'
      const userMsg: ChatMessage = { id: nextId(), role: 'user', content: text }
      const aiId = nextId()
      const aiMsg: ChatMessage = {
        id: aiId,
        role: 'assistant',
        content: '',
        sources: [],
        agent_steps: mode === 'agent' ? [] : undefined,
        streaming: true,
      }
      setMessages((prev) => [...prev, userMsg, aiMsg])
      setStreaming(true)

      const patchAi = (patch: Partial<ChatMessage>) =>
        setMessages((prev) => prev.map((m) => (m.id === aiId ? { ...m, ...patch } : m)))

      let agentStepCount = 0

      abortRef.current = streamChat(
        {
          message: text,
          conversation_id: conversationId,
          model: opts.model,
          category: opts.category,
          document_ids: opts.documentIds,
          lang: opts.lang,
          mode,
        },
        {
          onAgentStep: (step: AgentStep) => {
            agentStepCount += 1
            setMessages((prev) =>
              prev.map((m) =>
                m.id === aiId
                  ? { ...m, agent_steps: [...(m.agent_steps ?? []), step] }
                  : m,
              ),
            )
          },
          onSources: (cid: string, sources: Source[]) => {
            if (!conversationId) setConversationId(cid)
            patchAi({ sources })
          },
          onToken: (delta) =>
            setMessages((prev) =>
              prev.map((m) => (m.id === aiId ? { ...m, content: m.content + delta } : m)),
            ),
          onDone: (messageId) => {
            if (mode === 'agent') {
              trackEvent(AnalyticsEvent.AGENT_RUN_DONE, {
                steps: agentStepCount,
                model: opts.model,
              })
            }
            patchAi({ id: messageId, streaming: false })
            setStreaming(false)
            abortRef.current = null
            onFinished?.()
          },
          onError: (msg) => {
            if (mode === 'agent') {
              trackEvent(AnalyticsEvent.AGENT_RUN_ERROR, {
                steps: agentStepCount,
                model: opts.model,
                message: msg.slice(0, 120),
              })
            }
            patchAi({
              content: (aiMsg.content || '') + `\n\n⚠️ ${msg}`,
              streaming: false,
            })
            setStreaming(false)
            abortRef.current = null
          },
        },
      )
    },
    [conversationId, isStreaming, setConversationId, onFinished],
  )

  return { messages, isStreaming, send, stop, reset }
}
