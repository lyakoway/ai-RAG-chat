import { useCallback, useEffect, useRef, useState } from 'react'
import { AnalyticsEvent, trackEvent } from '../lib/analytics'
import { api } from '../lib/api'
import { IconExternal } from '../lib/icons'
import { useI18n } from '../lib/i18n'
import type { Source } from '../lib/types'

interface Props {
  source: Source | null
  onClose: () => void
}

const XLSX_PREVIEW_MAX_ROWS = 500

function fileExt(filename: string) {
  return filename.split('.').pop()?.toLowerCase() ?? ''
}

function viewerMode(ext: string): 'pdf' | 'docx' | 'xlsx' | 'fallback' {
  if (ext === 'pdf') return 'pdf'
  if (ext === 'docx') return 'docx'
  if (ext === 'xlsx' || ext === 'xls') return 'xlsx'
  return 'fallback'
}

function viewerParams(source: Source) {
  const ext = fileExt(source.filename)
  return {
    filename: source.filename,
    format: ext || 'unknown',
    mode: viewerMode(ext),
    ...(source.page != null ? { page: source.page } : {}),
  }
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
      {status === 'loading' && <p className="viewer-status">{t('viewerDocxLoading')}</p>}
      {status === 'error' && <p className="viewer-status">{t('viewerDocxError')}</p>}
      <div
        ref={containerRef}
        className={`viewer-docx ${status === 'ready' ? 'ready' : ''}`}
      />
    </div>
  )
}

type SheetPreview = {
  name: string
  rows: string[][]
  truncated: boolean
  totalRows: number
}

function XlsxPreview({ fileUrl }: { fileUrl: string }) {
  const { t } = useI18n()
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading')
  const [sheets, setSheets] = useState<SheetPreview[]>([])
  const [active, setActive] = useState(0)

  useEffect(() => {
    let cancelled = false
    setStatus('loading')
    setSheets([])
    setActive(0)

    ;(async () => {
      try {
        const [XLSX, res] = await Promise.all([import('xlsx'), fetch(fileUrl)])
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const buffer = await res.arrayBuffer()
        if (cancelled) return

        const wb = XLSX.read(buffer, { type: 'array' })
        const parsed: SheetPreview[] = wb.SheetNames.map((name) => {
          const ws = wb.Sheets[name]
          const all = XLSX.utils.sheet_to_json<(string | number | boolean | null)[]>(ws, {
            header: 1,
            defval: '',
            raw: false,
          })
          const rows = all.map((row) =>
            (Array.isArray(row) ? row : []).map((cell) =>
              cell == null || cell === '' ? '' : String(cell),
            ),
          )
          return {
            name,
            rows: rows.slice(0, XLSX_PREVIEW_MAX_ROWS),
            truncated: rows.length > XLSX_PREVIEW_MAX_ROWS,
            totalRows: rows.length,
          }
        })

        if (!cancelled) {
          setSheets(parsed)
          setStatus('ready')
        }
      } catch {
        if (!cancelled) setStatus('error')
      }
    })()

    return () => {
      cancelled = true
    }
  }, [fileUrl])

  const sheet = sheets[active]

  return (
    <div className="viewer-xlsx">
      {status === 'loading' && <p className="viewer-status">{t('viewerXlsxLoading')}</p>}
      {status === 'error' && <p className="viewer-status">{t('viewerXlsxError')}</p>}

      {status === 'ready' && sheet && (
        <>
          <div className="viewer-xlsx-scroll">
            {sheet.rows.length === 0 ? (
              <p className="viewer-status">{t('viewerXlsxEmpty')}</p>
            ) : (
              <table className="viewer-xlsx-table">
                <tbody>
                  {sheet.rows.map((row, ri) => (
                    <tr key={ri} className={ri === 0 ? 'head' : undefined}>
                      <th className="row-num" scope="row">
                        {ri + 1}
                      </th>
                      {row.map((cell, ci) => (
                        <td key={ci}>{cell}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {sheet.truncated && (
              <p className="viewer-xlsx-note">
                {t('viewerXlsxTruncated', {
                  shown: XLSX_PREVIEW_MAX_ROWS,
                  total: sheet.totalRows,
                })}
              </p>
            )}
          </div>

          {sheets.length > 1 && (
            <div className="viewer-xlsx-tabs" role="tablist">
              {sheets.map((s, i) => (
                <button
                  key={s.name}
                  type="button"
                  role="tab"
                  aria-selected={i === active}
                  className={`viewer-xlsx-tab ${i === active ? 'active' : ''}`}
                  onClick={() => setActive(i)}
                >
                  {s.name}
                </button>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}

export function DocumentViewer({ source, onClose }: Props) {
  const { t } = useI18n()

  const closeViewer = useCallback(() => {
    if (source) {
      trackEvent(AnalyticsEvent.VIEWER_CLOSE, viewerParams(source))
    }
    onClose()
  }, [source, onClose])

  useEffect(() => {
    if (!source) return
    trackEvent(AnalyticsEvent.VIEWER_OPEN, viewerParams(source))
  }, [source])

  useEffect(() => {
    if (!source) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && closeViewer()
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [source, closeViewer])

  if (!source) return null

  const ext = fileExt(source.filename)
  const mode = viewerMode(ext)
  const fileUrl = api.documentFileUrl(source.document_id)
  // PDF.js/native viewer honours #page= to jump straight to the cited page.
  const pdfUrl = source.page ? `${fileUrl}#page=${source.page}&view=FitH` : fileUrl
  const params = viewerParams(source)

  return (
    <div className="viewer-overlay" onClick={closeViewer}>
      <div className="viewer" onClick={(e) => e.stopPropagation()}>
        <div className="viewer-head">
          <div className="viewer-title">
            <strong>{source.filename}</strong>
            {source.page != null && (
              <span className="viewer-page">{t('page', { n: source.page })}</span>
            )}
          </div>
          <div className="viewer-actions">
            <a
              className="viewer-open"
              href={fileUrl}
              target="_blank"
              rel="noreferrer"
              onClick={() => trackEvent(AnalyticsEvent.VIEWER_NEW_TAB, params)}
            >
              <IconExternal width={15} height={15} /> {t('viewerNewTab')}
            </a>
            <button
              className="viewer-close"
              onClick={closeViewer}
              title={t('viewerClose')}
            >
              ✕
            </button>
          </div>
        </div>

        <div className="viewer-body">
          {mode === 'pdf' ? (
            <iframe className="viewer-frame" src={pdfUrl} title={source.filename} />
          ) : mode === 'docx' ? (
            <DocxPreview fileUrl={fileUrl} />
          ) : mode === 'xlsx' ? (
            <XlsxPreview fileUrl={fileUrl} />
          ) : (
            <div className="viewer-fallback">
              <p>
                {t('viewerPreviewUnsupported')}
                {source.page != null && <> {t('viewerFromPage', { n: source.page })}</>}
              </p>
              <blockquote className="viewer-snippet">{source.snippet}</blockquote>
              <a
                className="viewer-download"
                href={fileUrl}
                target="_blank"
                rel="noreferrer"
                onClick={() => trackEvent(AnalyticsEvent.VIEWER_DOWNLOAD, params)}
              >
                {t('viewerDownload')}
              </a>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
