import { useRef, useState } from 'react'
import { IconDoc, IconTrash, IconUpload } from '../lib/icons'
import { api } from '../lib/api'
import type { DocumentItem } from '../lib/types'

interface Props {
  documents: DocumentItem[]
  categories: string[]
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

export function DocumentsPanel({ documents, categories, onUploaded, onDeleted, onClose }: Props) {
  const [category, setCategory] = useState('General')
  const [uploading, setUploading] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const upload = async (files: FileList | File[]) => {
    setError(null)
    setUploading(true)
    try {
      // Sequential upload keeps the UI status readable; supports many files at once.
      for (const file of Array.from(files)) {
        await api.uploadDocument(file, category.trim() || 'General')
      }
      onUploaded()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Ошибка загрузки')
    } finally {
      setUploading(false)
    }
  }

  const remove = async (id: string) => {
    await api.deleteDocument(id)
    onDeleted()
  }

  const knownCategories = Array.from(new Set(['General', ...categories]))

  return (
    <aside className="docs-panel">
      <div className="docs-head">
        <h2><IconDoc width={18} height={18} /> Документы</h2>
        <button className="docs-close" onClick={onClose} title="Скрыть панель">✕</button>
      </div>

      <div className="docs-upload">
        <label className="docs-cat-label">Категория</label>
        <input
          className="docs-cat-input"
          list="categories"
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          placeholder="Например: HR, Финансы, Договоры"
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
            {uploading ? 'Загрузка…' : 'Перетащите файлы или нажмите'}
          </span>
          <span className="dropzone-sub">PDF · Word · Excel · можно несколько сразу</span>
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
        {documents.length === 0 && <p className="docs-empty">Документы ещё не загружены.</p>}
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
                  <span>{d.page_count} стр · {d.chunk_count} фрагм.</span>
                )}
              </div>
              {d.status === 'processing' && (
                <div className="doc-status processing">
                  <span className="spinner" /> Индексация…
                </div>
              )}
              {d.status === 'error' && (
                <div className="doc-status error" title={d.error ?? ''}>
                  Ошибка: {d.error}
                </div>
              )}
            </div>
            <button className="doc-del" onClick={() => remove(d.id)} title="Удалить">
              <IconTrash width={16} height={16} />
            </button>
          </div>
        ))}
      </div>
    </aside>
  )
}
