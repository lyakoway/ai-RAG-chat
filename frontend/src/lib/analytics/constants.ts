export const YANDEX_METRIKA_ID = import.meta.env.VITE_YANDEX_METRIKA_ID
export const GA4_MEASUREMENT_ID = import.meta.env.VITE_GA4_MEASUREMENT_ID

/**
 * Имена событий — одинаковые для GA4 и целей Яндекс.Метрики (reachGoal).
 * Описание всех событий: docs/analytics-events.md
 */
export const AnalyticsEvent = {
  CHAT_MESSAGE_SEND: 'chat_message_send',
  CHAT_NEW: 'chat_new',
  CHAT_SUGGESTION_CLICK: 'chat_suggestion_click',
  DOCUMENT_UPLOAD: 'document_upload',
  DOCUMENT_DELETE: 'document_delete',
  DOCS_PANEL_TOGGLE: 'docs_panel_toggle',
  CATEGORY_FILTER: 'category_filter',
  MODEL_CHANGE: 'model_change',
  THEME_TOGGLE: 'theme_toggle',
  LANGUAGE_TOGGLE: 'language_toggle',
  /** Клик по имени файла источника → открытие просмотрщика */
  SOURCE_CLICK: 'source_click',
  /** Клик по маркеру [n] в ответе */
  SOURCE_CITATION_CLICK: 'source_citation_click',
  /** Раскрыть / свернуть блок «Источники» */
  SOURCES_TOGGLE: 'sources_toggle',
} as const

export type AnalyticsEventName =
  (typeof AnalyticsEvent)[keyof typeof AnalyticsEvent]
