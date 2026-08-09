import { useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'
import { IconExternal } from '../lib/icons'
import { useI18n } from '../lib/i18n'
import type { Source } from '../lib/types'

interface Props {
  source: Source | null
  onClose: () => void
}

function fileExt(filename: string) {
  return filename.split('.').pop()?.toLowerCase() ?? ''
}

function DocxPreview({ fileUrl }: { fileUrl: string }) {
  const { t } = useI18n()
  const containerRef = useRef<HTMLDivElement>(null)
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading')

  useEffect(() => {
    const el = containerRef.current
    if (!el) return

    let cancelled = false
    setStatus('loading')
    el.innerHTML = ''

    ;(async () => {
      try {
        const [{ renderAsync }, res] = await Promise.all([
          import('docx-preview'),
          fetch(fileUrl),
        ])
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const buffer = await res.arrayBuffer()
        if (cancelled) return
        await renderAsync(buffer, el, undefined, {
          className: 'docx',
          inWrapper: true,
          ignoreWidth: false,
          ignoreHeight: false,
          breakPages: true,
          renderHeaders: true,
          renderFooters: true,
        })
        if (!cancelled) setStatus('ready')
      } catch {
        if (!cancelled) setStatus('error')
      }
    })()

    return () => {
      cancelled = true
      el.innerHTML = ''
    }
  }, [fileUrl])

  return (
    <div className="viewer-docx-wrap">
      {status === 'loading' && <p className="viewer-docx-status">{t('viewerDocxLoading')}</p>}
      {status === 'error' && <p className="viewer-docx-status">{t('viewerDocxError')}</p>}
      <div
        ref={containerRef}
        className={`viewer-docx ${status === 'ready' ? 'ready' : ''}`}
      />
    </div>
  )
}

export function DocumentViewer({ source, onClose }: Props) {
  const { t } = useI18n()
  useEffect(() => {
    if (!source) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [source, onClose])

  if (!source) return null

  const ext = fileExt(source.filename)
  const isPdf = ext === 'pdf'
  const isDocx = ext === 'docx'
  const fileUrl = api.documentFileUrl(source.document_id)
  // PDF.js/native viewer honours #page= to jump straight to the cited page.
  const pdfUrl = source.page ? `${fileUrl}#page=${source.page}&view=FitH` : fileUrl

  return (
    <div className="viewer-overlay" onClick={onClose}>
      <div className="viewer" onClick={(e) => e.stopPropagation()}>
        <div className="viewer-head">
          <div className="viewer-title">
            <strong>{source.filename}</strong>
            {source.page != null && (
              <span className="viewer-page">{t('page', { n: source.page })}</span>
            )}
          </div>
          <div className="viewer-actions">
            <a className="viewer-open" href={fileUrl} target="_blank" rel="noreferrer">
              <IconExternal width={15} height={15} /> {t('viewerNewTab')}
            </a>
            <button className="viewer-close" onClick={onClose} title={t('viewerClose')}>✕</button>
          </div>
        </div>

        <div className="viewer-body">
          {isPdf ? (
            <iframe className="viewer-frame" src={pdfUrl} title={source.filename} />
          ) : isDocx ? (
            <DocxPreview fileUrl={fileUrl} />
          ) : (
            <div className="viewer-fallback">
              <p>
                {t('viewerPreviewUnsupported')}
                {source.page != null && <> {t('viewerFromPage', { n: source.page })}</>}
              </p>
              <blockquote className="viewer-snippet">{source.snippet}</blockquote>
              <a className="viewer-download" href={fileUrl} target="_blank" rel="noreferrer">
                {t('viewerDownload')}
              </a>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
