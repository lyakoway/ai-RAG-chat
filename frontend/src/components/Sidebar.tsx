import { IconChat, IconGlobe, IconMoon, IconPlus, IconSpark, IconSun, IconTrash } from '../lib/icons'
import { AnalyticsEvent, trackEvent } from '../lib/analytics'
import { Filters } from './Filters'
import { useI18n, type TKey } from '../lib/i18n'
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

const GROUP_KEYS: Record<string, TKey> = {
  today: 'groupToday',
  week: 'groupWeek',
  earlier: 'groupEarlier',
}

function groupByDate(items: Conversation[]) {
  const groups: Record<string, Conversation[]> = {}
  const now = Date.now()
  for (const c of items) {
    const days = (now - new Date(c.updated_at).getTime()) / 86400000
    const key = days < 1 ? 'today' : days < 7 ? 'week' : 'earlier'
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
  const { t, toggleLang } = useI18n()
  const groups = groupByDate(conversations)
  const order = ['today', 'week', 'earlier']

  return (
    <aside className={`sidebar ${open ? 'open' : ''}`}>
      <div className="brand">
        <div className="brand-logo"><IconSpark width={20} height={20} /></div>
        <div>
          <div className="brand-title">RAG Chat</div>
          <div className="brand-sub">{t('brandSub')}</div>
        </div>
      </div>

      <button className="btn-new" onClick={onNew}>
        <IconPlus /> {t('newChat')}
      </button>

      <div className="sidebar-filters">
        <span className="sidebar-filters-label">{t('searchSettings')}</span>
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
        {conversations.length === 0 && <p className="conv-empty">{t('historyEmpty')}</p>}
        {order.map((key) =>
          groups[key]?.length ? (
            <div key={key} className="conv-group">
              <div className="conv-group-label">{t(GROUP_KEYS[key])}</div>
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
                    title={t('deleteConversation')}
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
          {theme === 'dark' ? t('themeLight') : t('themeDark')}
        </button>
        <button
          className="theme-toggle"
          onClick={() => {
            trackEvent(AnalyticsEvent.LANGUAGE_TOGGLE)
            toggleLang()
          }}
        >
          <IconGlobe />
          {t('langSwitch')}
        </button>
      </div>
    </aside>
  )
}
