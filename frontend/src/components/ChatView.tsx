import { useEffect, useRef } from 'react'
import { Composer } from './Composer'
import { MessageBubble } from './MessageBubble'
import { IconLayers, IconSpark } from '../lib/icons'
import type { ChatMessage, Source } from '../lib/types'

interface Props {
  messages: ChatMessage[]
  isStreaming: boolean
  onSend: (text: string) => void
  onStop: () => void
  hasDocuments: boolean
  onOpenSource: (source: Source) => void
}

const SUGGESTIONS = [
  'Кратко перескажи ключевые положения документа',
  'Какие сроки и условия упоминаются?',
  'Найди цифры и суммы в таблицах',
]

export function ChatView({
  messages,
  isStreaming,
  onSend,
  onStop,
  hasDocuments,
  onOpenSource,
}: Props) {
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
            <h1 className="welcome-title">Чат с вашими документами</h1>
            <p className="welcome-sub">
              Загрузите PDF, Word или Excel и задавайте вопросы — ответы приходят со ссылками
              на страницы-источники.
            </p>

            {!hasDocuments && (
              <div className="welcome-note">
                <IconLayers width={16} height={16} />
                Пока нет готовых документов. Откройте панель «Документы» справа и загрузите файлы.
              </div>
            )}

            <div className="suggestions">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  className="suggestion"
                  disabled={!hasDocuments}
                  onClick={() => onSend(s)}
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
