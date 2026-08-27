import type {
  Conversation,
  ConversationDetail,
  DocumentItem,
  ModelInfo,
  SearchResponse,
} from './types'

const BASE = '/api'

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body.detail ?? detail
    } catch {
      /* ignore */
    }
    throw new Error(detail)
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T)
}

export const api = {
  // ---- Models ----
  listModels: () => fetch(`${BASE}/models`).then(json<ModelInfo[]>),

  // ---- Documents ----
  listDocuments: (category?: string) => {
    const q = category && category !== 'All' ? `?category=${encodeURIComponent(category)}` : ''
    return fetch(`${BASE}/documents${q}`).then(json<DocumentItem[]>)
  },
  listCategories: () => fetch(`${BASE}/documents/categories`).then(json<string[]>),
  uploadDocument: (file: File, category: string) => {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('category', category)
    return fetch(`${BASE}/documents`, { method: 'POST', body: fd }).then(json<DocumentItem>)
  },
  deleteDocument: (id: string) =>
    fetch(`${BASE}/documents/${id}`, { method: 'DELETE' }).then(json<void>),
  loadDemoDocuments: () =>
    fetch(`${BASE}/documents/demo`, { method: 'POST' }).then(json<DocumentItem[]>),
  documentFileUrl: (id: string) => `${BASE}/documents/${id}/file`,

  // ---- Vector search ----
  search: (q: string, opts?: { category?: string; top_k?: number }) => {
    const p = new URLSearchParams({ q })
    if (opts?.category && opts.category !== 'All') p.set('category', opts.category)
    if (opts?.top_k) p.set('top_k', String(opts.top_k))
    return fetch(`${BASE}/search?${p}`).then(json<SearchResponse>)
  },

  // ---- Conversations ----
  listConversations: () => fetch(`${BASE}/conversations`).then(json<Conversation[]>),
  getConversation: (id: string) =>
    fetch(`${BASE}/conversations/${id}`).then(json<ConversationDetail>),
  renameConversation: (id: string, title: string) =>
    fetch(`${BASE}/conversations/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title }),
    }).then(json<Conversation>),
  deleteConversation: (id: string) =>
    fetch(`${BASE}/conversations/${id}`, { method: 'DELETE' }).then(json<void>),
}
