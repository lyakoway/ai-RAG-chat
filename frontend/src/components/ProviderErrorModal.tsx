const CONTACTS_URL = 'https://lyakoway.vercel.app/contacts'

import { useI18n } from '../lib/i18n'
import { AnalyticsEvent, trackEvent } from '../lib/analytics'

/** Detects provider-side failures worth explaining in a friendly modal:
 *  exhausted balance (429), quota, invalid/missing API key (401/403). */
export function isProviderError(text: string | undefined | null): boolean {
  if (!text) return false
  return /insufficient balance|please recharge|error code:\s*429|status code:\s*429|баланс|пополн|quota|api key|unauthorized|error code:\s*401|error code:\s*403/i.test(
    text,
  )
}

/**
 * Модалка «Модель недоступна» — перенос из проекта ai-data-pilot:
 * понятное объяснение (баланс / ключ), сырая ошибка в <details>,
 * кнопки «Закрыть» и «Связаться с нами».
 */
export function ProviderErrorModal({
  message,
  onClose,
}: {
  message: string
  onClose: () => void
}) {
  const { t } = useI18n()

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box modal-box-center" onClick={(e) => e.stopPropagation()}>
        <h3 className="modal-title">{t('providerErrorTitle')}</h3>
        <p className="modal-desc">{t('providerErrorBody')}</p>
        <details className="provider-error-detail">
          <summary>{t('providerErrorDetails')}</summary>
          <pre>
            <code>{message.slice(0, 500)}</code>
          </pre>
        </details>
        <div className="modal-actions">
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            {t('providerErrorClose')}
          </button>
          <a
            className="btn btn-primary"
            href={CONTACTS_URL}
            target="_blank"
            rel="noopener noreferrer"
            onClick={() => trackEvent(AnalyticsEvent.PROVIDER_ERROR_CONTACT)}
          >
            {t('providerErrorContact')}
          </a>
        </div>
      </div>
    </div>
  )
}
