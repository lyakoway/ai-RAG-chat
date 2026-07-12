import { useEffect, useRef, useState, type ReactNode } from 'react'
import { IconChevron } from '../lib/icons'

export interface DropdownOption {
  value: string
  label: string
  hint?: string
  disabled?: boolean
  badge?: ReactNode
}

interface Props {
  value: string
  options: DropdownOption[]
  onChange: (value: string) => void
  icon?: ReactNode
  label?: string // shown before selected value
  align?: 'left' | 'right'
}

export function Dropdown({ value, options, onChange, icon, label, align = 'left' }: Props) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const selected = options.find((o) => o.value === value)

  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [open])

  return (
    <div className="dropdown" ref={ref}>
      <button className="dropdown-trigger" onClick={() => setOpen((v) => !v)}>
        {icon}
        {label && <span className="dropdown-label">{label}</span>}
        <span className="dropdown-value">{selected?.label ?? value}</span>
        <IconChevron width={16} height={16} className={`dropdown-caret ${open ? 'up' : ''}`} />
      </button>
      {open && (
        <div className={`dropdown-menu ${align}`}>
          {options.map((o) => (
            <button
              key={o.value}
              className={`dropdown-option ${o.value === value ? 'active' : ''}`}
              disabled={o.disabled}
              onClick={() => {
                onChange(o.value)
                setOpen(false)
              }}
            >
              <span className="dropdown-option-main">
                <span className="dropdown-option-label">{o.label}</span>
                {o.hint && <span className="dropdown-option-hint">{o.hint}</span>}
              </span>
              {o.badge}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
