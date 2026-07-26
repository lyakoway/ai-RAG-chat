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

    welcomeTitle: 'Чат с вашими документами',
    welcomeSub: 'Загрузите PDF, Word или Excel и задавайте вопросы — ответы приходят со ссылками на страницы-источники.',
    welcomeNote: 'Пока нет готовых документов. Откройте панель «Документы» справа и загрузите файлы.',
    suggestion1: 'Кратко перескажи ключевые положения документа',
    suggestion2: 'Какие сроки и условия упоминаются?',
    suggestion3: 'Найди цифры и суммы в таблицах',

    composerPlaceholder: 'Спросите что-нибудь о ваших документах…',
    composerHint: 'Enter — отправить · Shift+Enter — новая строка. Ответы основаны на загруженных документах.',
    stop: 'Остановить',
    sendHint: 'Отправить (Enter)',

    sources: 'Источники · {count}',
    sourceN: 'Источник {n}',
    openSource: 'Открыть источник',
    page: 'стр. {n}',

    hidePanel: 'Скрыть панель',
    categoryPlaceholder: 'Например: HR, Финансы, Договоры',
    dropzoneIdle: 'Перетащите файлы или нажмите',
    dropzoneUploading: 'Загрузка…',
    dropzoneSub: 'PDF · Word · Excel · можно несколько сразу',
    docsEmpty: 'Документы ещё не загружены.',
    indexing: 'Индексация…',
    errorPrefix: 'Ошибка',
    deleteDoc: 'Удалить',
    docStats: '{pages} стр · {chunks} фрагм.',
    uploadError: 'Ошибка загрузки',

    viewerNewTab: 'В новой вкладке',
    viewerClose: 'Закрыть (Esc)',
    viewerPdfOnly: 'Предпросмотр в браузере доступен только для PDF.',
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

    welcomeTitle: 'Chat with your documents',
    welcomeSub: 'Upload PDF, Word or Excel and ask questions — answers come with links to their source pages.',
    welcomeNote: 'No ready documents yet. Open the “Documents” panel on the right and upload files.',
    suggestion1: 'Summarize the key points of the document',
    suggestion2: 'What deadlines and conditions are mentioned?',
    suggestion3: 'Find figures and totals in the tables',

    composerPlaceholder: 'Ask anything about your documents…',
    composerHint: 'Enter to send · Shift+Enter for a new line. Answers are grounded in your uploaded documents.',
    stop: 'Stop',
    sendHint: 'Send (Enter)',

    sources: 'Sources · {count}',
    sourceN: 'Source {n}',
    openSource: 'Open source',
    page: 'p. {n}',

    hidePanel: 'Hide panel',
    categoryPlaceholder: 'e.g. HR, Finance, Contracts',
    dropzoneIdle: 'Drag files here or click',
    dropzoneUploading: 'Uploading…',
    dropzoneSub: 'PDF · Word · Excel · multiple at once',
    docsEmpty: 'No documents uploaded yet.',
    indexing: 'Indexing…',
    errorPrefix: 'Error',
    deleteDoc: 'Delete',
    docStats: '{pages} pp · {chunks} chunks',
    uploadError: 'Upload failed',

    viewerNewTab: 'Open in new tab',
    viewerClose: 'Close (Esc)',
    viewerPdfOnly: 'In-browser preview is available for PDF only.',
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
  const [lang, setLang] = useState<Lang>(() => initialPref('lang', LANGS, 'ru'))

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
