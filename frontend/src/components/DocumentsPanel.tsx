import { useRef, useState } from 'react'
import { IconDoc, IconTrash, IconUpload } from '../lib/icons'
import { AnalyticsEvent, trackEvent } from '../lib/analytics'
import { useSwipeDismiss } from '../hooks/useSwipeDismiss'
import { api } from '../lib/api'
import { useI18n } from '../lib/i18n'
import type { DocumentItem } from '../lib/types'

interface Props {
  documents: DocumentItem[]
  categories: string[]
  readyDocs: number
  onUploaded: () => void
  onDeleted: () => void
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
  readyDocs,
  onUploaded,
  onDeleted,
  onClose,
}: Props) {
  const { t } = useI18n()
  const [category, setCategory] = useState('General')
  const [uploading, setUploading] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

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
    await api.deleteDocument(id)
    trackEvent(AnalyticsEvent.DOCUMENT_DELETE, { filename })
    onDeleted()
  }

  const knownCategories = Array.from(new Set(['General', ...categories]))
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
          <span className="docs-count">{readyDocs}</span>
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
        {documents.length === 0 && <p className="docs-empty">{t('docsEmpty')}</p>}
        {documents.map((d) => (
          <div key={d.id} className="doc-item">
            <div className={`doc-ext ext-${fileExt(d.filename).toLowerCase()}`}>
              {fileExt(d.filename)}
            </div>
            <div className="doc-info">
              <div className="doc-name" title={d.filename}>{d.filename}</div>
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
            <button
              className="doc-del"
              onClick={() => remove(d.id, d.filename)}
              title={t('deleteDoc')}
            >
              <IconTrash width={16} height={16} />
            </button>
          </div>
        ))}
      </div>
    </aside>
  )
}
