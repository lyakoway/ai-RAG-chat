import { useEffect, useRef } from 'react'
import { Composer } from './Composer'
import { MessageBubble } from './MessageBubble'
import { IconLayers, IconSpark } from '../lib/icons'
import { AnalyticsEvent, trackEvent } from '../lib/analytics'
import { useI18n } from '../lib/i18n'
import type { ChatMessage, Source } from '../lib/types'

interface Props {
  messages: ChatMessage[]
  isStreaming: boolean
  onSend: (text: string) => void
  onStop: () => void
  hasDocuments: boolean
  onOpenSource: (source: Source) => void
}

export function ChatView({
  messages,
  isStreaming,
  onSend,
  onStop,
  hasDocuments,
  onOpenSource,
}: Props) {
  const { t } = useI18n()
  const suggestions = [t('suggestion1'), t('suggestion2'), t('suggestion3')]
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages])

  const empty = messages.length === 0

  return (
    <div className="chat">
      <div className="chat-scroll">
        {empty ? (
          <div className="welcome">
            <div className="welcome-logo"><IconSpark width={30} height={30} /></div>
            <h1 className="welcome-title">{t('welcomeTitle')}</h1>
            <p className="welcome-sub">{t('welcomeSub')}</p>

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
            {messages.map((m) => (
              <MessageBubble key={m.id} message={m} onOpenSource={onOpenSource} />
            ))}
            <div ref={endRef} />
          </div>
        )}
      </div>

      <Composer onSend={onSend} onStop={onStop} isStreaming={isStreaming} />
    </div>
  )
}
