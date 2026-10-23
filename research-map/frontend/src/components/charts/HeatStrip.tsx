import { useState } from 'react'

export type HeatCell = { key: string; state: 'on' | 'off' | 'outside'; label: string }
export type HeatRow = { key: string; label: string; cells: HeatCell[] }

const FILL: Record<HeatCell['state'], string> = { on: 'var(--cell-on)', off: 'var(--cell-off)', outside: 'var(--cell-outside)' }

/**
 * Day × hour presence grid (e.g. weather snapshot captures). Cells are 2 px
 * apart; hovering or focusing a cell names it. "outside" cells are outside
 * the reporting window and drawn as hatched outlines, not as gaps.
 */
export function HeatStrip({ rows, columns, ariaLabel }: { rows: HeatRow[]; columns: string[]; ariaLabel: string }) {
  const [active, setActive] = useState<HeatCell | null>(null)
  return (
    <div>
      <div role="grid" aria-label={ariaLabel} className="grid gap-[2px]" style={{ gridTemplateColumns: `72px repeat(${columns.length}, minmax(0, 1fr))` }}>
        <div role="row" className="contents">
          <span role="columnheader" />
          {columns.map((column, index) => (
            <span key={column} role="columnheader" className="text-center text-[10px] text-fg-subtle tabular">{index % 3 === 0 ? column : ''}</span>
          ))}
        </div>
        {rows.map(row => (
          <div key={row.key} role="row" className="contents">
            <span role="rowheader" className="truncate pr-2 text-right text-[11px] leading-[18px] text-fg-muted tabular">{row.label}</span>
            {row.cells.map(cell => (
              <span key={cell.key} role="gridcell" tabIndex={cell.state === 'outside' ? -1 : 0} aria-label={cell.label}
                onMouseEnter={() => setActive(cell)} onMouseLeave={() => setActive(null)} onFocus={() => setActive(cell)} onBlur={() => setActive(null)}
                className={`h-[18px] rounded-[3px] outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus)] ${cell.state === 'outside' ? 'hatch border border-dashed border-line' : ''} ${active?.key === cell.key ? 'ring-2 ring-[var(--fg-muted)]' : ''}`}
                style={{ background: cell.state === 'outside' ? undefined : FILL[cell.state] }} />
            ))}
          </div>
        ))}
      </div>
      <div className="mt-2 min-h-[18px] text-[11.5px] text-fg-muted" aria-live="polite">{active ? active.label : 'Rê chuột / Tab vào một ô để xem giờ.'}</div>
    </div>
  )
}
