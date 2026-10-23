import { useMemo } from 'react'
import { BellRing, Rewind } from 'lucide-react'
import { getStationHazards } from '../../api/hazards'
import { describeApiError } from '../../api/client'
import { EmptyState, Skeleton } from '../../components/ui'
import { usePolling } from '../../hooks/usePolling'
import type { StationAlerts, StationHazardsResponse } from '../../types/alerts'
import { PageScroll } from '../shared/research'
import { DEFAULT_TIERS, bucketOf, localTime, shortName, sortStations, tierClass, tierLabel, type TierMeta } from './model'
import { HATCH, ShadowChip, StationCard, TierIcon } from './parts'

const REASON: Record<string, string> = {
  no_hazard_ledger: 'Chưa có sổ cảnh báo shadow: bộ chạy hazard chưa ghi lần nào (runtime/hazard-shadow).',
  empty_hazard_ledger: 'Sổ cảnh báo shadow trống hoặc không đọc được.',
}
const cardId = (station: StationAlerts) => `alert-station-${station.id}`

function focusCard(id: string) {
  const el = document.getElementById(id)
  if (!el) return
  el.scrollIntoView({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'center' })
  el.focus({ preventScroll: true })
}

/** One tile per station in severity order: the whole network at a glance; each tile jumps to its card. */
function StationTiles({ stations, tiers }: { stations: StationAlerts[]; tiers: TierMeta[] }) {
  return (
    <ul className="m-0 flex list-none flex-wrap gap-1 p-0" aria-label="Trạm theo bậc, cao nhất trước">
      {stations.map(station => {
        const bucket = bucketOf(station)
        const tier = bucket.kind === 'tier' ? bucket.tier : null
        const state = tier != null ? `bậc ${tier} ${tierLabel(tiers, tier)}` : bucket.kind === 'stale' ? 'dữ liệu cũ' : 'không có dữ liệu'
        return (
          <li key={station.id}>
            <button type="button" onClick={() => focusCard(cardId(station))}
              title={`${shortName(station.name)} · ${state}`} aria-label={`${shortName(station.name)} (${station.id}): ${state}`}
              className={`grid h-9 min-w-9 place-items-center rounded-[var(--radius-xs)] border px-1 text-[10.5px] font-semibold leading-none tabular hover:brightness-95 ${tier != null ? tierClass(tiers, tier) : 'border-dashed border-[var(--neutral-line)] text-neutral'}`}
              style={tier == null ? HATCH : undefined}>
              <span className="flex flex-col items-center gap-0.5">
                {tier != null ? <TierIcon tier={tier} size={12} /> : <span aria-hidden>–</span>}
                <span>{station.id}</span>
              </span>
            </button>
          </li>
        )
      })}
    </ul>
  )
}

/** Answer-first summary: how many stations need preparing today, then the count per tier / data state. */
function Summary({ data, stations, tiers }: { data: StationHazardsResponse; stations: StationAlerts[]; tiers: TierMeta[] }) {
  const counts = new Map<string, number>()
  for (const s of stations) {
    const b = bucketOf(s)
    const key = b.kind === 'tier' ? `t${b.tier}` : b.kind
    counts.set(key, (counts.get(key) ?? 0) + 1)
  }
  const assessed = stations.filter(s => bucketOf(s).kind === 'tier')
  const attention = assessed.filter(s => (s.max_tier ?? 0) >= 2).length
  const watching = assessed.filter(s => s.max_tier === 1).length
  const top = Math.max(-1, ...assessed.map(s => s.max_tier ?? -1))
  const answer = !assessed.length ? 'Không trạm nào có dữ liệu mới để xếp bậc.'
    : attention ? `${attention} trạm ở bậc Chuẩn bị trở lên; cao nhất: bậc ${top} ${tierLabel(tiers, top)}.`
      : watching ? `Không trạm nào cần chuẩn bị; ${watching} trạm cần theo dõi.`
        : 'Mọi trạm được đánh giá đều bình thường.'
  const legend = [
    ...[...tiers].reverse().map(t => ({ key: `t${t.tier}`, tier: t.tier as number | null, label: `Bậc ${t.tier} · ${t.label_vi}` })),
    { key: 'stale', tier: null, label: 'Dữ liệu cũ' },
    { key: 'unavailable', tier: null, label: 'Không có dữ liệu' },
  ].filter(item => counts.get(item.key))
  const heroTone = !assessed.length ? 'text-neutral' : attention ? (top >= 3 ? 'text-danger' : 'text-warn') : watching ? 'text-info' : 'text-ok'
  return (
    <section aria-labelledby="alerts-q" className="rounded-[var(--radius-lg)] border border-line bg-surface px-5 py-4 shadow-[var(--shadow-sm)]">
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div className="min-w-[240px] flex-[1_1_340px]">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 id="alerts-q" className="m-0 text-[13px] font-medium text-fg-muted">Hôm nay có trạm nào cần chú ý?</h2>
            <ShadowChip />
          </div>
          <div className="mt-1.5 flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
            <span className={`hero-figure ${heroTone}`}>{assessed.length ? attention : '—'}</span>
            <span className="text-[14px] font-medium text-fg-muted">/ {stations.length} trạm cần chuẩn bị</span>
          </div>
          <p className="m-0 mt-1.5 max-w-[62ch] text-[13px] leading-snug text-fg">{answer}</p>
          <p className="m-0 mt-1 text-[11.5px] text-fg-subtle">
            Lần chạy {localTime(data.issued_at)} · bộ ngưỡng <code>{data.config_version ?? '—'}</code> · quá {data.stale_after_hours ?? 3} giờ coi là cũ
          </p>
        </div>
        <div className="flex min-w-0 flex-[1_1_380px] flex-col gap-2">
          <StationTiles stations={stations} tiers={tiers} />
          <ul className="m-0 flex list-none flex-wrap gap-x-3 gap-y-1 p-0 text-[12px] text-fg-muted" aria-label="Số trạm theo bậc">
            {legend.map(item => (
              <li key={item.key} className="inline-flex items-center gap-1.5">
                <span className={`inline-grid size-3.5 place-items-center rounded-[3px] border ${item.tier != null ? tierClass(tiers, item.tier) : 'border-dashed border-[var(--neutral-line)]'}`} style={item.tier == null ? HATCH : undefined} aria-hidden />
                <span>{item.label}</span><span className="font-semibold text-fg tabular">{counts.get(item.key)}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  )
}

export default function AlertsView() {
  const poll = usePolling(getStationHazards, { intervalMs: 5 * 60_000, maxErrorRetries: 3, retryBaseMs: 3_000, clearOnError: true })
  const data = poll.data
  const tiers = data?.tiers?.length ? data.tiers : DEFAULT_TIERS
  const stations = useMemo(() => sortStations(data?.stations ?? []), [data])

  let body
  if (!data) {
    body = poll.error
      ? <EmptyState tone="danger" icon={<BellRing size={22} />} title="Không tải được cảnh báo theo trạm" description={describeApiError(poll.error)}>
          <button type="button" onClick={poll.refresh} className="rounded-md border border-line px-3 py-1 text-[12.5px] font-semibold hover:bg-surface-2">Thử lại</button>
        </EmptyState>
      : <><Skeleton className="h-36" /><Skeleton className="h-64" /></>
  } else if (data.status !== 'ready') {
    body = <EmptyState icon={<BellRing size={22} />} title="Chưa có cảnh báo theo trạm" description={REASON[data.reason ?? ''] ?? data.reason ?? 'Không khả dụng'} />
  } else {
    body = (
      <>
        {data.replay && (
          <div role="note" className="mock-stripes flex items-start gap-2 rounded-[var(--radius-md)] border border-[var(--mock-line)] bg-mock-bg px-3.5 py-2.5 text-[13px] text-fg">
            <Rewind size={16} className="mt-0.5 flex-none text-mock" aria-hidden />
            <span><span className="font-semibold text-mock">Dữ liệu phát lại, không phải hiện tại.</span> {stations.every(s => s.replay || !s.issued_at) ? 'Các trạm' : 'Một số trạm (có nhãn "Phát lại")'} dùng gió/nhiệt độ quá khứ (tái phân tích) chạy lại như bản tin; bậc chỉ minh hoạ logic cảnh báo.</span>
          </div>
        )}
        <Summary data={data} stations={stations} tiers={tiers} />
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 2xl:grid-cols-3">
          {stations.map(station => <StationCard key={station.id} id={cardId(station)} station={station} tiers={tiers} />)}
        </div>
      </>
    )
  }

  return (
    <PageScroll>
      <h1 className="sr-only">Cảnh báo theo trạm</h1>
      {body}
    </PageScroll>
  )
}
