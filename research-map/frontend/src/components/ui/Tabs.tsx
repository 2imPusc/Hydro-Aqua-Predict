import { useRef, type KeyboardEvent, type ReactNode } from 'react'

type TabsProps<T extends string> = {
  value: T
  onChange: (value: T) => void
  tabs: Array<{ value: T; label: ReactNode; badge?: ReactNode }>
  label: string
}

/** Underline tabs with roving focus (←/→). Panels are rendered by the caller. */
export function Tabs<T extends string>({ value, onChange, tabs, label }: TabsProps<T>) {
  const refs = useRef<Array<HTMLButtonElement | null>>([])
  const onKey = (event: KeyboardEvent, index: number) => {
    if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') return
    event.preventDefault()
    const next = (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length
    refs.current[next]?.focus()
    onChange(tabs[next].value)
  }
  return (
    <div role="tablist" aria-label={label} className="flex gap-1 border-b border-line">
      {tabs.map((tab, index) => {
        const active = tab.value === value
        return (
          <button key={tab.value} ref={element => { refs.current[index] = element }} role="tab" type="button" aria-selected={active} tabIndex={active ? 0 : -1}
            onClick={() => onChange(tab.value)} onKeyDown={event => onKey(event, index)}
            className={`-mb-px flex items-center gap-1.5 border-b-2 px-3 py-2 text-[13px] font-semibold transition-colors ${active ? 'border-accent text-fg' : 'border-transparent text-fg-subtle hover:text-fg'}`}>
            {tab.label}{tab.badge}
          </button>
        )
      })}
    </div>
  )
}
