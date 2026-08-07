import { GA4_MEASUREMENT_ID, YANDEX_METRIKA_ID } from './constants'
import type { AnalyticsEventName } from './constants'

export type AnalyticsParams = Record<
  string,
  string | number | boolean | undefined
>

declare global {
  interface Window {
    gtag?: (...args: unknown[]) => void
    ym?: (id: number | string, method: string, ...args: unknown[]) => void
  }
}

const cleanParams = (params?: AnalyticsParams) => {
  if (!params) return undefined
  const entries = Object.entries(params).filter(([, v]) => v !== undefined)
  return entries.length ? Object.fromEntries(entries) : undefined
}

/** Событие в GA4 + цель в Яндекс.Метрике (если счётчики подключены). */
export const trackEvent = (
  name: AnalyticsEventName | string,
  params?: AnalyticsParams,
) => {
  if (typeof window === 'undefined') return
  const payload = cleanParams(params)

  if (GA4_MEASUREMENT_ID && typeof window.gtag === 'function') {
    window.gtag('event', name, payload)
  }

  if (YANDEX_METRIKA_ID && typeof window.ym === 'function') {
    window.ym(YANDEX_METRIKA_ID, 'reachGoal', name, payload)
  }
}

/** Pageview при клиентской навигации (первый заход уже шлёт init/config). */
export const trackPageView = (url: string) => {
  if (typeof window === 'undefined') return
  const path = url.split(/[?#]/)[0] || '/'

  if (GA4_MEASUREMENT_ID && typeof window.gtag === 'function') {
    window.gtag('config', GA4_MEASUREMENT_ID, { page_path: path })
  }

  if (YANDEX_METRIKA_ID && typeof window.ym === 'function') {
    window.ym(YANDEX_METRIKA_ID, 'hit', path)
  }
}
