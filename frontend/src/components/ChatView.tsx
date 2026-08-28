import { useEffect, useRef } from 'react'
import { Composer } from './Composer'
import { MessageBubble } from './MessageBubble'
import { IconBot, IconLayers, IconSpark } from '../lib/icons'
import { AnalyticsEvent, trackEvent } from '../lib/analytics'
import { useI18n } from '../lib/i18n'
import type { ChatMessage, ChatMode, Source } from '../lib/types'

interface Props {
  messages: ChatMessage[]
  isStreaming: boolean
  onSend: (text: string) => void
  onStop: () => void
  hasDocuments: boolean
  onOpenSource: (source: Source) => void
  onFeedback: (messageId: string, value: 'up' | 'down' | null) => void
  onFollowup: (question: string) => void
  mode: ChatMode
}

export function ChatView({
  messages,
  isStreaming,
  onSend,
  onStop,
  hasDocuments,
  onOpenSource,
  onFeedback,
  onFollowup,
  mode,
}: Props) {
  const { t } = useI18n()
  const isAgent = mode === 'agent'
  const suggestions = isAgent
    ? [t('agentSuggestion1'), t('agentSuggestion2'), t('agentSuggestion3')]
    : [t('suggestion1'), t('suggestion2'), t('suggestion3')]
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages])

  const empty = messages.length === 0

  return (
    <div className={`chat ${isAgent ? 'mode-agent' : 'mode-rag'}`}>
      <div className="chat-scroll">
        {empty ? (
          <div className="welcome">
            <div className={`welcome-logo ${isAgent ? 'agent' : ''}`}>
              {isAgent ? <IconBot width={30} height={30} /> : <IconSpark width={30} height={30} />}
            </div>
            <div className={`mode-badge ${isAgent ? 'agent' : 'rag'}`}>
              {isAgent ? t('modeAgent') : t('modeRag')}
            </div>
            <h1 className="welcome-title">
              {isAgent ? t('welcomeTitleAgent') : t('welcomeTitle')}
            </h1>
            <p className="welcome-sub">
              {isAgent ? t('welcomeSubAgent') : t('welcomeSub')}
            </p>

            {!hasDocuments && (
              <div className="welcome-note">
                <IconLayers width={16} height={16} />
                {t('welcomeNote')}
              </div>
            )}

            <div className="suggestions">
              {suggestions.map((s, i) => (
                <button
                  key={s}
                  className="suggestion"
                  disabled={!hasDocuments}
                  onClick={() => {
                    trackEvent(AnalyticsEvent.CHAT_SUGGESTION_CLICK, {
                      index: i + 1,
                      mode,
                    })
                    onSend(s)
                  }}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="messages">
            {messages.map((m, i) => (
              <MessageBubble
                key={m.id}
                message={m}
                isLast={i === messages.length - 1}
                onOpenSource={onOpenSource}
                onFeedback={onFeedback}
                onFollowup={onFollowup}
              />
            ))}
            <div ref={endRef} />
          </div>
        )}
      </div>

      <Composer onSend={onSend} onStop={onStop} isStreaming={isStreaming} />
    </div>
  )
}
