import { CloudLightning, ThermometerSun } from 'lucide-react'
import { Disclosure, Panel, StateChip, StatusWord } from '../../components/ui'
import { num } from '../../lib/format'

/**
 * Shape the storm / heat hindcast summary is expected to take once
 * `scripts/export_research_map_artifacts.py` emits it (proposed key:
 * `hazards.json` in `artifacts/research-map/<stamp>/`, served under
 * `/api/v1/research/hazards`). Fields mirror the experiment outputs
 * `storm-hindcast-*` (manifest, climatology_month, yagi_check) and
 * `heat-hindcast-*` (manifest thresholds, trend, bias). Nothing is read
 * from experiment folders by the frontend.
 */
export type HazardSummary = {
  export_version: string | null
  storm?: {
    source_run: string
    seasons: [number, number]
    passages: number
    /** Storms per year reaching Beaufort ≥ 8 at the site, by month (1–12). */
    per_month_cap8: Array<{ month: number; per_year: number }>
    yagi?: { peak_time: string; min_dist_km: number; site_beaufort: number; era5_max_wind_ms: number | null; note?: string }
  }
  heat?: {
    source_run: string
    thresholds_c: { watch: number; stress: number; severe: number; min_run_days: number }
    oisst_offset_c: number | null
    /** Trend of days per decade at alert ≥ 1, with 95 % CI. */
    trend_days_per_decade: { value: number; ci95: [number, number]; years: [number, number] } | null
    /** ISO weeks where stress days occurred in any year (share of years). */
    peak_weeks?: Array<{ iso_week: number; share_years: number }>
  }
}

/**
 * Storm & heat hindcast (H2 · weather-aware advisory track). Until the export
 * carries `hazards.json` this renders an explicit "not exported" state: no
 * figure is typed in or read from experiment folders.
 */
export function HazardCard({ data }: { data: HazardSummary | null }) {
  if (!data || (!data.storm && !data.heat)) {
    return (
      <Panel title="Bão & nắng nóng" icon={<CloudLightning size={15} />} actions={<StateChip size="xs" state="unavailable" label="Chưa có trong export" />}
        summary="Hindcast đã chạy nhưng chưa được export cho bản đồ">
        <Disclosure summary="Khi có export sẽ hiện gì?">
          <p className="m-0">Bão: số cơn bão đạt cấp 8+ tại NB1 theo tháng (IBTrACS 1980–2026) và kiểm tra Yagi 2024.</p>
          <p className="m-0">Nắng nóng: ngưỡng nhiệt cá giò (theo dõi / căng thẳng / nghiêm trọng), xu hướng số ngày nóng mỗi thập kỷ và các tuần hay gặp.</p>
          <p className="m-0">Chỉ quan sát lịch sử, không kích hoạt cảnh báo.</p>
        </Disclosure>
      </Panel>
    )
  }
  const { storm, heat } = data
  const peakMonth = storm?.per_month_cap8.reduce((best, row) => (row.per_year > best.per_year ? row : best), storm.per_month_cap8[0])
  return (
    <Panel title="Bão & nắng nóng" icon={<CloudLightning size={15} />} actions={<StateChip size="xs" state="research_only" />}>
      <div className="grid gap-2 sm:grid-cols-2">
        {storm && (
          <div className="rounded-[var(--radius-sm)] bg-surface-2 px-3 py-2">
            <div className="text-[12px] text-fg-muted">Bão đi qua gần NB1 (≤ 500 km)</div>
            <div className="text-[18px] font-semibold text-fg">{storm.passages} lượt <span className="text-[12px] font-normal text-fg-muted">{storm.seasons[0]}–{storm.seasons[1]}</span></div>
            {peakMonth && <div className="text-[11.5px] text-fg-subtle">gió cấp 8+ tại trạm nhiều nhất tháng {peakMonth.month}: {num(peakMonth.per_year, 2)} cơn/năm</div>}
          </div>
        )}
        {heat && (
          <div className="rounded-[var(--radius-sm)] bg-surface-2 px-3 py-2">
            <div className="flex items-center gap-1 text-[12px] text-fg-muted"><ThermometerSun size={13} aria-hidden />Nắng nóng (ngưỡng {heat.thresholds_c.watch}/{heat.thresholds_c.stress}/{heat.thresholds_c.severe} °C)</div>
            {heat.trend_days_per_decade
              ? <div className="text-[18px] font-semibold text-fg">+{num(heat.trend_days_per_decade.value, 1)} <span className="text-[12px] font-normal text-fg-muted">ngày / thập kỷ</span></div>
              : <StatusWord size="xs" status={{ tone: 'neutral', label: 'Không có xu hướng' }} />}
            {heat.trend_days_per_decade && <div className="text-[11.5px] text-fg-subtle">CI 95 % {num(heat.trend_days_per_decade.ci95[0], 1)}–{num(heat.trend_days_per_decade.ci95[1], 1)}</div>}
          </div>
        )}
      </div>
      <Disclosure summary="Chi tiết">
        {storm?.yagi && <p className="m-0">Yagi ({storm.yagi.peak_time.slice(0, 10)}): cách {num(storm.yagi.min_dist_km, 0)} km, gió tại trạm cấp {storm.yagi.site_beaufort} (cận dưới). {storm.yagi.note}</p>}
        {heat?.oisst_offset_c != null && <p className="m-0">SST vệ tinh lệch so với cảm biến {num(heat.oisst_offset_c, 2)} °C (đã hiệu chỉnh).</p>}
        <p className="m-0">Run: {[storm?.source_run, heat?.source_run].filter(Boolean).join(', ')} · export {data.export_version ?? '—'}. Chỉ quan sát, không kích hoạt cảnh báo.</p>
      </Disclosure>
    </Panel>
  )
}
