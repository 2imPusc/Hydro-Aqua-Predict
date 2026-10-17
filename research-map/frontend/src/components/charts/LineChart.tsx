import { useId, useMemo, useState, type ReactNode } from 'react'
import { linear, niceDomain, niceTicks } from './scale'
import { useElementWidth } from './useElementWidth'

export type ChartPoint = { x: number; y: number | null; /** hollow marker = condition not met (e.g. gate fail) */ hollow?: boolean }
export type ChartSeries = { id: string; label: string; color: string; dashed?: boolean; points: ChartPoint[] }
export type ChartBand = { from: number; to: number; label: string }

type Props = {
  /** Categorical x positions (equally spaced), e.g. horizons in minutes. */
  xs: number[]
  xFormat: (x: number) => string
  series: ChartSeries[]
  yFormat: (y: number) => string
  yTitle?: string
  /** Values the y domain must include (e.g. 0). */
  include?: number[]
  yDomain?: [number, number]
  bands?: ChartBand[]
  refLines?: Array<{ y: number; label?: string }>
  height?: number
  ariaLabel: string
  /** Extra tooltip content for a hovered x. */
  tooltipExtra?: (x: number) => ReactNode
  hollowLabel?: string
}

const MARGIN = { top: 10, right: 14, bottom: 26, left: 46 }

/**
 * Small multi-series line chart over a categorical x axis. Thin 2 px lines,
 * 8 px markers with a surface ring, recessive grid, crosshair + tooltip on
 * hover/focus. Identity is carried by the legend (always shown for ≥ 2
 * series) and the tooltip, never by colour alone.
 */
export function LineChart({ xs, xFormat, series, yFormat, yTitle, include = [], yDomain, bands = [], refLines = [], height = 200, ariaLabel, tooltipExtra, hollowLabel }: Props) {
  const [ref, width] = useElementWidth<HTMLDivElement>()
  const [hover, setHover] = useState<number | null>(null)
  const titleId = useId()

  const values = series.flatMap(s => s.points.map(p => p.y)).filter((v): v is number => v != null && Number.isFinite(v))
  const domain = yDomain ?? niceDomain(values, [...include, ...bands.flatMap(b => [b.from, b.to]), ...refLines.map(r => r.y)])
  const innerW = Math.max(40, width - MARGIN.left - MARGIN.right)
  const innerH = height - MARGIN.top - MARGIN.bottom
  const xPos = (index: number) => MARGIN.left + (xs.length <= 1 ? innerW / 2 : (index / (xs.length - 1)) * innerW)
  const y = linear(domain, [MARGIN.top + innerH, MARGIN.top])
  const ticks = niceTicks(domain[0], domain[1], 4)
  const indexOf = useMemo(() => new Map(xs.map((x, i) => [x, i])), [xs])

  const onMove = (event: React.MouseEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect()
    const px = event.clientX - rect.left
    let best = 0
    xs.forEach((_, i) => { if (Math.abs(xPos(i) - px) < Math.abs(xPos(best) - px)) best = i })
    setHover(best)
  }
  const onKey = (event: React.KeyboardEvent) => {
    if (event.key === 'ArrowRight') { event.preventDefault(); setHover(h => Math.min(xs.length - 1, (h ?? -1) + 1)) }
    if (event.key === 'ArrowLeft') { event.preventDefault(); setHover(h => Math.max(0, (h ?? xs.length) - 1)) }
    if (event.key === 'Escape') setHover(null)
  }

  const hoverX = hover != null ? xs[hover] : null
  const tooltipLeft = hover != null ? Math.min(Math.max(xPos(hover) + 10, 0), width - 200) : 0

  return (
    <div ref={ref} className="relative w-full">
      <svg width={width} height={height} role="img" aria-labelledby={titleId} tabIndex={0}
        onMouseMove={onMove} onMouseLeave={() => setHover(null)} onKeyDown={onKey} onBlur={() => setHover(null)} className="block overflow-visible outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus)] rounded">
        <title id={titleId}>{ariaLabel}</title>
        {bands.map(band => (
          <g key={band.label}>
            <rect x={MARGIN.left} width={innerW} y={y(band.to)} height={Math.max(0, y(band.from) - y(band.to))} fill="var(--chart-band)" />
            <line x1={MARGIN.left} x2={MARGIN.left + innerW} y1={y(band.to)} y2={y(band.to)} stroke="var(--chart-band-line)" strokeDasharray="3 3" />
            <line x1={MARGIN.left} x2={MARGIN.left + innerW} y1={y(band.from)} y2={y(band.from)} stroke="var(--chart-band-line)" strokeDasharray="3 3" />
            <text x={MARGIN.left + innerW - 4} y={y(band.to) - 3} textAnchor="end" fontSize={10} fill="var(--fg-subtle)">{band.label}</text>
          </g>
        ))}
        {ticks.map(tick => (
          <g key={tick}>
            <line x1={MARGIN.left} x2={MARGIN.left + innerW} y1={y(tick)} y2={y(tick)} stroke={tick === 0 ? 'var(--chart-axis)' : 'var(--chart-grid)'} strokeWidth={tick === 0 ? 1.25 : 1} />
            <text x={MARGIN.left - 6} y={y(tick)} dy="0.32em" textAnchor="end" fontSize={10.5} fill="var(--fg-subtle)" className="tabular">{yFormat(tick)}</text>
          </g>
        ))}
        {refLines.map(line => (
          <g key={line.y}>
            <line x1={MARGIN.left} x2={MARGIN.left + innerW} y1={y(line.y)} y2={y(line.y)} stroke="var(--fg-subtle)" strokeDasharray="4 3" />
            {line.label && <text x={MARGIN.left + 4} y={y(line.y) - 4} fontSize={10} fill="var(--fg-subtle)">{line.label}</text>}
          </g>
        ))}
        {yTitle && <text x={10} y={MARGIN.top + innerH / 2} transform={`rotate(-90 10 ${MARGIN.top + innerH / 2})`} textAnchor="middle" fontSize={10.5} fill="var(--fg-subtle)">{yTitle}</text>}
        {xs.map((x, i) => (
          <text key={x} x={xPos(i)} y={height - 8} textAnchor="middle" fontSize={10.5} fill={hover === i ? 'var(--fg)' : 'var(--fg-subtle)'} className="tabular">{xFormat(x)}</text>
        ))}
        {hover != null && <line x1={xPos(hover)} x2={xPos(hover)} y1={MARGIN.top} y2={MARGIN.top + innerH} stroke="var(--line-strong)" />}
        {series.map(s => {
          const pts = s.points.filter(p => p.y != null && indexOf.has(p.x)).sort((a, b) => indexOf.get(a.x)! - indexOf.get(b.x)!)
          const path = pts.map((p, i) => `${i ? 'L' : 'M'}${xPos(indexOf.get(p.x)!).toFixed(1)},${y(p.y!).toFixed(1)}`).join('')
          return (
            <g key={s.id}>
              <path d={path} fill="none" stroke={s.color} strokeWidth={2} strokeDasharray={s.dashed ? '5 4' : undefined} strokeLinejoin="round" strokeLinecap="round" />
              {pts.map(p => (
                <circle key={p.x} cx={xPos(indexOf.get(p.x)!)} cy={y(p.y!)} r={hover != null && xs[hover] === p.x ? 5 : 4}
                  fill={p.hollow ? 'var(--surface)' : s.color} stroke={p.hollow ? s.color : 'var(--surface)'} strokeWidth={p.hollow ? 2 : 1.5} />
              ))}
            </g>
          )
        })}
      </svg>
      {hoverX != null && (
        <div className="chart-tooltip" style={{ left: tooltipLeft, top: 4 }}>
          <div className="mb-1 font-semibold">{xFormat(hoverX)}</div>
          {series.map(s => {
            const point = s.points.find(p => p.x === hoverX)
            return (
              <div key={s.id} className="flex items-center gap-1.5">
                <span className="size-2 flex-none rounded-full" style={{ background: s.color }} aria-hidden />
                <span className="min-w-0 flex-1 truncate text-fg-muted">{s.label}</span>
                <span className="tabular font-semibold">{point?.y != null ? yFormat(point.y) : '—'}</span>
                {point?.hollow && hollowLabel && <span className="text-[10px] text-fg-subtle">{hollowLabel}</span>}
              </div>
            )
          })}
          {tooltipExtra?.(hoverX)}
        </div>
      )}
    </div>
  )
}

/** HTML legend row for line charts: line swatch + label; explains filled vs hollow markers. */
export function ChartLegend({ series, markerNote }: { series: Array<Pick<ChartSeries, 'id' | 'label' | 'color' | 'dashed'>>; markerNote?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11.5px] text-fg-muted">
      {series.map(s => (
        <span key={s.id} className="inline-flex items-center gap-1.5">
          <svg width="18" height="8" aria-hidden><line x1="1" x2="17" y1="4" y2="4" stroke={s.color} strokeWidth="2" strokeDasharray={s.dashed ? '4 3' : undefined} /><circle cx="9" cy="4" r="3" fill={s.color} /></svg>
          {s.label}
        </span>
      ))}
      {markerNote && <span className="inline-flex items-center gap-1.5 text-fg-subtle">{markerNote}</span>}
    </div>
  )
}

export function HollowMarkerNote({ filled, hollow }: { filled: string; hollow: string }) {
  return (
    <>
      <svg width="10" height="10" aria-hidden><circle cx="5" cy="5" r="3.5" fill="var(--fg-muted)" /></svg>{filled}
      <svg width="10" height="10" aria-hidden className="ml-1"><circle cx="5" cy="5" r="3.5" fill="none" stroke="var(--fg-muted)" strokeWidth="1.5" /></svg>{hollow}
    </>
  )
}
