import type { ReactNode } from 'react'

type StatProps = {
  label: ReactNode
  value: ReactNode
  unit?: ReactNode
  hint?: ReactNode
  status?: ReactNode
  muted?: boolean
}

/** Metric tile: label on top, large tabular value, optional unit, hint and status chip. */
export function Stat({ label, value, unit, hint, status, muted }: StatProps) {
  return (
    <div className="min-w-0 rounded-[var(--radius-sm)] border border-line bg-surface-2 px-2.5 py-2">
      <div className="flex items-center justify-between gap-1">
        <span className="truncate text-[10.5px] font-semibold uppercase tracking-[.06em] text-fg-subtle">{label}</span>
        {status}
      </div>
      <div className={`mt-0.5 flex items-baseline gap-1 tabular ${muted ? 'text-fg-subtle' : 'text-fg'}`}>
        <span className="text-[18px] font-semibold leading-tight tracking-tight">{value}</span>
        {unit && <span className="truncate text-[11px] text-fg-subtle">{unit}</span>}
      </div>
      {hint && <div className="mt-0.5 truncate text-[10.5px] text-fg-subtle">{hint}</div>}
    </div>
  )
}
