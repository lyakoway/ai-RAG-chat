import { useEffect } from 'react'
import { api } from '../lib/api'
import { IconExternal } from '../lib/icons'
import { useI18n } from '../lib/i18n'
import type { Source } from '../lib/types'

interface Props {
  source: Source | null
  onClose: () => void
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

  const ext = source.filename.split('.').pop()?.toLowerCase() ?? ''
  const isPdf = ext === 'pdf'
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
          ) : (
            <div className="viewer-fallback">
              <p>
                {t('viewerPdfOnly')}
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
