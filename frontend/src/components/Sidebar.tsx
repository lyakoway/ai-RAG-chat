import { IconChat, IconMoon, IconPlus, IconSpark, IconSun, IconTrash } from '../lib/icons'
import { Filters } from './Filters'
import type { Conversation, ModelInfo } from '../lib/types'

interface Props {
  open: boolean // mobile drawer state
  conversations: Conversation[]
  activeId: string | null
  onNew: () => void
  onOpen: (id: string) => void
  onDelete: (id: string) => void
  theme: 'light' | 'dark'
  onToggleTheme: () => void
  // Model/category selectors — shown here only on mobile (in the drawer).
  models: ModelInfo[]
  model: string
  onModelChange: (id: string) => void
  categories: string[]
  category: string
  onCategoryChange: (c: string) => void
}

function groupByDate(items: Conversation[]) {
  const groups: Record<string, Conversation[]> = {}
  const now = Date.now()
  for (const c of items) {
    const days = (now - new Date(c.updated_at).getTime()) / 86400000
    const key = days < 1 ? 'Сегодня' : days < 7 ? 'Последние 7 дней' : 'Ранее'
    ;(groups[key] ??= []).push(c)
  }
  return groups
}

export function Sidebar({
  open,
  conversations,
  activeId,
  onNew,
  onOpen,
  onDelete,
  theme,
  onToggleTheme,
  models,
  model,
  onModelChange,
  categories,
  category,
  onCategoryChange,
}: Props) {
  const groups = groupByDate(conversations)
  const order = ['Сегодня', 'Последние 7 дней', 'Ранее']

  return (
    <aside className={`sidebar ${open ? 'open' : ''}`}>
      <div className="brand">
        <div className="brand-logo"><IconSpark width={20} height={20} /></div>
        <div>
          <div className="brand-title">RAG Chat</div>
          <div className="brand-sub">Поиск по документам</div>
        </div>
      </div>

      <button className="btn-new" onClick={onNew}>
        <IconPlus /> Новый чат
      </button>

      <div className="sidebar-filters">
        <span className="sidebar-filters-label">Настройки поиска</span>
        <Filters
          models={models}
          model={model}
          onModelChange={onModelChange}
          categories={categories}
          category={category}
          onCategoryChange={onCategoryChange}
        />
      </div>

      <nav className="conv-list">
        {conversations.length === 0 && (
          <p className="conv-empty">История пуста. Задайте первый вопрос.</p>
        )}
        {order.map((key) =>
          groups[key]?.length ? (
            <div key={key} className="conv-group">
              <div className="conv-group-label">{key}</div>
              {groups[key].map((c) => (
                <div
                  key={c.id}
                  className={`conv-item ${c.id === activeId ? 'active' : ''}`}
                  onClick={() => onOpen(c.id)}
                >
                  <IconChat width={15} height={15} className="conv-icon" />
                  <span className="conv-title">{c.title}</span>
                  <button
                    className="conv-del"
                    title="Удалить диалог"
                    onClick={(e) => {
                      e.stopPropagation()
                      onDelete(c.id)
                    }}
                  >
                    <IconTrash width={15} height={15} />
                  </button>
                </div>
              ))}
            </div>
          ) : null,
        )}
      </nav>

      <div className="sidebar-footer">
        <button className="theme-toggle" onClick={onToggleTheme}>
          {theme === 'dark' ? <IconSun /> : <IconMoon />}
          {theme === 'dark' ? 'Светлая тема' : 'Тёмная тема'}
        </button>
      </div>
    </aside>
  )
}
