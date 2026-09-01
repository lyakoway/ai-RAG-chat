import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { initialPref } from './prefs'

export type Lang = 'ru' | 'en'

const LANGS: readonly Lang[] = ['ru', 'en']

/** Flat translation dictionary. `{var}` placeholders are filled by t(key, vars). */
const dict = {
  ru: {
    brandSub: 'Поиск по документам',
    newChat: 'Новый чат',
    searchSettings: 'Настройки поиска',
    historyEmpty: 'История пуста. Задайте первый вопрос.',
    groupToday: 'Сегодня',
    groupWeek: 'Последние 7 дней',
    groupEarlier: 'Ранее',
    deleteConversation: 'Удалить диалог',
    themeLight: 'Светлая тема',
    themeDark: 'Тёмная тема',
    langSwitch: 'English',
    menuTitle: 'Меню и настройки',

    model: 'Модель',
    category: 'Категория',
    allCategories: 'Все категории',
    documents: 'Документы',
    available: 'Доступна',
    unavailable: 'Нет ключа / офлайн',
    mode: 'Режим',
    modeRag: 'RAG Chat',
    modeAgent: 'AI Агент',
    modeSearch: 'Векторный поиск',
    modeRagHint: 'Один поиск → ответ',
    modeAgentHint: 'Шаги и инструменты',
    modeSearchHint: 'Фрагменты без LLM',

    searchWelcomeTitle: 'Векторный поиск по документам',
    searchWelcomeSub: 'Семантический поиск на fastembed: находим фрагменты по смыслу, а не по ключевым словам. Без LLM — только эмбеддинги и векторная база.',
    searchPlaceholder: 'Что искать в документах…',
    searchButton: 'Найти',
    searchHint: 'Enter — найти. Поиск идёт по фрагментам загруженных документов.',
    searchEmpty: 'Ничего не найдено. Попробуйте переформулировать запрос.',
    searchResults: 'Фрагментов: {count}',
    searchTook: '{ms} мс',
    searchSuggestion1: 'Какие условия удалённой работы?',
    searchSuggestion2: 'Тарифы и скидки',
    searchSuggestion3: 'Сроки и этапы тестирования',

    welcomeTitle: 'Чат с вашими документами',
    welcomeSub: 'Загрузите PDF, Word или Excel и задавайте вопросы — ответы приходят со ссылками на страницы-источники.',
    welcomeTitleAgent: 'AI-агент по вашим документам',
    welcomeSubAgent: 'Агент сам вызывает инструменты: смотрит список файлов, ищет фрагменты, затем отвечает. Шаги видны в ленте.',
    welcomeNote: 'Пока нет готовых документов. Откройте панель «Документы» справа и загрузите файлы.',
    suggestion1: 'Кратко перескажи ключевые положения документа',
    suggestion2: 'Какие сроки и условия упоминаются?',
    suggestion3: 'Найди цифры и суммы в таблицах',
    agentSuggestion1: 'Сравни ключевые условия в загруженных документах',
    agentSuggestion2: 'Найди все сроки и суммы, затем кратко сведи',
    agentSuggestion3: 'Какие документы есть и о чём каждый?',

    composerPlaceholder: 'Спросите что-нибудь…',
    composerHint: 'Enter — отправить · Shift+Enter — новая строка. Ответы основаны на загруженных документах.',
    agentSteps: 'Шаги агента',
    agentThinking: 'думает…',
    agentWorking: 'Выполняет следующий шаг…',
    agentToolSearch: 'Поиск по документам',
    agentToolList: 'Список документов',
    agentToolGeneric: 'Инструмент: {name}',
    stop: 'Остановить',
    sendHint: 'Отправить (Enter)',

    sources: 'Источники · {count}',
    sourceN: 'Источник {n}',
    openSource: 'Открыть источник',
    page: 'стр. {n}',
    feedbackUp: 'Ответ был полезен',
    feedbackDown: 'Ответ можно улучшить',
    modelThinking: 'Модель размышляет — это может занять до минуты…',
    providerSlow: 'Z.ai отвечает с задержкой — продолжаем…',
    voiceInput: 'Голосовой ввод',

    providerErrorTitle: 'Модель недоступна',
    providerErrorBody:
      'Выбранный LLM-провайдер отклонил запрос — чаще всего это значит, что исчерпан баланс аккаунта или неверный API-ключ. Пополните баланс провайдера, выберите другую модель в селекторе — или напишите нам, поможем настроить.',
    providerErrorContact: 'Связаться с нами',
    providerErrorClose: 'Закрыть',
    providerErrorDetails: 'Подробности',

    hidePanel: 'Скрыть панель',
    categoryPlaceholder: 'Например: HR, Финансы, Договоры',
    dropzoneIdle: 'Перетащите файлы или нажмите',
    dropzoneUploading: 'Загрузка…',
    dropzoneSub: 'PDF · Word · Excel · можно несколько сразу',
    docsEmpty: 'Документы ещё не загружены.',
    docsEmptyLang: 'Документов на этом языке нет. Переключите язык или загрузите свои файлы.',
    demoDocsBtn: 'Загрузить демо-документы',
    docOpen: 'Открыть просмотр',
    docDownload: 'Скачать файл',
    indexing: 'Индексация…',
    errorPrefix: 'Ошибка',
    deleteDoc: 'Удалить',
    docStats: '{pages} стр · {chunks} фрагм.',
    uploadError: 'Ошибка загрузки',

    viewerNewTab: 'В новой вкладке',
    viewerClose: 'Закрыть (Esc)',
    viewerPreviewUnsupported: 'Предпросмотр в браузере доступен для PDF, DOCX и Excel (XLSX/XLS).',
    viewerDocxLoading: 'Загрузка документа…',
    viewerDocxError: 'Не удалось показать DOCX. Скачайте файл или откройте в новой вкладке.',
    viewerXlsxLoading: 'Загрузка таблицы…',
    viewerXlsxError: 'Не удалось показать Excel. Скачайте файл или откройте в новой вкладке.',
    viewerXlsxEmpty: 'Лист пуст.',
    viewerXlsxTruncated: 'Показаны первые {shown} из {total} строк.',
    viewerFromPage: 'Цитата взята из фрагмента стр. {n}.',
    viewerDownload: 'Скачать / открыть файл',
  },
  en: {
    brandSub: 'Search your documents',
    newChat: 'New chat',
    searchSettings: 'Search settings',
    historyEmpty: 'No history yet. Ask your first question.',
    groupToday: 'Today',
    groupWeek: 'Last 7 days',
    groupEarlier: 'Earlier',
    deleteConversation: 'Delete conversation',
    themeLight: 'Light theme',
    themeDark: 'Dark theme',
    langSwitch: 'Русский',
    menuTitle: 'Menu & settings',

    model: 'Model',
    category: 'Category',
    allCategories: 'All categories',
    documents: 'Documents',
    available: 'Available',
    unavailable: 'No key / offline',
    mode: 'Mode',
    modeRag: 'RAG Chat',
    modeAgent: 'AI Agent',
    modeSearch: 'Vector search',
    modeRagHint: 'One retrieve → answer',
    modeAgentHint: 'Steps & tools',
    modeSearchHint: 'Chunks without LLM',

    searchWelcomeTitle: 'Vector search over your documents',
    searchWelcomeSub: 'fastembed semantic search: matches chunks by meaning, not keywords. No LLM — just embeddings and a vector store.',
    searchPlaceholder: 'What to search in documents…',
    searchButton: 'Search',
    searchHint: 'Enter to search. Queries run over fragments of uploaded documents.',
    searchEmpty: 'Nothing found. Try rephrasing the query.',
    searchResults: 'Fragments: {count}',
    searchTook: '{ms} ms',
    searchSuggestion1: 'Remote work conditions',
    searchSuggestion2: 'Pricing and discounts',
    searchSuggestion3: 'Testing timeline and stages',

    welcomeTitle: 'Chat with your documents',
    welcomeSub: 'Upload PDF, Word or Excel and ask questions — answers come with links to their source pages.',
    welcomeTitleAgent: 'AI agent over your documents',
    welcomeSubAgent: 'The agent calls tools itself: lists files, searches chunks, then answers. Steps show up in the thread.',
    welcomeNote: 'No ready documents yet. Open the “Documents” panel on the right and upload files.',
    suggestion1: 'Summarize the key points of the document',
    suggestion2: 'What deadlines and conditions are mentioned?',
    suggestion3: 'Find figures and totals in the tables',
    agentSuggestion1: 'Compare key terms across the uploaded documents',
    agentSuggestion2: 'Find all deadlines and amounts, then summarize',
    agentSuggestion3: 'What documents are there and what is each about?',

    composerPlaceholder: 'Ask anything…',
    composerHint: 'Enter to send · Shift+Enter for a new line. Answers are grounded in your uploaded documents.',
    agentSteps: 'Agent steps',
    agentThinking: 'thinking…',
    agentWorking: 'Running next step…',
    agentToolSearch: 'Search documents',
    agentToolList: 'List documents',
    agentToolGeneric: 'Tool: {name}',
    stop: 'Stop',
    sendHint: 'Send (Enter)',

    sources: 'Sources · {count}',
    sourceN: 'Source {n}',
    openSource: 'Open source',
    page: 'p. {n}',
    feedbackUp: 'This answer was helpful',
    feedbackDown: 'This answer could be better',
    modelThinking: 'The model is thinking — this can take up to a minute…',
    providerSlow: 'Z.ai is responding slowly — still working…',
    voiceInput: 'Voice input',

    providerErrorTitle: 'Model unavailable',
    providerErrorBody:
      'The selected LLM provider declined the request — most often this means the account balance is exhausted or the API key is invalid. Top up the provider balance, choose another model in the selector, or contact us and we will help you set it up.',
    providerErrorContact: 'Contact us',
    providerErrorClose: 'Close',
    providerErrorDetails: 'Details',

    hidePanel: 'Hide panel',
    categoryPlaceholder: 'e.g. HR, Finance, Contracts',
    dropzoneIdle: 'Drag files here or click',
    dropzoneUploading: 'Uploading…',
    dropzoneSub: 'PDF · Word · Excel · multiple at once',
    docsEmpty: 'No documents uploaded yet.',
    docsEmptyLang: 'No documents in this language. Switch the language or upload your files.',
    demoDocsBtn: 'Load demo documents',
    docOpen: 'Open viewer',
    docDownload: 'Download file',
    indexing: 'Indexing…',
    errorPrefix: 'Error',
    deleteDoc: 'Delete',
    docStats: '{pages} pp · {chunks} chunks',
    uploadError: 'Upload failed',

    viewerNewTab: 'Open in new tab',
    viewerClose: 'Close (Esc)',
    viewerPreviewUnsupported: 'In-browser preview is available for PDF, DOCX and Excel (XLSX/XLS).',
    viewerDocxLoading: 'Loading document…',
    viewerDocxError: 'Could not preview this DOCX. Download it or open in a new tab.',
    viewerXlsxLoading: 'Loading spreadsheet…',
    viewerXlsxError: 'Could not preview this Excel file. Download it or open in a new tab.',
    viewerXlsxEmpty: 'This sheet is empty.',
    viewerXlsxTruncated: 'Showing the first {shown} of {total} rows.',
    viewerFromPage: 'Citation taken from a fragment on p. {n}.',
    viewerDownload: 'Download / open file',
  },
} as const

export type TKey = keyof (typeof dict)['ru']

interface I18nValue {
  lang: Lang
  setLang: (l: Lang) => void
  toggleLang: () => void
  t: (key: TKey, vars?: Record<string, string | number>) => string
}

const I18nContext = createContext<I18nValue | null>(null)

export function I18nProvider({ children }: { children: ReactNode }) {
  // Язык по умолчанию — английский (URL ?lang= и localStorage перекрывают).
  const [lang, setLang] = useState<Lang>(() => initialPref('lang', LANGS, 'en'))

  useEffect(() => {
    localStorage.setItem('lang', lang)
    document.documentElement.lang = lang
  }, [lang])

  const t = (key: TKey, vars?: Record<string, string | number>) => {
    let s: string = dict[lang][key] ?? dict.ru[key] ?? key
    if (vars) {
      for (const [k, v] of Object.entries(vars)) s = s.replace(`{${k}}`, String(v))
    }
    return s
  }

  const toggleLang = () => setLang(lang === 'ru' ? 'en' : 'ru')

  return (
    <I18nContext.Provider value={{ lang, setLang, toggleLang, t }}>
      {children}
    </I18nContext.Provider>
  )
}

export function useI18n(): I18nValue {
  const ctx = useContext(I18nContext)
  if (!ctx) throw new Error('useI18n must be used within I18nProvider')
  return ctx
}
