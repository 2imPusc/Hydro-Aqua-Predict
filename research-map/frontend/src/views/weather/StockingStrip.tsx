import type { ReactNode } from 'react'
import { Ban, CalendarRange, CircleAlert, CircleCheck, Snowflake } from 'lucide-react'
import { Disclosure } from '../../components/ui'
import { num, pct } from '../../lib/format'
import type { HazardStocking, StockingClass } from '../../types/research'
import { TheoryChip } from './TheoryChip'

/**
 * Ordinal status per month: each class has its own tone *and* glyph, so the
 * strip reads without colour. `avoid_cold` (cold at stocking, hard gate) uses
 * the cool info tone + snowflake, distinct from `avoid` (low composite score).
 */
const CLASS_META: Record<StockingClass, { label: string; short: string; bg: string; line: string; fg: string; icon: (size: number) => ReactNode }> = {
  good: { label: 'Tốt', short: 'Tốt', bg: 'var(--ok-bg)', line: 'var(--ok-line)', fg: 'text-ok', icon: size => <CircleCheck size={size} strokeWidth={2.2} aria-hidden /> },
  caution: { label: 'Cân nhắc', short: 'Cân nhắc', bg: 'var(--warn-bg)', line: 'var(--warn-line)', fg: 'text-warn', icon: size => <CircleAlert size={size} strokeWidth={2.2} aria-hidden /> },
  avoid: { label: 'Tránh', short: 'Tránh', bg: 'var(--danger-bg)', line: 'var(--danger-line)', fg: 'text-danger', icon: size => <Ban size={size} strokeWidth={2.2} aria-hidden /> },
  avoid_cold: { label: 'Tránh · lạnh lúc thả', short: 'Lạnh', bg: 'var(--info-bg)', line: 'var(--info-line)', fg: 'text-info', icon: size => <Snowflake size={size} strokeWidth={2.2} aria-hidden /> },
}
const ORDER: StockingClass[] = ['good', 'caution', 'avoid', 'avoid_cold']

/** 12-month stocking calendar (one row per grow-out length) with a legend; details closed. */
export function StockingStrip({ stocking }: { stocking: HazardStocking }) {
  const base = stocking.calendars[0]
  const goodMonths = base?.months.filter(row => row.class === 'good').map(row => row.month) ?? []
  const coldMonths = base?.months.filter(row => row.class === 'avoid_cold').map(row => `T${row.month}`) ?? []
  return (
    <section className="mt-3 rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2.5" aria-labelledby="stocking-title">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <CalendarRange size={15} className="text-accent" aria-hidden />
        <h3 id="stocking-title" className="m-0 min-w-0 flex-1 text-[12.5px] font-medium text-fg-muted">Tháng nào nên thả giống cá giò?</h3>
        <TheoryChip />
      </div>
      {base && goodMonths.length > 0 && (
        <p className="m-0 mt-1 text-[12.5px] text-fg">
          Chu kỳ {base.growout_weeks} tuần: tốt nhất <span className="font-semibold">T{goodMonths[0]}–T{goodMonths[goodMonths.length - 1]}</span>
          {stocking.best_weeks_base[String(base.growout_weeks)] && <span className="text-fg-muted"> (tuần {stocking.best_weeks_base[String(base.growout_weeks)].join(', ')})</span>}{coldMonths.length ? `; ${coldMonths.join(', ')} lạnh lúc thả` : ''}.
        </p>
      )}
      <div className="scroll-thin mt-2 overflow-x-auto">
        <div className="grid min-w-[520px] grid-cols-[64px_repeat(12,minmax(0,1fr))] gap-[3px] text-[11px]" role="table" aria-label="Lịch thả giống theo tháng">
          <div role="row" className="contents">
            <span role="columnheader" className="sr-only">Chu kỳ nuôi</span>
            {Array.from({ length: 12 }, (_, i) => <span key={i} role="columnheader" className="text-center text-fg-subtle tabular">T{i + 1}</span>)}
          </div>
          {stocking.calendars.map(calendar => (
            <div key={calendar.growout_weeks} role="row" className="contents">
              <span role="rowheader" className="self-center whitespace-nowrap text-fg-muted">{calendar.growout_weeks} tuần</span>
              {calendar.months.map(month => {
                const meta = month.class ? CLASS_META[month.class] : null
                const label = `T${month.month}, chu kỳ ${calendar.growout_weeks} tuần: ${meta?.label ?? 'không có'}${month.score != null ? ` · điểm ${num(month.score, 2)}` : ''}${month.feasible_frac != null && month.feasible_frac < 1 ? ` · ${pct(month.feasible_frac)} tuần khả thi` : ''}`
                return (
                  <span key={month.month} role="cell" title={label} aria-label={label}
                    className={`grid h-8 place-items-center rounded-[4px] border ${meta?.fg ?? 'text-fg-subtle'}`}
                    style={{ background: meta?.bg ?? 'transparent', borderColor: meta?.line ?? 'var(--line)' }}>
                    {meta ? meta.icon(14) : '—'}
                  </span>
                )
              })}
            </div>
          ))}
        </div>
      </div>
      <ul className="m-0 mt-2 flex list-none flex-wrap gap-x-4 gap-y-1 p-0 text-[11.5px] text-fg-muted" aria-label="Chú giải lịch thả giống">
        {ORDER.map(key => (
          <li key={key} className="inline-flex items-center gap-1.5">
            <span className={`grid size-4 place-items-center rounded-[3px] border ${CLASS_META[key].fg}`} style={{ background: CLASS_META[key].bg, borderColor: CLASS_META[key].line }}>{CLASS_META[key].icon(11)}</span>
            {CLASS_META[key].label}
          </li>
        ))}
      </ul>
      <Disclosure summary="Cách tính" className="mt-1.5">
        <p className="m-0">Điểm tổng hợp (nóng, rét, bão, 8 tuần đầu, tăng trưởng) từ OISST {stocking.years?.[0]}–{stocking.years?.[1]} và quỹ đạo bão; lớp tháng theo ngưỡng điểm {stocking.class_cuts?.map(cut => num(cut, 2)).join(' / ')}.</p>
        <p className="m-0">Điều kiện cứng: {stocking.gate.early_weeks} tuần đầu SST ≥ {stocking.gate.early_mean_sst_min_c} °C ở ≥ {pct(stocking.gate.min_share_of_years)} số năm, nếu không là “lạnh lúc thả”.</p>
        <p className="m-0">Tuần tốt nhất đổi theo bộ trọng số và kịch bản mùa đông lạnh hơn (xem RL-35). {stocking.validated_against_ground_truth === false ? 'Chưa đối chiếu với vụ nuôi thật.' : ''} Run {stocking.source_run}.</p>
      </Disclosure>
    </section>
  )
}
