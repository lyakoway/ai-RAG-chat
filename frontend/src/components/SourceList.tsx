import { useEffect, useRef, useState } from 'react'
import { IconChevron, IconDoc, IconExternal } from '../lib/icons'
import { useI18n } from '../lib/i18n'
import type { Source } from '../lib/types'

interface Props {
  sources: Source[]
  open: boolean
  onToggle: () => void
  activeIndex: number | null // index requested via an inline [n] click
  onOpenSource: (source: Source) => void
}

export function SourceList({ sources, open, onToggle, activeIndex, onOpenSource }: Props) {
  const { t } = useI18n()
  const cardRefs = useRef<(HTMLLIElement | null)[]>([])
  const [flash, setFlash] = useState<number | null>(null)

  // When an inline citation points here, scroll to and briefly highlight it.
  useEffect(() => {
    if (activeIndex == null || !open) return
    const el = cardRefs.current[activeIndex]
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
      setFlash(activeIndex)
      const t = setTimeout(() => setFlash(null), 1400)
      return () => clearTimeout(t)
    }
  }, [activeIndex, open])

  if (!sources.length) return null

  return (
    <div className="sources">
      <button className="sources-header" onClick={onToggle}>
        <IconDoc width={15} height={15} />
        <span>{t('sources', { count: sources.length })}</span>
        <IconChevron width={15} height={15} className={`sources-caret ${open ? 'up' : ''}`} />
      </button>

      {open && (
        <ol className="sources-body">
          {sources.map((s, i) => (
            <li
              key={`${s.document_id}-${s.chunk_index}-${i}`}
              ref={(el) => {
                cardRefs.current[i] = el
              }}
              className={`source-card ${flash === i ? 'flash' : ''}`}
            >
              <div className="source-top">
                <span className="source-index">[{i + 1}]</span>
                <button
                  className="source-name"
                  onClick={() => onOpenSource(s)}
                  title={t('openSource')}
                >
                  {s.filename}
                  <IconExternal width={13} height={13} />
                </button>
                <span className="source-meta">
                  {s.page != null && (
                    <span className="source-page">{t('page', { n: s.page })}</span>
                  )}
                  {s.score != null && (
                    <span className="source-score">{Math.round(s.score * 100)}%</span>
                  )}
                </span>
              </div>
              <p className="source-snippet">{s.snippet}</p>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}
