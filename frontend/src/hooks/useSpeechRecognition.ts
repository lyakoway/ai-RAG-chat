import { useCallback, useRef, useState } from 'react'

/* Голосовой ввод через Web Speech API (Chrome, Edge, Android Chrome, Safari 14.5+).
   Firefox не поддерживает — supported=false, кнопка микрофона скрывается. */

interface SpeechRecognitionLike {
  lang: string
  continuous: boolean
  interimResults: boolean
  start(): void
  stop(): void
  onresult: ((e: { results: ArrayLike<{ isFinal: boolean; 0: { transcript: string } }> }) => void) | null
  onerror: ((e: { error: string }) => void) | null
  onend: (() => void) | null
}

export function useSpeechRecognition(lang: 'ru' | 'en') {
  const supported =
    typeof window !== 'undefined' &&
    Boolean(
      (window as unknown as Record<string, unknown>).SpeechRecognition ||
        (window as unknown as Record<string, unknown>).webkitSpeechRecognition,
    )

  const [listening, setListening] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Распознанный текст текущей сессии: финальный + промежуточный.
  const [finalText, setFinalText] = useState('')
  const [interim, setInterim] = useState('')
  const recRef = useRef<SpeechRecognitionLike | null>(null)

  const start = useCallback(() => {
    if (!supported) return
    const w = window as unknown as Record<string, unknown>
    const SR = (w.SpeechRecognition || w.webkitSpeechRecognition) as
      | (new () => SpeechRecognitionLike)
      | undefined
    if (!SR) return

    setFinalText('')
    setInterim('')
    setError(null)

    const rec = new SR()
    rec.lang = lang === 'en' ? 'en-US' : 'ru-RU'
    rec.continuous = true
    rec.interimResults = true
    rec.onresult = (e) => {
      let fin = ''
      let inter = ''
      for (let i = 0; i < e.results.length; i++) {
        const r = e.results[i] as { isFinal: boolean; 0: { transcript: string } }
        if (r.isFinal) fin += r[0].transcript
        else inter += r[0].transcript
      }
      setFinalText(fin.trim())
      setInterim(inter)
    }
    rec.onerror = (e) => {
      if (e.error === 'not-allowed' || e.error === 'service-not-allowed') {
        setError('microphone_denied')
      }
      // no-speech / aborted — тихо завершаем, onend сработает.
    }
    rec.onend = () => setListening(false)
    recRef.current = rec
    rec.start()
    setListening(true)
  }, [supported, lang, listening])

  const stop = useCallback(() => {
    recRef.current?.stop()
    setListening(false)
  }, [])

  const reset = useCallback(() => {
    setFinalText('')
    setInterim('')
  }, [])

  return {
    supported,
    listening,
    error,
    /** Распознанный текст сессии: финал + промежуточный (для живого отображения). */
    text: [finalText, interim].filter(Boolean).join(' '),
    start,
    stop,
    reset,
  }
}
