import type { ReactNode } from 'react'

type ToggleProps = {
  checked: boolean
  onChange: (checked: boolean) => void
  label: ReactNode
  description?: ReactNode
  disabled?: boolean
  badge?: ReactNode
  swatch?: string
}

/** Switch row for map layers: label, one-line description, optional state badge. */
export function Toggle({ checked, onChange, label, description, disabled, badge, swatch }: ToggleProps) {
  return (
    <label className={`group flex items-start gap-2.5 rounded-[var(--radius-sm)] px-2 py-1.5 transition-colors ${disabled ? 'cursor-not-allowed opacity-55' : 'cursor-pointer hover:bg-surface-3/70'}`}>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={`relative mt-0.5 inline-flex h-[18px] w-8 flex-none items-center rounded-full border transition-colors duration-150 disabled:cursor-not-allowed ${checked ? 'border-accent bg-accent' : 'border-line-strong bg-surface-3'}`}
      >
        <span className={`absolute left-[2px] size-3 rounded-full shadow-sm transition-transform duration-150 ${checked ? 'translate-x-[14px] bg-[var(--accent-fg)]' : 'bg-fg-subtle'}`} />
      </button>
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-1.5">
          {swatch && <span className="size-2.5 flex-none rounded-[3px]" style={{ background: swatch }} aria-hidden />}
          <span className="truncate text-[12.5px] font-medium text-fg">{label}</span>
          {badge && <span className="ml-auto flex-none">{badge}</span>}
        </span>
        {description && <span className="mt-px block truncate text-[11px] text-fg-subtle" title={typeof description === 'string' ? description : undefined}>{description}</span>}
      </span>
    </label>
  )
}

/** Segmented control (radio group) for small exclusive choices. */
export function Segmented<T extends string>({ value, onChange, options, label, size = 'sm' }: { value: T; onChange: (value: T) => void; options: Array<{ value: T; label: ReactNode; tone?: 'mock' }>; label: string; size?: 'xs' | 'sm' }) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex w-full rounded-[var(--radius-sm)] border border-line bg-surface-3 p-0.5">
      {options.map(option => {
        const active = option.value === value
        const activeClass = option.tone === 'mock' ? 'bg-mock text-white shadow-sm' : 'bg-surface text-fg shadow-sm'
        return (
          <button key={option.value} type="button" role="radio" aria-checked={active} onClick={() => onChange(option.value)}
            className={`flex-1 rounded-[6px] font-semibold transition-colors duration-150 ${size === 'xs' ? 'px-2 py-0.5 text-[11px]' : 'px-2.5 py-1 text-[12px]'} ${active ? activeClass : 'text-fg-muted hover:text-fg'}`}>
            {option.label}
          </button>
        )
      })}
    </div>
  )
}
