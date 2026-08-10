import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type TouchEvent,
} from 'react'

type Edge = 'left' | 'right'

const MOBILE_MQ = '(max-width: 1100px)'
const THRESHOLD_PX = 72
const AXIS_LOCK_PX = 10

/**
 * Swipe-to-dismiss for mobile drawers.
 * left edge → swipe left to close; right edge → swipe right to close.
 */
export function useSwipeDismiss(
  onDismiss: () => void,
  edge: Edge,
  enabled = true,
) {
  const [style, setStyle] = useState<CSSProperties | undefined>()
  const [swiping, setSwiping] = useState(false)

  const startRef = useRef<{ x: number; y: number } | null>(null)
  const axisRef = useRef<'h' | 'v' | null>(null)
  const offsetRef = useRef(0)
  const mobileRef = useRef(false)
  const onDismissRef = useRef(onDismiss)
  onDismissRef.current = onDismiss

  useEffect(() => {
    const mql = window.matchMedia(MOBILE_MQ)
    const sync = () => {
      mobileRef.current = mql.matches
    }
    sync()
    mql.addEventListener('change', sync)
    return () => mql.removeEventListener('change', sync)
  }, [])

  const clear = useCallback(() => {
    startRef.current = null
    axisRef.current = null
    offsetRef.current = 0
    setStyle(undefined)
    setSwiping(false)
  }, [])

  const onTouchStart = useCallback(
    (e: TouchEvent) => {
      if (!enabled || !mobileRef.current) return
      const t = e.touches[0]
      startRef.current = { x: t.clientX, y: t.clientY }
      axisRef.current = null
      offsetRef.current = 0
      setSwiping(true)
    },
    [enabled],
  )

  const onTouchMove = useCallback(
    (e: TouchEvent) => {
      if (!enabled || !mobileRef.current || !startRef.current) return
      const t = e.touches[0]
      const dx = t.clientX - startRef.current.x
      const dy = t.clientY - startRef.current.y

      if (!axisRef.current) {
        if (Math.abs(dx) < AXIS_LOCK_PX && Math.abs(dy) < AXIS_LOCK_PX) return
        axisRef.current = Math.abs(dx) >= Math.abs(dy) ? 'h' : 'v'
      }
      if (axisRef.current !== 'h') return

      const next = edge === 'left' ? Math.min(0, dx) : Math.max(0, dx)
      offsetRef.current = next
      setStyle({ transform: `translateX(${next}px)` })
    },
    [enabled, edge],
  )

  const onTouchEnd = useCallback(() => {
    if (!enabled || !mobileRef.current) {
      clear()
      return
    }
    const o = offsetRef.current
    const dismiss =
      axisRef.current === 'h' &&
      (edge === 'left' ? o <= -THRESHOLD_PX : o >= THRESHOLD_PX)
    clear()
    if (dismiss) onDismissRef.current()
  }, [enabled, edge, clear])

  return {
    swiping,
    style,
    handlers: {
      onTouchStart,
      onTouchMove,
      onTouchEnd,
      onTouchCancel: clear,
    },
  }
}
