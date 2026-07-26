import { useRef, useState } from 'react'
import { IconSend, IconStop } from '../lib/icons'
import { useI18n } from '../lib/i18n'

interface Props {
  onSend: (text: string) => void
  onStop: () => void
  isStreaming: boolean
}

export function Composer({ onSend, onStop, isStreaming }: Props) {
  const { t } = useI18n()
  const [text, setText] = useState('')
  const ref = useRef<HTMLTextAreaElement>(null)

  const autoGrow = () => {
    const el = ref.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`
  }

  const submit = () => {
    const value = text.trim()
    if (!value || isStreaming) return
    onSend(value)
    setText('')
    requestAnimationFrame(() => {
      if (ref.current) ref.current.style.height = 'auto'
    })
  }

  return (
    <div className="composer">
      <div className="composer-box">
        <textarea
          ref={ref}
          className="composer-input"
          placeholder={t('composerPlaceholder')}
          rows={1}
          value={text}
          onChange={(e) => {
            setText(e.target.value)
            autoGrow()
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              submit()
            }
          }}
        />
        {isStreaming ? (
          <button className="composer-btn stop" onClick={onStop} title={t('stop')}>
            <IconStop />
          </button>
        ) : (
          <button
            className="composer-btn send"
            onClick={submit}
            disabled={!text.trim()}
            title={t('sendHint')}
          >
            <IconSend />
          </button>
        )}
      </div>
      <p className="composer-hint">{t('composerHint')}</p>
    </div>
  )
}
