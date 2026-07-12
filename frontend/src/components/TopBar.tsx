import { Filters } from './Filters'
import { IconDoc, IconMenu } from '../lib/icons'
import type { ModelInfo } from '../lib/types'

interface Props {
  models: ModelInfo[]
  model: string
  onModelChange: (id: string) => void
  categories: string[]
  category: string
  onCategoryChange: (c: string) => void
  docsOpen: boolean
  onToggleDocs: () => void
  readyDocs: number
  onMenu: () => void
}

export function TopBar({
  models,
  model,
  onModelChange,
  categories,
  category,
  onCategoryChange,
  docsOpen,
  onToggleDocs,
  readyDocs,
  onMenu,
}: Props) {
  return (
    <header className="topbar">
      <button className="menu-btn" onClick={onMenu} title="Меню и настройки">
        <IconMenu width={18} height={18} />
      </button>

      {/* Desktop: selectors live in the bar. On mobile they move into the drawer. */}
      <div className="topbar-left">
        <Filters
          models={models}
          model={model}
          onModelChange={onModelChange}
          categories={categories}
          category={category}
          onCategoryChange={onCategoryChange}
        />
      </div>

      <button
        className={`docs-toggle ${docsOpen ? 'active' : ''}`}
        onClick={onToggleDocs}
        title="Панель документов"
      >
        <IconDoc width={16} height={16} />
        Документы
        <span className="docs-count">{readyDocs}</span>
      </button>
    </header>
  )
}
