export interface Source {
  document_id: string
  filename: string
  page: number | null
  snippet: string
  score: number | null
  chunk_index: number | null
}

export interface DocumentItem {
  id: string
  filename: string
  content_type: string
  category: string
  size_bytes: number
  page_count: number
  chunk_count: number
  status: 'processing' | 'ready' | 'error'
  error: string | null
  lang: string | null
  pair_key: string | null
  created_at: string
}

export type ChatMode = 'rag' | 'agent' | 'search'

export interface AgentStep {
  index: number
  type: string
  name: string
  args?: Record<string, unknown>
  ok?: boolean
  detail?: string
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  sources?: Source[] | null
  agent_steps?: AgentStep[] | null
  feedback?: string | null
  created_at?: string
  streaming?: boolean
}

export interface Conversation {
  id: string
  title: string
  model: string | null
  created_at: string
  updated_at: string
}

export interface ConversationDetail extends Conversation {
  messages: ChatMessage[]
}

export interface ModelInfo {
  id: string
  provider: 'openai' | 'anthropic' | 'ollama' | 'mock'
  label: string
  available: boolean
  description: string
}

export interface SearchResponse {
  query: string
  took_ms: number
  embedding_model: string
  results: Source[]
}
