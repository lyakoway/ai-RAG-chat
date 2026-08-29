import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'
import { AnalyticsEvent, trackEvent } from '../lib/analytics'
import { buildDocumentSuggestions } from '../lib/suggestions'
import { useI18n } from '../lib/i18n'
import { useSpeechRecognition } from '../hooks/useSpeechRecognition'
import { IconExternal, IconLayers, IconMic, IconSearch } from '../lib/icons'
import type { DocumentItem, Source } from '../lib/types'

interface Props {
  documents: DocumentItem[]
  category: string // 'All' or a concrete category
  onOpenSource: (source: Source) => void
}

/** Векторный поиск: прямой семантический поиск по фрагментам документов
 *  (fastembed + Chroma), без LLM. */
export function SearchView({ documents, category, onOpenSource }: Props) {
  const { t, lang } = useI18n()
  const [query, setQuery] = useState('')
  const speech = useSpeechRecognition(lang)
  const voiceBaseRef = useRef('')
  const [results, setResults] = useState<Source[] | null>(null)
  const [tookMs, setTookMs] = useState<number | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const runSearch = useCallback(
    async (raw: string) => {
      const q = raw.trim()
      if (!q || loading) return
      setLoading(true)
      setError(null)
      try {
        const res = await api.search(q, {
          category: category === 'All' ? undefined : category,
          top_k: 10,
        })
        setResults(res.results)
        setTookMs(res.took_ms)
        trackEvent(AnalyticsEvent.VECTOR_SEARCH, {
          results_count: res.results.length,
          took_ms: res.took_ms,
          category: category === 'All' ? 'all' : category,
        })
      } catch (e) {
        setError(e instanceof Error ? e.message : 'search_failed')
        trackEvent(AnalyticsEvent.VECTOR_SEARCH_ERROR, {
          message: (e instanceof Error ? e.message : 'search_failed').slice(0, 120),
        })
      } finally {
        setLoading(false)
      }
    },
    [category, loading],
  )

  const empty = results !== null && results.length === 0
  const hasDocuments = documents.some((d) => d.status === 'ready')
  const suggestions = buildDocumentSuggestions(documents, lang)

  const toggleVoice = () => {
    if (speech.listening) {
      speech.stop()
      return
    }
    trackEvent(AnalyticsEvent.VOICE_INPUT, { context: 'search' })
    voiceBaseRef.current = query
    speech.start()
  }

  // Распознанный голосом текст дописывается к содержимому поля поиска.
  useEffect(() => {
    if (!speech.listening) return
    const combined = [voiceBaseRef.current, speech.text].filter(Boolean).join(' ')
    setQuery(combined)
  }, [speech.listening, speech.text])

  return (
    <div className="chat">
      <div className="chat-scroll">
        {results === null ? (
          <div className="welcome">
            <div className="welcome-logo search">
              <IconSearch width={30} height={30} />
            </div>
            <div className="mode-badge search">{t('modeSearch')}</div>
            <h1 className="welcome-title">{t('searchWelcomeTitle')}</h1>
            <p className="welcome-sub">{t('searchWelcomeSub')}</p>

            {!hasDocuments && (
              <div className="welcome-note">
                <IconLayers width={16} height={16} />
                {t('welcomeNote')}
              </div>
            )}

            <div className="suggestions">
              {suggestions.map((s) => (
                  <button
                    key={s}
                    className="suggestion"
                    disabled={!hasDocuments}
                    onClick={() => {
                      setQuery(s)
                      runSearch(s)
                    }}
                  >
                    {s}
                  </button>
                ),
              )}
            </div>
          </div>
        ) : (
          <div className="search-results">
            <div className="search-summary">
              <span>{t('searchResults', { count: results.length })}</span>
              {tookMs != null && (
                <span className="search-took">{t('searchTook', { ms: tookMs })}</span>
              )}
            </div>

            {empty && <div className="search-empty">{t('searchEmpty')}</div>}

            {error && <div className="search-empty">{t('errorPrefix')}: {error}</div>}

            <ol className="search-list">
              {results.map((r, i) => (
                <li
                  key={`${r.document_id}-${r.chunk_index}-${i}`}
                  className="source-card clickable"
                  onClick={() => onOpenSource(r)}
                >
                  <div className="source-top">
                    <span className="source-index">[{i + 1}]</span>
                    <button
                      className="source-name"
                      onClick={(e) => {
                        e.stopPropagation()
                        onOpenSource(r)
                      }}
                      title={t('openSource')}
                    >
                      {r.filename}
                      <IconExternal width={13} height={13} />
                    </button>
                    <span className="source-meta">
                      {r.page != null && (
                        <span className="source-page">{t('page', { n: r.page })}</span>
                      )}
                      {r.score != null && (
                        <span className="source-score" title={String(r.score)}>
                          {Math.round(r.score * 100)}%
                        </span>
                      )}
                    </span>
                  </div>
                  <p className="source-snippet">{r.snippet}</p>
                </li>
              ))}
            </ol>
          </div>
        )}
      </div>

      <div className="composer">
        <div className="composer-box">
          <input
            className="composer-input"
            value={query}
            placeholder={t('searchPlaceholder')}
            disabled={!hasDocuments || loading}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                runSearch(query)
              }
            }}
          />
          <button
            className={`composer-btn mic ${speech.listening ? 'listening' : ''}`}
            onClick={toggleVoice}
            disabled={!hasDocuments || loading}
            title={t('voiceInput')}
          >
            <IconMic />
          </button>
          <button
            className="composer-btn send"
            onClick={() => runSearch(query)}
            disabled={!query.trim() || loading || !hasDocuments}
            title={t('searchButton')}
          >
            {loading ? '…' : <IconSearch />}
          </button>
        </div>
        <p className="composer-hint">{t('searchHint')}</p>
      </div>
    </div>
  )
}
