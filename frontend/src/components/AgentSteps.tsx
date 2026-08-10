import { IconLayers, IconSpark } from '../lib/icons'
import { useI18n } from '../lib/i18n'
import type { AgentStep } from '../lib/types'

interface Props {
  steps: AgentStep[]
  streaming?: boolean
}

export function AgentSteps({ steps, streaming }: Props) {
  const { t } = useI18n()
  if (!steps.length && !streaming) return null

  const toolLabel = (name: string) => {
    if (name === 'search_documents') return t('agentToolSearch')
    if (name === 'list_documents') return t('agentToolList')
    return t('agentToolGeneric', { name })
  }

  return (
    <div className="agent-steps" aria-label={t('agentSteps')}>
      <div className="agent-steps-head">
        <IconSpark width={14} height={14} />
        <span>{t('agentSteps')}</span>
        {streaming && !steps.length && (
          <span className="agent-steps-live">{t('agentThinking')}</span>
        )}
      </div>
      <ol className="agent-steps-list">
        {steps.map((s) => (
          <li key={s.index} className={`agent-step ${s.ok === false ? 'fail' : ''}`}>
            <span className="agent-step-index">{s.index}</span>
            <div className="agent-step-body">
              <div className="agent-step-name">
                <IconLayers width={13} height={13} />
                {toolLabel(s.name)}
              </div>
              {s.detail && <p className="agent-step-detail">{s.detail}</p>}
            </div>
          </li>
        ))}
        {streaming && (
          <li className="agent-step pending">
            <span className="agent-step-index">…</span>
            <div className="agent-step-body">
              <div className="agent-step-name">{t('agentWorking')}</div>
            </div>
          </li>
        )}
      </ol>
    </div>
  )
}
