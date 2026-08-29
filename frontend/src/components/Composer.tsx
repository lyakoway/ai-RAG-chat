import { useEffect, useRef, useState } from 'react'
import { IconMic, IconSend, IconStop } from '../lib/icons'
import { AnalyticsEvent, trackEvent } from '../lib/analytics'
import { useI18n } from '../lib/i18n'
import { useSpeechRecognition } from '../hooks/useSpeechRecognition'

interface Props {
  onSend: (text: string) => void
  onStop: () => void
  isStreaming: boolean
}

export function Composer({ onSend, onStop, isStreaming }: Props) {
  const { t, lang } = useI18n()
  const [text, setText] = useState('')
  const ref = useRef<HTMLTextAreaElement>(null)

  const speech = useSpeechRecognition(lang)
  const voiceBaseRef = useRef('')

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
    speech.reset()
    requestAnimationFrame(() => {
      if (ref.current) ref.current.style.height = 'auto'
    })
  }

  const toggleVoice = () => {
    if (speech.listening) {
      speech.stop()
      return
    }
    trackEvent(AnalyticsEvent.VOICE_INPUT, { context: 'chat' })
    voiceBaseRef.current = text
    speech.start()
    if (ref.current) ref.current.focus()
  }

  // Распознанный текст дописывается к тому, что было в поле до старта.
  useEffect(() => {
    if (!speech.listening) return
    const combined = [voiceBaseRef.current, speech.text].filter(Boolean).join(' ')
    setText(combined)
    autoGrow()
  }, [speech.listening, speech.text])

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
          <>
            {speech.supported && (
              <button
                type="button"
                className={`composer-btn mic ${speech.listening ? 'listening' : ''}`}
                onClick={toggleVoice}
                title={t('voiceInput')}
              >
                <IconMic />
              </button>
            )}
            <button
              className="composer-btn send"
              onClick={submit}
              disabled={!text.trim()}
              title={t('sendHint')}
            >
              <IconSend />
            </button>
          </>
        )}
      </div>
      <p className="composer-hint">{t('composerHint')}</p>
    </div>
  )
}
