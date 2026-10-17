import type { ReactNode } from 'react'

/** Continuous colour ramp with tick labels. */
export function GradientLegend({ title, gradient, ticks, note }: { title: ReactNode; gradient: string; ticks: ReactNode[]; note?: ReactNode }) {
  return (
    <div>
      <div className="text-[11.5px] font-semibold text-fg">{title}</div>
      <div className="mt-1.5 h-2 rounded-full ring-1 ring-inset ring-black/5" style={{ background: gradient }} />
      <div className="mt-1 flex justify-between text-[10.5px] text-fg-subtle tabular">{ticks.map((tick, index) => <span key={index}>{tick}</span>)}</div>
      {note && <div className="mt-0.5 text-[10.5px] text-fg-subtle">{note}</div>}
    </div>
  )
}

/** Categorical legend: swatch + label rows. */
export function SwatchLegend({ title, items, note, columns = 1 }: { title: ReactNode; items: Array<{ color: string; label: ReactNode; shape?: 'square' | 'dot' | 'line' | 'dash' }>; note?: ReactNode; columns?: 1 | 2 }) {
  return (
    <div>
      <div className="text-[11.5px] font-semibold text-fg">{title}</div>
      <ul className={`m-0 mt-1.5 grid list-none gap-x-3 gap-y-1 p-0 ${columns === 2 ? 'grid-cols-2' : ''}`}>
        {items.map((item, index) => (
          <li key={index} className="flex items-center gap-2 text-[11px] text-fg-muted">
            <Swatch color={item.color} shape={item.shape} />
            {item.label}
          </li>
        ))}
      </ul>
      {note && <div className="mt-1 text-[10.5px] text-fg-subtle">{note}</div>}
    </div>
  )
}

function Swatch({ color, shape = 'square' }: { color: string; shape?: 'square' | 'dot' | 'line' | 'dash' }) {
  if (shape === 'line') return <span className="h-0.5 w-4 flex-none rounded" style={{ background: color }} aria-hidden />
  if (shape === 'dash') return <span className="w-4 flex-none border-t-2 border-dashed" style={{ borderColor: color }} aria-hidden />
  return <span className={`size-3 flex-none ${shape === 'dot' ? 'rounded-full' : 'rounded-[3px]'}`} style={{ background: color, opacity: shape === 'square' ? .75 : 1 }} aria-hidden />
}
