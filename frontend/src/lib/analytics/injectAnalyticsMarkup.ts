import { GA4_MEASUREMENT_ID, YANDEX_METRIKA_ID } from './constants'

let injected = false

const appendInlineScript = (html: string) => {
  const script = document.createElement('script')
  script.textContent = html
  document.head.appendChild(script)
}

const appendExternalScript = (src: string) => {
  const script = document.createElement('script')
  script.async = true
  script.src = src
  document.head.appendChild(script)
}

const injectYandexMetrika = () => {
  if (!YANDEX_METRIKA_ID) return
  const id = YANDEX_METRIKA_ID
  appendInlineScript(
    `(function(m,e,t,r,i,k,a){m[i]=m[i]||function(){(m[i].a=m[i].a||[]).push(arguments)};m[i].l=1*new Date();k=e.createElement(t),a=e.getElementsByTagName(t)[0],k.async=1,k.src=r,a.parentNode.insertBefore(k,a)})(window, document, "script", "https://mc.yandex.ru/metrika/tag.js", "ym");ym(${id}, "init", {clickmap:true,trackLinks:true,accurateTrackBounce:true,webvisor:true});`,
  )

  const noscript = document.createElement('noscript')
  const wrap = document.createElement('div')
  const img = document.createElement('img')
  img.src = `https://mc.yandex.ru/watch/${id}`
  img.alt = ''
  img.style.position = 'absolute'
  img.style.left = '-9999px'
  wrap.appendChild(img)
  noscript.appendChild(wrap)
  document.body.appendChild(noscript)
}

const injectGa4 = () => {
  if (!GA4_MEASUREMENT_ID) return
  const id = GA4_MEASUREMENT_ID
  appendExternalScript(`https://www.googletagmanager.com/gtag/js?id=${id}`)
  appendInlineScript(
    `window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}gtag('js',new Date());gtag('config','${id}');`,
  )
}

/**
 * Разметка Яндекс.Метрики и GA4 (как getAnalyticsMarkup в lyako-way).
 * Для Vite вставляем скрипты в <head> до монтирования React.
 * Без ID в env — no-op.
 */
export function injectAnalyticsMarkup() {
  if (typeof document === 'undefined' || injected) return
  injected = true
  injectYandexMetrika()
  injectGa4()
}
