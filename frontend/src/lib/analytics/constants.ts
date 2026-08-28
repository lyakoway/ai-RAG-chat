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
  /** Ошибка стрима ответа (RAG или агент) */
  CHAT_ERROR: 'chat_error',
  DOCUMENT_UPLOAD: 'document_upload',
  /** Ошибка загрузки файла(ов) в панели документов */
  DOCUMENT_UPLOAD_ERROR: 'document_upload_error',
  /** Кнопка «Загрузить демо-документы» на пустой панели */
  DEMO_DOCS_LOAD: 'demo_documents_load',
  /** Ошибка загрузки демо-пака */
  DEMO_DOCS_LOAD_ERROR: 'demo_documents_load_error',
  /** Скачивание файла из панели документов */
  DOCUMENT_DOWNLOAD: 'document_download',
  /** Оценка ответа 👍/👎 (value: up | down; повторный клик снимает) */
  ANSWER_FEEDBACK: 'answer_feedback',
  /** Клик по follow-up подсказке под ответом */
  FOLLOWUP_CLICK: 'followup_click',
  DOCUMENT_DELETE: 'document_delete',
  DOCUMENT_DELETE_ERROR: 'document_delete_error',
  DOCS_PANEL_TOGGLE: 'docs_panel_toggle',
  CONVERSATION_OPEN_ERROR: 'conversation_open_error',
  CONVERSATION_DELETE_ERROR: 'conversation_delete_error',
  CATEGORY_FILTER: 'category_filter',
  MODEL_CHANGE: 'model_change',
  /** Переключатель «Режим: RAG Chat | AI Агент» */
  MODE_CHANGE: 'mode_change',
  /** Поиск выполнен в режиме «Векторный поиск» */
  VECTOR_SEARCH: 'vector_search',
  /** Ошибка запроса векторного поиска */
  VECTOR_SEARCH_ERROR: 'vector_search_error',
  /** Успешный ответ в режиме AI Агент (после шагов tools) */
  AGENT_RUN_DONE: 'agent_run_done',
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
  /** Ошибка превью в просмотрщике (DOCX / XLSX) */
  VIEWER_ERROR: 'viewer_error',
  /** «Скачать / открыть файл» (fallback) */
  VIEWER_DOWNLOAD: 'viewer_download',
  /** «В новой вкладке» */
  VIEWER_NEW_TAB: 'viewer_new_tab',
  /** Закрытие просмотрщика (✕ / Esc / оверлей) */
  VIEWER_CLOSE: 'viewer_close',
} as const

export type AnalyticsEventName =
  (typeof AnalyticsEvent)[keyof typeof AnalyticsEvent]
