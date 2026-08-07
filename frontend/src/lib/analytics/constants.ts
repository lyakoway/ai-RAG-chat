export const YANDEX_METRIKA_ID = import.meta.env.VITE_YANDEX_METRIKA_ID
export const GA4_MEASUREMENT_ID = import.meta.env.VITE_GA4_MEASUREMENT_ID

/**
 * Имена событий — одинаковые для GA4 и целей Яндекс.Метрики (reachGoal).
 */
export const AnalyticsEvent = {
  CHAT_MESSAGE_SEND: 'chat_message_send',
  CHAT_NEW: 'chat_new',
  DOCUMENT_UPLOAD: 'document_upload',
  DOCUMENT_OPEN: 'document_open',
  DOCUMENT_DELETE: 'document_delete',
  CATEGORY_FILTER: 'category_filter',
  MODEL_CHANGE: 'model_change',
  THEME_TOGGLE: 'theme_toggle',
  LANGUAGE_TOGGLE: 'language_toggle',
  SOURCE_CLICK: 'source_click',
} as const

export type AnalyticsEventName =
  (typeof AnalyticsEvent)[keyof typeof AnalyticsEvent]
