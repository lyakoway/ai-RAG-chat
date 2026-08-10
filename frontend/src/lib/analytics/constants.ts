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
  /** Переключатель «Режим: RAG Chat | AI Агент» */
  MODE_CHANGE: 'mode_change',
  /** Успешный ответ в режиме AI Агент (после шагов tools) */
  AGENT_RUN_DONE: 'agent_run_done',
  /** Ошибка / обрыв прогона в режиме AI Агент */
  AGENT_RUN_ERROR: 'agent_run_error',
  THEME_TOGGLE: 'theme_toggle',
  LANGUAGE_TOGGLE: 'language_toggle',
  /** Клик по имени файла источника → открытие просмотрщика */
  SOURCE_CLICK: 'source_click',
  /** Клик по маркеру [n] в ответе */
  SOURCE_CITATION_CLICK: 'source_citation_click',
  /** Раскрыть / свернуть блок «Источники» */
  SOURCES_TOGGLE: 'sources_toggle',
  /** Модалка просмотрщика открыта */
  VIEWER_OPEN: 'viewer_open',
  /** «Скачать / открыть файл» (fallback) */
  VIEWER_DOWNLOAD: 'viewer_download',
  /** «В новой вкладке» */
  VIEWER_NEW_TAB: 'viewer_new_tab',
  /** Закрытие просмотрщика (✕ / Esc / оверлей) */
  VIEWER_CLOSE: 'viewer_close',
} as const

export type AnalyticsEventName =
  (typeof AnalyticsEvent)[keyof typeof AnalyticsEvent]
