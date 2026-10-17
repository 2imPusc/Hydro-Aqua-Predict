import { linear } from './scale'
import { useElementWidth } from './useElementWidth'

type Props = {
  value: number | null
  current?: number | null
  pi80: [number, number] | null
  pi90: [number, number] | null
  domain: [number, number]
  format: (v: number) => string
  color?: string
  ariaLabel: string
}

/**
 * Forecast value with nested PI80 / PI90 bands on a shared axis, plus the
 * current reading as a tick, so cards for different feature sets compare at a glance.
 */
export function IntervalBar({ value, current, pi80, pi90, domain, format, color = 'var(--series-1)', ariaLabel }: Props) {
  const [ref, width] = useElementWidth<HTMLDivElement>(220)
  const x = linear(domain, [4, width - 4])
  return (
    <div ref={ref} className="w-full">
      <svg width={width} height={34} role="img" aria-label={ariaLabel} className="block">
        <line x1={4} x2={width - 4} y1={14} y2={14} stroke="var(--chart-grid)" strokeWidth={6} strokeLinecap="round" />
        {pi90 && <rect x={x(pi90[0])} width={Math.max(2, x(pi90[1]) - x(pi90[0]))} y={8} height={12} rx={4} fill={color} opacity={0.22} />}
        {pi80 && <rect x={x(pi80[0])} width={Math.max(2, x(pi80[1]) - x(pi80[0]))} y={8} height={12} rx={4} fill={color} opacity={0.42} />}
        {current != null && <line x1={x(current)} x2={x(current)} y1={4} y2={24} stroke="var(--fg-muted)" strokeWidth={1.5} strokeDasharray="2 2" />}
        {value != null && <circle cx={x(value)} cy={14} r={5} fill={color} stroke="var(--surface)" strokeWidth={2} />}
        <text x={4} y={32} fontSize={9.5} fill="var(--fg-subtle)" className="tabular">{format(domain[0])}</text>
        <text x={width - 4} y={32} fontSize={9.5} fill="var(--fg-subtle)" textAnchor="end" className="tabular">{format(domain[1])}</text>
      </svg>
    </div>
  )
}

/** Point estimate with a confidence interval on a fixed [lo, hi] axis (e.g. AUC 0.5–1). */
export function CiBar({ value, ci, domain = [0.5, 1], reference, ariaLabel }: { value: number; ci: [number, number] | null; domain?: [number, number]; reference?: { value: number; label: string }; ariaLabel: string }) {
  const [ref, width] = useElementWidth<HTMLDivElement>(240)
  const x = linear(domain, [6, width - 6])
  const ticks = [domain[0], (domain[0] + domain[1]) / 2, domain[1]]
  return (
    <div ref={ref} className="w-full">
      <svg width={width} height={44} role="img" aria-label={ariaLabel} className="block">
        <line x1={6} x2={width - 6} y1={16} y2={16} stroke="var(--chart-axis)" />
        {reference && (
          <g>
            <line x1={x(reference.value)} x2={x(reference.value)} y1={6} y2={26} stroke="var(--fg-subtle)" strokeDasharray="3 2" />
            <text x={x(reference.value) + 4} y={9} fontSize={9.5} fill="var(--fg-subtle)">{reference.label}</text>
          </g>
        )}
        {ci && <line x1={x(ci[0])} x2={x(ci[1])} y1={16} y2={16} stroke="var(--series-1)" strokeWidth={4} strokeLinecap="round" opacity={0.45} />}
        <circle cx={x(value)} cy={16} r={6} fill="var(--series-1)" stroke="var(--surface)" strokeWidth={2} />
        {ticks.map(tick => <text key={tick} x={x(tick)} y={40} fontSize={10} fill="var(--fg-subtle)" textAnchor="middle" className="tabular">{tick.toFixed(2)}</text>)}
      </svg>
    </div>
  )
}
