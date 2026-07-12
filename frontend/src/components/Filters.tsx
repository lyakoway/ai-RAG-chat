import { Dropdown, type DropdownOption } from './Dropdown'
import { IconLayers, IconSpark } from '../lib/icons'
import type { ModelInfo } from '../lib/types'

interface Props {
  models: ModelInfo[]
  model: string
  onModelChange: (id: string) => void
  categories: string[]
  category: string
  onCategoryChange: (c: string) => void
}

const providerLabel: Record<string, string> = {
  openai: 'OpenAI',
  anthropic: 'Anthropic',
  ollama: 'Ollama',
  mock: 'Demo',
}

/** Model + category selectors. Rendered inline in the top bar on desktop,
 *  and stacked inside the sidebar drawer on mobile. */
export function Filters({
  models,
  model,
  onModelChange,
  categories,
  category,
  onCategoryChange,
}: Props) {
  const modelOptions: DropdownOption[] = models.map((m) => ({
    value: m.id,
    label: m.label,
    hint: providerLabel[m.provider] ?? m.provider,
    disabled: !m.available,
    badge: m.available ? (
      <span className="dot dot-on" title="Доступна" />
    ) : (
      <span className="dot dot-off" title="Нет ключа / офлайн" />
    ),
  }))

  const categoryOptions: DropdownOption[] = [
    { value: 'All', label: 'Все категории' },
    ...categories.map((c) => ({ value: c, label: c })),
  ]

  return (
    <>
      <Dropdown
        value={model}
        options={modelOptions}
        onChange={onModelChange}
        icon={<IconSpark width={16} height={16} />}
        label="Модель"
      />
      <Dropdown
        value={category}
        options={categoryOptions}
        onChange={onCategoryChange}
        icon={<IconLayers width={16} height={16} />}
        label="Категория"
      />
    </>
  )
}
