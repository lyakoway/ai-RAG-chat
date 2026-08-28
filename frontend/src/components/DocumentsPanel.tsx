import { useRef, useState } from 'react'
import { IconDoc, IconDownload, IconEye, IconTrash, IconUpload } from '../lib/icons'
import { AnalyticsEvent, trackEvent } from '../lib/analytics'
import { useSwipeDismiss } from '../hooks/useSwipeDismiss'
import { api } from '../lib/api'
import { useI18n } from '../lib/i18n'
import type { DocumentItem, Source } from '../lib/types'

interface Props {
  documents: DocumentItem[]
  categories: string[]
  onUploaded: () => void
  onDeleted: () => void
  onOpenSource: (source: Source) => void
  onClose: () => void
}

function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function fileExt(name: string) {
  return name.split('.').pop()?.toUpperCase() ?? 'DOC'
}

export function DocumentsPanel({
  documents,
  categories,
  onUploaded,
  onDeleted,
  onOpenSource,
  onClose,
}: Props) {
  const { t, lang } = useI18n()
  const [category, setCategory] = useState('General')
  const [uploading, setUploading] = useState(false)
  const [demoLoading, setDemoLoading] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const loadDemo = async () => {
    if (demoLoading) return
    setError(null)
    setDemoLoading(true)
    try {
      await api.loadDemoDocuments()
      trackEvent(AnalyticsEvent.DEMO_DOCS_LOAD)
      onUploaded()
    } catch (e) {
      const message = e instanceof Error ? e.message : t('uploadError')
      trackEvent(AnalyticsEvent.DEMO_DOCS_LOAD_ERROR, {
        message: message.slice(0, 120),
      })
      setError(message)
    } finally {
      setDemoLoading(false)
    }
  }

  const upload = async (files: FileList | File[]) => {
    setError(null)
    setUploading(true)
    const list = Array.from(files)
    const cat = category.trim() || 'General'
    try {
      // Sequential upload keeps the UI status readable; supports many files at once.
      for (const file of list) {
        await api.uploadDocument(file, cat)
      }
      trackEvent(AnalyticsEvent.DOCUMENT_UPLOAD, {
        category: cat,
        count: list.length,
      })
      onUploaded()
    } catch (e) {
      const message = e instanceof Error ? e.message : t('uploadError')
      trackEvent(AnalyticsEvent.DOCUMENT_UPLOAD_ERROR, {
        category: cat,
        count: list.length,
        message: message.slice(0, 120),
      })
      setError(message)
    } finally {
      setUploading(false)
    }
  }

  const remove = async (id: string, filename: string) => {
    try {
      await api.deleteDocument(id)
      trackEvent(AnalyticsEvent.DOCUMENT_DELETE, { filename })
      onDeleted()
    } catch (e) {
      const message = e instanceof Error ? e.message : t('uploadError')
      trackEvent(AnalyticsEvent.DOCUMENT_DELETE_ERROR, {
        filename,
        message: message.slice(0, 120),
      })
      setError(message)
    }
  }

  const knownCategories = Array.from(new Set(['General', ...categories]))
  // Показываем документы на языке интерфейса. Исключение — собственные загрузки
  // без пары: они видны на любом языке, чтобы спросить по ним можно было
  // с любого интерфейса (ответ LLM даст на языке интерфейса). Прячем только
  // языковых «двойников» демо-пака.
  const DEMO_PAIR_ORDER = ['user_guide', 'remote_work_policy', 'pricing']
  const pairSlot = (d: DocumentItem) => {
    const i = d.pair_key ? DEMO_PAIR_ORDER.indexOf(d.pair_key) : -1
    return i === -1 ? DEMO_PAIR_ORDER.length : i
  }
  const visible = documents
    .filter((d) => !d.pair_key || !d.lang || d.lang === lang)
    .sort((a, b) => {
      const delta = pairSlot(a) - pairSlot(b)
      if (delta !== 0) return delta
      return b.created_at.localeCompare(a.created_at) // непарные: новые сверху
    })
  const visibleReady = visible.filter((d) => d.status === 'ready').length
  const swipe = useSwipeDismiss(onClose, 'right')

  return (
    <aside
      className={`docs-panel ${swipe.swiping ? 'swiping' : ''}`}
      style={swipe.style}
      {...swipe.handlers}
    >
      <div className="docs-head">
        <h2>
          <IconDoc width={18} height={18} />
          {t('documents')}
          <span className="docs-count">{visibleReady}</span>
        </h2>
        <button className="docs-close" onClick={onClose} title={t('hidePanel')}>✕</button>
      </div>

      <div className="docs-upload">
        <label className="docs-cat-label">{t('category')}</label>
        <input
          className="docs-cat-input"
          list="categories"
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          placeholder={t('categoryPlaceholder')}
        />
        <datalist id="categories">
          {knownCategories.map((c) => (
            <option key={c} value={c} />
          ))}
        </datalist>

        <div
          className={`dropzone ${dragOver ? 'over' : ''}`}
          onClick={() => inputRef.current?.click()}
          onDragOver={(e) => {
            e.preventDefault()
            setDragOver(true)
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDragOver(false)
            if (e.dataTransfer.files.length) upload(e.dataTransfer.files)
          }}
        >
          <IconUpload width={22} height={22} />
          <span className="dropzone-title">
            {uploading ? t('dropzoneUploading') : t('dropzoneIdle')}
          </span>
          <span className="dropzone-sub">{t('dropzoneSub')}</span>
          <input
            ref={inputRef}
            type="file"
            multiple
            accept=".pdf,.docx,.doc,.xlsx,.xls"
            hidden
            onChange={(e) => {
              if (e.target.files?.length) upload(e.target.files)
              e.target.value = ''
            }}
          />
        </div>
        {error && <p className="docs-error">{error}</p>}
      </div>

      <div className="docs-list">
        {documents.length === 0 && (
          <div className="docs-empty-block">
            <p className="docs-empty">{t('docsEmpty')}</p>
            <button
              className="btn btn-ghost demo-load-btn"
              onClick={loadDemo}
              disabled={demoLoading}
            >
              {demoLoading ? '…' : t('demoDocsBtn')}
            </button>
          </div>
        )}
        {documents.length > 0 && visible.length === 0 && (
          <p className="docs-empty">{t('docsEmptyLang')}</p>
        )}
        {visible.map((d) => (
          <div key={d.id} className="doc-item">
            <div className={`doc-ext ext-${fileExt(d.filename).toLowerCase()}`}>
              {fileExt(d.filename)}
            </div>
            <div className="doc-info">
              <button
                className="doc-name clickable"
                title={t('docOpen')}
                onClick={() =>
                  onOpenSource({
                    document_id: d.id,
                    filename: d.filename,
                    page: null,
                    snippet: '',
                    score: null,
                    chunk_index: null,
                  })
                }
              >
                {d.filename}
              </button>
              <div className="doc-meta">
                <span className="doc-badge">{d.category}</span>
                <span>{formatSize(d.size_bytes)}</span>
                {d.status === 'ready' && (
                  <span>{t('docStats', { pages: d.page_count, chunks: d.chunk_count })}</span>
                )}
              </div>
              {d.status === 'processing' && (
                <div className="doc-status processing">
                  <span className="spinner" /> {t('indexing')}
                </div>
              )}
              {d.status === 'error' && (
                <div className="doc-status error" title={d.error ?? ''}>
                  {t('errorPrefix')}: {d.error}
                </div>
              )}
            </div>
            <div className="doc-actions">
              {d.status === 'ready' && (
                <button
                  className="doc-action"
                  title={t('docOpen')}
                  onClick={() =>
                    onOpenSource({
                      document_id: d.id,
                      filename: d.filename,
                      page: null,
                      snippet: '',
                      score: null,
                      chunk_index: null,
                    })
                  }
                >
                  <IconEye width={16} height={16} />
                </button>
              )}
              {d.status === 'ready' && (
                <a
                  className="doc-action"
                  href={api.documentFileUrl(d.id)}
                  download={d.filename}
                  title={t('docDownload')}
                  onClick={() => trackEvent(AnalyticsEvent.DOCUMENT_DOWNLOAD, { filename: d.filename })}
                >
                  <IconDownload width={16} height={16} />
                </a>
              )}
              <button
                className="doc-del"
                onClick={() => remove(d.id, d.filename)}
                title={t('deleteDoc')}
              >
                <IconTrash width={16} height={16} />
              </button>
            </div>
          </div>
        ))}
      </div>
    </aside>
  )
}
