import { useState, type ComponentProps, type ReactNode } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { IconSpark, IconThumbDown, IconThumbUp } from '../lib/icons'
import { AnalyticsEvent, trackEvent } from '../lib/analytics'
import { injectCitations } from '../lib/citations'
import { AgentSteps } from './AgentSteps'
import { SourceList } from './SourceList'
import { useI18n } from '../lib/i18n'
import type { ChatMessage, Source } from '../lib/types'

interface Props {
  message: ChatMessage
  onOpenSource: (source: Source) => void
  onFeedback: (messageId: string, value: 'up' | 'down' | null) => void
}

export function MessageBubble({ message, onOpenSource, onFeedback }: Props) {
  const { t } = useI18n()
  const isUser = message.role === 'user'
  const steps = message.agent_steps ?? []
  const showCursor =
    message.streaming && !message.content && steps.length === 0
  const sources = message.sources ?? []

  const [sourcesOpen, setSourcesOpen] = useState(false)
  const [activeSource, setActiveSource] = useState<number | null>(null)

  const goToCitation = (index: number) => {
    const source = sources[index]
    trackEvent(AnalyticsEvent.SOURCE_CITATION_CLICK, {
      index: index + 1,
      ...(source?.filename ? { filename: source.filename } : {}),
      ...(source?.page != null ? { page: source.page } : {}),
    })
    setSourcesOpen(true)
    // Re-trigger scroll even if the same index is clicked twice.
    setActiveSource(null)
    requestAnimationFrame(() => setActiveSource(index))
  }

  const handleSourcesToggle = () => {
    const next = !sourcesOpen
    trackEvent(AnalyticsEvent.SOURCES_TOGGLE, {
      open: next,
      count: sources.length,
    })
    setSourcesOpen(next)
  }

  const handleFeedback = (value: 'up' | 'down') => {
    const next = message.feedback === value ? null : value // повторный клик снимает
    trackEvent(AnalyticsEvent.ANSWER_FEEDBACK, { value: next ?? 'clear' })
    onFeedback(message.id, next)
  }

  // Markdown renderers that make citation markers ([1]) clickable.
  const withCites = (children: ReactNode) =>
    injectCitations(children, sources.length, goToCitation, (n) => t('sourceN', { n }))
  const mdComponents = {
    p: (p: ComponentProps<'p'>) => <p>{withCites(p.children)}</p>,
    li: (p: ComponentProps<'li'>) => <li>{withCites(p.children)}</li>,
    td: (p: ComponentProps<'td'>) => <td>{withCites(p.children)}</td>,
    strong: (p: ComponentProps<'strong'>) => <strong>{withCites(p.children)}</strong>,
    em: (p: ComponentProps<'em'>) => <em>{withCites(p.children)}</em>,
  }

  return (
    <div className={`msg ${isUser ? 'msg-user' : 'msg-ai'}`}>
      {!isUser && (
        <div className="msg-avatar">
          <IconSpark width={16} height={16} />
        </div>
      )}
      <div className="msg-body">
        {!isUser && (steps.length > 0 || (message.streaming && message.agent_steps)) && (
          <AgentSteps
            steps={steps}
            streaming={Boolean(message.streaming && !message.content)}
          />
        )}
        {(isUser || showCursor || message.content) && (
          <div className={`bubble ${isUser ? 'bubble-user' : 'bubble-ai'}`}>
            {showCursor ? (
              <div className="typing">
                <span /><span /><span />
              </div>
            ) : isUser ? (
              <span className="bubble-plain">{message.content}</span>
            ) : (
              <div className="markdown">
                <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
                  {message.content}
                </ReactMarkdown>
                {message.streaming && <span className="caret" />}
              </div>
            )}
          </div>
        )}
        {!isUser && sources.length > 0 && (
          <SourceList
            sources={sources}
            open={sourcesOpen}
            onToggle={handleSourcesToggle}
            activeIndex={activeSource}
            onOpenSource={onOpenSource}
          />
        )}
        {!isUser && !message.streaming && message.content && (
          <div className="msg-feedback">
            <button
              className={`fb-btn ${message.feedback === 'up' ? 'active' : ''}`}
              onClick={() => handleFeedback('up')}
              title={t('feedbackUp')}
            >
              <IconThumbUp width={15} height={15} />
            </button>
            <button
              className={`fb-btn ${message.feedback === 'down' ? 'active' : ''}`}
              onClick={() => handleFeedback('down')}
              title={t('feedbackDown')}
            >
              <IconThumbDown width={15} height={15} />
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
