import { Dropdown, type DropdownOption } from './Dropdown'
import { IconBot, IconLayers, IconSpark } from '../lib/icons'
import { useI18n } from '../lib/i18n'
import type { ChatMode, ModelInfo } from '../lib/types'

interface Props {
  models: ModelInfo[]
  model: string
  onModelChange: (id: string) => void
  categories: string[]
  category: string
  onCategoryChange: (c: string) => void
  mode: ChatMode
  onModeChange: (mode: ChatMode) => void
}

const providerLabel: Record<string, string> = {
  openai: 'OpenAI',
  anthropic: 'Anthropic',
  ollama: 'Ollama',
  mock: 'Demo',
  zai: 'Z.ai',
}

/** Mode + model + category. Rendered in the top bar (desktop) and sidebar (mobile). */
export function Filters({
  models,
  model,
  onModelChange,
  categories,
  category,
  onCategoryChange,
  mode,
  onModeChange,
}: Props) {
  const { t } = useI18n()

  const modeOptions: DropdownOption[] = [
    { value: 'rag', label: t('modeRag'), hint: t('modeRagHint') },
    { value: 'agent', label: t('modeAgent'), hint: t('modeAgentHint') },
  ]

  const modelOptions: DropdownOption[] = models.map((m) => ({
    value: m.id,
    label: m.label,
    hint: providerLabel[m.provider] ?? m.provider,
    disabled: !m.available,
    badge: m.available ? (
      <span className="dot dot-on" title={t('available')} />
    ) : (
      <span className="dot dot-off" title={t('unavailable')} />
    ),
  }))

  const categoryOptions: DropdownOption[] = [
    { value: 'All', label: t('allCategories') },
    ...categories.map((c) => ({ value: c, label: c })),
  ]

  return (
    <>
      <Dropdown
        value={mode}
        options={modeOptions}
        onChange={(v) => onModeChange(v as ChatMode)}
        icon={<IconBot width={16} height={16} />}
        label={t('mode')}
      />
      <Dropdown
        value={model}
        options={modelOptions}
        onChange={onModelChange}
        icon={<IconSpark width={16} height={16} />}
        label={t('model')}
      />
      <Dropdown
        value={category}
        options={categoryOptions}
        onChange={onCategoryChange}
        icon={<IconLayers width={16} height={16} />}
        label={t('category')}
      />
    </>
  )
}
