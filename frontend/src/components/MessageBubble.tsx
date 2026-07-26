import { useState, type ComponentProps, type ReactNode } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { IconSpark } from '../lib/icons'
import { injectCitations } from '../lib/citations'
import { SourceList } from './SourceList'
import { useI18n } from '../lib/i18n'
import type { ChatMessage, Source } from '../lib/types'

interface Props {
  message: ChatMessage
  onOpenSource: (source: Source) => void
}

export function MessageBubble({ message, onOpenSource }: Props) {
  const { t } = useI18n()
  const isUser = message.role === 'user'
  const showCursor = message.streaming && !message.content
  const sources = message.sources ?? []

  const [sourcesOpen, setSourcesOpen] = useState(false)
  const [activeSource, setActiveSource] = useState<number | null>(null)

  const goToCitation = (index: number) => {
    setSourcesOpen(true)
    // Re-trigger scroll even if the same index is clicked twice.
    setActiveSource(null)
    requestAnimationFrame(() => setActiveSource(index))
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
        {!isUser && sources.length > 0 && (
          <SourceList
            sources={sources}
            open={sourcesOpen}
            onToggle={() => setSourcesOpen((v) => !v)}
            activeIndex={activeSource}
            onOpenSource={onOpenSource}
          />
        )}
      </div>
    </div>
  )
}
