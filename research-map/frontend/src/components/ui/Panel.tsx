import { useId, useState, type ReactNode } from 'react'
import { ChevronDown } from 'lucide-react'

type PanelProps = {
  title?: ReactNode
  icon?: ReactNode
  actions?: ReactNode
  children: ReactNode
  /** `glass` floats over the map; `solid` sits on page backgrounds. */
  variant?: 'glass' | 'solid'
  collapsible?: boolean
  defaultOpen?: boolean
  className?: string
  bodyClassName?: string
}

export function Panel({ title, icon, actions, children, variant = 'solid', collapsible, defaultOpen = true, className = '', bodyClassName = '' }: PanelProps) {
  const [open, setOpen] = useState(defaultOpen)
  const bodyId = useId()
  const surface = variant === 'glass' ? 'glass' : 'bg-surface border border-line shadow-[var(--shadow-sm)]'
  const header = title !== undefined && (
    <div className="flex items-center gap-2 px-3.5 pt-3 pb-2">
      {icon && <span className="text-accent flex-none" aria-hidden>{icon}</span>}
      <h2 className="m-0 min-w-0 flex-1 truncate text-[12.5px] font-semibold tracking-[.01em] text-fg">{title}</h2>
      {actions}
      {collapsible && (
        <button type="button" onClick={() => setOpen(value => !value)} aria-expanded={open} aria-controls={bodyId}
          className="-mr-1 grid size-6 place-items-center rounded-md text-fg-subtle transition-colors hover:bg-surface-3 hover:text-fg"
          aria-label={open ? 'Thu gọn' : 'Mở rộng'}>
          <ChevronDown size={15} className={`transition-transform duration-200 ${open ? '' : '-rotate-90'}`} />
        </button>
      )}
    </div>
  )
  return (
    <section className={`rounded-[var(--radius-lg)] ${surface} ${className}`}>
      {header}
      {(!collapsible || open) && <div id={bodyId} className={`px-3.5 pb-3.5 ${title === undefined ? 'pt-3.5' : ''} ${bodyClassName}`}>{children}</div>}
    </section>
  )
}

/** Small uppercase group heading inside a panel. */
export function SectionLabel({ children, icon, trailing }: { children: ReactNode; icon?: ReactNode; trailing?: ReactNode }) {
  return (
    <div className="mb-1.5 mt-3 flex items-center gap-1.5 first:mt-0">
      {icon && <span className="text-fg-subtle" aria-hidden>{icon}</span>}
      <h3 className="m-0 flex-1 text-[10.5px] font-bold uppercase tracking-[.08em] text-fg-subtle">{children}</h3>
      {trailing}
    </div>
  )
}

/** Label/value rows for provenance and metadata. */
export function KeyValue({ items }: { items: Array<[ReactNode, ReactNode] | null | false | undefined> }) {
  const rows = items.filter(Boolean) as Array<[ReactNode, ReactNode]>
  return (
    <dl className="m-0 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[12px]">
      {rows.map(([key, value], index) => (
        <div key={index} className="contents">
          <dt className="text-fg-subtle">{key}</dt>
          <dd className="m-0 min-w-0 break-words text-right text-fg tabular">{value ?? '—'}</dd>
        </div>
      ))}
    </dl>
  )
}

/** Inline note used for provenance, disclaimers and honesty labels. */
export function Note({ children, tone = 'neutral', icon }: { children: ReactNode; tone?: 'neutral' | 'mock' | 'warn' | 'info' | 'danger'; icon?: ReactNode }) {
  const toneClass = {
    neutral: 'bg-surface-2 text-fg-muted border-line',
    mock: 'bg-mock-bg text-mock border-[var(--mock-line)]',
    warn: 'bg-warn-bg text-warn border-[var(--warn-line)]',
    info: 'bg-info-bg text-info border-[var(--info-line)]',
    danger: 'bg-danger-bg text-danger border-[var(--danger-line)]',
  }[tone]
  return (
    <div className={`flex gap-2 rounded-[var(--radius-sm)] border px-2.5 py-2 text-[11.5px] leading-snug ${toneClass}`}>
      {icon && <span className="mt-px flex-none" aria-hidden>{icon}</span>}
      <div className="min-w-0">{children}</div>
    </div>
  )
}
