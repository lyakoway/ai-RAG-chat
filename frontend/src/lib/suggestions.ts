import type { DocumentItem } from './types'

/** Подсказки на welcome-экранах строятся из реально загруженных документов:
 *  вопрос-предикат × документ из библиотеки. Нет документов — статичный фолбэк. */

const PREDICATES: Record<'ru' | 'en', Array<(doc: string) => string>> = {
  ru: [
    (doc) => `Кратко перескажи «${doc}»`,
    (doc) => `Какие ключевые пункты в «${doc}»?`,
    (doc) => `Найди в «${doc}» цифры, суммы и сроки`,
  ],
  en: [
    (doc) => `Summarize “${doc}”`,
    (doc) => `What are the key points in “${doc}”?`,
    (doc) => `Find figures, amounts and deadlines in “${doc}”`,
  ],
}

const FALLBACK: Record<'ru' | 'en', string[]> = {
  ru: [
    'Кратко перескажи ключевые положения документа',
    'Какие сроки и условия упоминаются?',
    'Найди цифры и суммы в таблицах',
  ],
  en: [
    'Summarize the key points of the document',
    'What deadlines and conditions are mentioned?',
    'Find figures and totals in the tables',
  ],
}

function docLabel(filename: string): string {
  const stem = filename.replace(/\.[^.]+$/, '')
  return stem.length > 32 ? stem.slice(0, 32) + '…' : stem
}

export function buildDocumentSuggestions(
  documents: DocumentItem[],
  lang: 'ru' | 'en',
): string[] {
  const stems = [
    ...new Set(
      documents
        .filter((d) => d.status === 'ready')
        .map((d) => docLabel(d.filename)),
    ),
  ]
  if (!stems.length) return FALLBACK[lang]

  const predicates = PREDICATES[lang]
  const out: string[] = []
  const max = Math.max(stems.length, predicates.length)
  for (let i = 0; out.length < 3 && i < max; i++) {
    const question = predicates[i % predicates.length](stems[i % stems.length])
    if (!out.includes(question)) out.push(question)
  }
  return out
}
