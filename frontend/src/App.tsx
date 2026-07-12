import { useCallback, useEffect, useMemo, useState } from 'react'
import './App.css'
import './styles/chat.css'
import './styles/documents.css'
import { Sidebar } from './components/Sidebar'
import { TopBar } from './components/TopBar'
import { ChatView } from './components/ChatView'
import { DocumentsPanel } from './components/DocumentsPanel'
import { DocumentViewer } from './components/DocumentViewer'
import { useChat } from './hooks/useChat'
import { api } from './lib/api'
import type { Conversation, DocumentItem, ModelInfo, Source } from './lib/types'

type Theme = 'light' | 'dark'

export default function App() {
  // ---- Theme ----
  const [theme, setTheme] = useState<Theme>(
    () => (localStorage.getItem('theme') as Theme) || 'dark',
  )
  useEffect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem('theme', theme)
  }, [theme])

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
  const { messages, isStreaming, send, stop, reset } = useChat({
    conversationId,
    setConversationId,
    onFinished: refreshConversations,
  })

  const readyDocs = useMemo(
    () => documents.filter((d) => d.status === 'ready').length,
    [documents],
  )

  const newChat = useCallback(() => {
    setConversationId(null)
    reset([])
    setSidebarOpen(false)
  }, [reset])

  const openConversation = useCallback(
    async (id: string) => {
      const detail = await api.getConversation(id)
      setConversationId(id)
      if (detail.model) setModel(detail.model)
      reset(detail.messages)
      setSidebarOpen(false)
    },
    [reset],
  )

  const deleteConversation = useCallback(
    async (id: string) => {
      await api.deleteConversation(id)
      if (id === conversationId) newChat()
      refreshConversations()
    },
    [conversationId, newChat, refreshConversations],
  )

  const handleSend = useCallback(
    (text: string) => send(text, { model, category: category === 'All' ? null : category }),
    [send, model, category],
  )

  return (
    <div className="app">
      <Sidebar
        open={sidebarOpen}
        conversations={conversations}
        activeId={conversationId}
        onNew={newChat}
        onOpen={openConversation}
        onDelete={deleteConversation}
        theme={theme}
        onToggleTheme={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
        models={models}
        model={model}
        onModelChange={setModel}
        categories={categories}
        category={category}
        onCategoryChange={setCategory}
      />

      <main className="main">
        <TopBar
          models={models}
          model={model}
          onModelChange={setModel}
          categories={categories}
          category={category}
          onCategoryChange={setCategory}
          docsOpen={docsOpen}
          onToggleDocs={() => setDocsOpen((v) => !v)}
          readyDocs={readyDocs}
          onMenu={() => setSidebarOpen(true)}
        />
        <ChatView
          messages={messages}
          isStreaming={isStreaming}
          onSend={handleSend}
          onStop={stop}
          hasDocuments={readyDocs > 0}
          onOpenSource={setViewerSource}
        />
      </main>

      {docsOpen && (
        <DocumentsPanel
          documents={documents}
          categories={categories}
          onUploaded={refreshDocs}
          onDeleted={refreshDocs}
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
    </div>
  )
}
