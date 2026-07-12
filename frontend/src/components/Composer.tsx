import { useRef, useState } from 'react'
import { IconSend, IconStop } from '../lib/icons'

interface Props {
  onSend: (text: string) => void
  onStop: () => void
  isStreaming: boolean
}

export function Composer({ onSend, onStop, isStreaming }: Props) {
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
          placeholder="Спросите что-нибудь о ваших документах…"
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
          <button className="composer-btn stop" onClick={onStop} title="Остановить">
            <IconStop />
          </button>
        ) : (
          <button
            className="composer-btn send"
            onClick={submit}
            disabled={!text.trim()}
            title="Отправить (Enter)"
          >
            <IconSend />
          </button>
        )}
      </div>
      <p className="composer-hint">
        Enter — отправить · Shift+Enter — новая строка. Ответы основаны на загруженных документах.
      </p>
    </div>
  )
}
