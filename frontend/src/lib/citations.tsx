import { Children, cloneElement, isValidElement, type ReactElement, type ReactNode } from 'react'

const CITE_RE = /(\[\d+\])/g

/**
 * Walk React children and turn textual citation markers like `[1]` into
 * clickable buttons. Recurses into elements so citations inside bold/italic
 * still work. `count` bounds valid indices so stray `[9]` isn't clickable.
 */
export function injectCitations(
  children: ReactNode,
  count: number,
  onCite: (index: number) => void,
  titleFor: (n: number) => string,
): ReactNode {
  return Children.map(children, (child) => {
    if (typeof child === 'string') {
      const parts = child.split(CITE_RE)
      return parts.map((part, i) => {
        const m = part.match(/^\[(\d+)\]$/)
        if (m) {
          const n = Number(m[1])
          if (n >= 1 && n <= count) {
            return (
              <button
                key={i}
                type="button"
                className="cite-ref"
                onClick={() => onCite(n - 1)}
                title={titleFor(n)}
              >
                {n}
              </button>
            )
          }
        }
        return part
      })
    }
    if (isValidElement(child)) {
      const el = child as ReactElement<{ children?: ReactNode }>
      if (el.props?.children) {
        return cloneElement(
          el,
          undefined,
          injectCitations(el.props.children, count, onCite, titleFor),
        )
      }
    }
    return child
  })
}
