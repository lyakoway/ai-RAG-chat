import { useCallback, useEffect, useMemo, useState } from 'react'
import './App.css'
import './styles/chat.css'
import './styles/documents.css'
import './styles/search.css'
import './styles/provider-error.css'
import { Sidebar } from './components/Sidebar'
import { TopBar } from './components/TopBar'
import { ChatView } from './components/ChatView'
import { SearchView } from './components/SearchView'
import { DocumentsPanel } from './components/DocumentsPanel'
import { DocumentViewer } from './components/DocumentViewer'
import { ProviderErrorModal, isProviderError } from './components/ProviderErrorModal'
import { useChat } from './hooks/useChat'
import { AnalyticsEvent, trackEvent } from './lib/analytics'
import { useI18n } from './lib/i18n'
import { api } from './lib/api'
import { initialPref, stripPrefParams } from './lib/prefs'
import type { ChatMode, Conversation, DocumentItem, ModelInfo, Source } from './lib/types'

type Theme = 'light' | 'dark'
const THEMES: readonly Theme[] = ['light', 'dark']
const MODES: readonly ChatMode[] = ['rag', 'agent', 'search']

export default function App() {
  const { lang } = useI18n()

  // ---- Theme ----
  // Initial value may come from ?theme= in the URL (see lib/prefs).
  const [theme, setTheme] = useState<Theme>(() => initialPref('theme', THEMES, 'dark'))
  useEffect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem('theme', theme)
  }, [theme])

  // ---- Chat mode: classic RAG vs multi-step AI agent ----
  const [mode, setMode] = useState<ChatMode>(() => initialPref('mode', MODES, 'rag'))
  useEffect(() => {
    localStorage.setItem('mode', mode)
  }, [mode])

  // URL params (?lang=&theme=&mode=) set the initial state once, then are stripped
  // so the user's own toggles stay authoritative on later reloads.
  useEffect(() => {
    stripPrefParams(['lang', 'theme', 'mode'])
  }, [])

  // ---- Models ----
  const [models, setModels] = useState<ModelInfo[]>([])
  const [model, setModel] = useState('mock')
  useEffect(() => {
    api.listModels().then((m) => {
      setModels(m)
      const firstAvailable = m.find((x) => x.available)
      if (firstAvailable) setModel(firstAvailable.id)
    })
  }, [])

  // ---- Documents + categories ----
  const [documents, setDocuments] = useState<DocumentItem[]>([])
  const [categories, setCategories] = useState<string[]>([])
  const [category, setCategory] = useState('All')
  // On wide screens the docs panel is docked open; on mobile it starts closed
  // (it becomes an overlay drawer there).
  const isWide = typeof window !== 'undefined' && window.innerWidth > 1100
  const [docsOpen, setDocsOpen] = useState(isWide)
  const [sidebarOpen, setSidebarOpen] = useState(false) // mobile drawer only
  const [viewerSource, setViewerSource] = useState<Source | null>(null)

  const refreshDocs = useCallback(async () => {
    const [docs, cats] = await Promise.all([api.listDocuments(), api.listCategories()])
    setDocuments(docs)
    setCategories(cats)
  }, [])
  useEffect(() => {
    refreshDocs()
  }, [refreshDocs])

  // Poll while any document is still processing.
  useEffect(() => {
    if (!documents.some((d) => d.status === 'processing')) return
    const t = setInterval(refreshDocs, 1500)
    return () => clearInterval(t)
  }, [documents, refreshDocs])

  // ---- Conversations ----
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [conversationId, setConversationId] = useState<string | null>(null)
  const refreshConversations = useCallback(async () => {
    setConversations(await api.listConversations())
  }, [])
  useEffect(() => {
    refreshConversations()
  }, [refreshConversations])

  // ---- Chat ----
  const handleTitle = useCallback((cid: string, title: string) => {
    setConversations((prev) => prev.map((c) => (c.id === cid ? { ...c, title } : c)))
  }, [])
  // Автозаголовок пишется фоновой задачей уже после ответа — второй рефреш
  // через 6 с подхватывает его в сайдбар.
  const onFinishedWithTitle = useCallback(() => {
    refreshConversations()
    setTimeout(refreshConversations, 6000)
  }, [refreshConversations])
  const [providerError, setProviderError] = useState<string | null>(null)
  const { messages, isStreaming, send, stop, reset } = useChat({
    conversationId,
    setConversationId,
    onFinished: onFinishedWithTitle,
    onError: (msg) => {
      if (isProviderError(msg)) setProviderError(msg)
    },
    onTitle: handleTitle,
  })

  const readyDocs = useMemo(
    () => documents.filter((d) => d.status === 'ready').length,
    [documents],
  )

  const resetChat = useCallback(() => {
    setConversationId(null)
    reset([])
    setSidebarOpen(false)
  }, [reset])

  const newChat = useCallback(() => {
    trackEvent(AnalyticsEvent.CHAT_NEW)
    resetChat()
  }, [resetChat])

  const openConversation = useCallback(
    async (id: string) => {
      try {
        const detail = await api.getConversation(id)
        setConversationId(id)
        if (detail.model) setModel(detail.model)
        reset(detail.messages)
        setSidebarOpen(false)
      } catch (e) {
        trackEvent(AnalyticsEvent.CONVERSATION_OPEN_ERROR, {
          conversation_id: id,
          message: (e instanceof Error ? e.message : 'open_failed').slice(0, 120),
        })
      }
    },
    [reset],
  )

  const deleteConversation = useCallback(
    async (id: string) => {
      try {
        await api.deleteConversation(id)
        if (id === conversationId) resetChat()
        refreshConversations()
      } catch (e) {
        trackEvent(AnalyticsEvent.CONVERSATION_DELETE_ERROR, {
          conversation_id: id,
          message: (e instanceof Error ? e.message : 'delete_failed').slice(0, 120),
        })
      }
    },
    [conversationId, resetChat, refreshConversations],
  )

  // Блокируем скролл страницы, когда на мобильном открыта шторка
  // (сайдбар или документы) — иначе фон прокручивается под оверлеем.
  useEffect(() => {
    const mq = window.matchMedia('(max-width: 1100px)')
    const update = () => {
      const overlay = (sidebarOpen || docsOpen) && mq.matches
      document.body.classList.toggle('no-scroll', overlay)
    }
    update()
    mq.addEventListener('change', update)
    return () => {
      mq.removeEventListener('change', update)
      document.body.classList.remove('no-scroll')
    }
  }, [sidebarOpen, docsOpen])

  const handleSend = useCallback(
    (text: string) => {
      trackEvent(AnalyticsEvent.CHAT_MESSAGE_SEND, {
        model,
        category: category === 'All' ? 'all' : category,
        mode,
      })
      send(text, {
        model,
        category: category === 'All' ? null : category,
        lang,
        mode,
      })
    },
    [send, model, category, lang, mode],
  )

  const handleModeChange = useCallback(
    (next: ChatMode) => {
      if (next === mode) return
      trackEvent(AnalyticsEvent.MODE_CHANGE, { from: mode, mode: next })
      setMode(next)
    },
    [mode],
  )

  const handleModelChange = useCallback((id: string) => {
    trackEvent(AnalyticsEvent.MODEL_CHANGE, { model: id })
    setModel(id)
  }, [])

  const handleCategoryChange = useCallback((c: string) => {
    trackEvent(AnalyticsEvent.CATEGORY_FILTER, { category: c })
    setCategory(c)
  }, [])

  const handleToggleTheme = useCallback(() => {
    const next = theme === 'dark' ? 'light' : 'dark'
    trackEvent(AnalyticsEvent.THEME_TOGGLE, { theme: next })
    setTheme(next)
  }, [theme])

  const handleOpenSource = useCallback((source: Source) => {
    trackEvent(AnalyticsEvent.SOURCE_CLICK, {
      filename: source.filename,
      ...(source.page != null ? { page: source.page } : {}),
    })
    setViewerSource(source)
  }, [])

  const handleMessageFeedback = useCallback((messageId: string, value: 'up' | 'down' | null) => {
    api.messageFeedback(messageId, value).catch(() => {
      // Оценка не критична: молча игнорируем сбой сети.
    })
  }, [])

  const handleFollowup = useCallback(
    (question: string) => {
      trackEvent(AnalyticsEvent.FOLLOWUP_CLICK, {})
      handleSend(question)
    },
    [handleSend],
  )

  const handleToggleDocs = useCallback(() => {
    setDocsOpen((v) => {
      const next = !v
      trackEvent(AnalyticsEvent.DOCS_PANEL_TOGGLE, { open: next })
      return next
    })
  }, [])

  return (
    <div className="app">
      <Sidebar
        open={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
        conversations={conversations}
        activeId={conversationId}
        onNew={newChat}
        onOpen={openConversation}
        onDelete={deleteConversation}
        theme={theme}
        onToggleTheme={handleToggleTheme}
        models={models}
        model={model}
        onModelChange={handleModelChange}
        categories={categories}
        category={category}
        onCategoryChange={handleCategoryChange}
        mode={mode}
        onModeChange={handleModeChange}
      />

      <main className="main">
        <TopBar
          models={models}
          model={model}
          onModelChange={handleModelChange}
          categories={categories}
          category={category}
          onCategoryChange={handleCategoryChange}
          mode={mode}
          onModeChange={handleModeChange}
          docsOpen={docsOpen}
          onToggleDocs={handleToggleDocs}
          readyDocs={readyDocs}
          onMenu={() => setSidebarOpen(true)}
        />
        {mode === 'search' ? (
          <SearchView
            documents={documents}
            category={category}
            onOpenSource={handleOpenSource}
          />
        ) : (
          <ChatView
            messages={messages}
            isStreaming={isStreaming}
            onSend={handleSend}
            onStop={stop}
            documents={documents}
            onOpenSource={handleOpenSource}
            onFeedback={handleMessageFeedback}
            onFollowup={handleFollowup}
            mode={mode}
          />
        )}
      </main>

      {docsOpen && (
        <DocumentsPanel
          documents={documents}
          categories={categories}
          onUploaded={refreshDocs}
          onDeleted={refreshDocs}
          onOpenSource={handleOpenSource}
          onClose={() => setDocsOpen(false)}
        />
      )}

      {/* Backdrop for mobile drawers (sidebar / docs). */}
      {(sidebarOpen || docsOpen) && (
        <div
          className="drawer-backdrop"
          onClick={() => {
            setSidebarOpen(false)
            setDocsOpen(false)
          }}
        />
      )}

      <DocumentViewer source={viewerSource} onClose={() => setViewerSource(null)} />

      {providerError && (
        <ProviderErrorModal
          message={providerError}
          onClose={() => setProviderError(null)}
        />
      )}
    </div>
  )
}
