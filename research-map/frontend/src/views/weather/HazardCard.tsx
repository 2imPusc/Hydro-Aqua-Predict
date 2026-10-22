import type { ReactNode } from 'react'
import { CloudLightning, Radar, Thermometer, ThermometerSun, Virus } from 'lucide-react'
import { Disclosure, Panel, Skeleton, StateChip, StatusWord, type VerdictStatus } from '../../components/ui'
import type { PollState } from '../../hooks/usePolling'
import { num, pct } from '../../lib/format'
import type { HazardDisease, HazardHeat, HazardHeatSkill, Hazards, HazardStorm, HazardStormLead } from '../../types/research'
import { researchReason } from '../../api/research'
import { StockingStrip } from './StockingStrip'
import { TheoryChip } from './TheoryChip'

const MONTHS = ['T1', 'T2', 'T3', 'T4', 'T5', 'T6', 'T7', 'T8', 'T9', 'T10', 'T11', 'T12']

/** Single-series column strip (values on hover / in the accessible name), baseline-anchored. */
function MiniBars({ values, labels, label, format }: { values: Array<number | null>; labels: string[]; label: string; format: (value: number | null) => string }) {
  const max = Math.max(...values.map(value => value ?? 0), 1e-9)
  return (
    <figure className="m-0" aria-label={`${label}: ${values.map((value, i) => `${labels[i]} ${format(value)}`).join(', ')}`} role="img">
      <div className="flex h-12 items-end gap-[2px] border-b border-line">
        {values.map((value, i) => (
          <div key={labels[i]} title={`${labels[i]}: ${format(value)}`} className="group flex h-full min-w-0 flex-1 items-end">
            <div className="w-full rounded-t-[3px] bg-[var(--series-1)] transition-opacity group-hover:opacity-80"
              style={{ height: value ? `${Math.max(6, (value / max) * 100)}%` : '0%' }} />
          </div>
        ))}
      </div>
      <div className="mt-0.5 flex gap-[2px] text-[10px] text-fg-subtle tabular">
        {labels.map(text => <span key={text} className="min-w-0 flex-1 text-center">{text}</span>)}
      </div>
    </figure>
  )
}

/** One answer-first tile: question → hero figure → one line; the rest in "Chi tiết". */
function Tile({ icon, question, value, unit, status, line, children }: { icon: ReactNode; question: string; value: ReactNode; unit?: ReactNode; status?: VerdictStatus; line?: ReactNode; children?: ReactNode }) {
  return (
    <section className="flex min-w-0 flex-col gap-1.5 rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2.5">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="text-accent" aria-hidden>{icon}</span>
        <h3 className="m-0 min-w-0 flex-1 text-[12.5px] font-medium text-fg-muted">{question}</h3>
      </div>
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
        <span className="text-[24px] font-semibold leading-none tracking-tight text-fg tabular">{value}</span>
        {unit && <span className="text-[12px] text-fg-muted">{unit}</span>}
        {status && <StatusWord size="xs" status={status} />}
      </div>
      {line && <p className="m-0 text-[12px] leading-snug text-fg">{line}</p>}
      <div><TheoryChip /></div>
      {children}
    </section>
  )
}

function StormTile({ storm }: { storm: HazardStorm }) {
  const peak = storm.per_month_cap8.reduce((best, row) => ((row.per_year ?? 0) > (best.per_year ?? 0) ? row : best), storm.per_month_cap8[0])
  const quiet = storm.per_month_cap8.filter(row => !row.per_year).map(row => row.month)
  const values = MONTHS.map((_, i) => storm.per_month_cap8.find(row => row.month === i + 1)?.per_year ?? null)
  return (
    <Tile icon={<CloudLightning size={15} />} question="Tháng nào bão gây gió cấp 8+ tại NB1?"
      value={num(peak?.per_year, 2)} unit={`cơn / năm · tháng ${peak?.month ?? '—'}`}
      line={`${storm.passages ?? '—'} lượt bão qua trong ${num(storm.radius_km, 0)} km, ${storm.seasons?.[0] ?? '—'}–${storm.seasons?.[1] ?? '—'}${quiet.length ? `; không có cơn cấp 8+ ở ${quiet.length} tháng` : ''}.`}>
      <MiniBars values={values} labels={MONTHS.map((_, i) => String(i + 1))} label="Số cơn bão đạt cấp 8+ tại NB1 mỗi năm, theo tháng" format={value => `${num(value, 2)} cơn/năm`} />
      <Disclosure summary="Chi tiết">
        {storm.yagi && <p className="m-0">Yagi ({storm.yagi.peak_time.slice(0, 10)}): tâm cách {num(storm.yagi.min_dist_km, 0)} km, gió tại lồng ước cấp {storm.yagi.site_beaufort ?? '—'}{storm.yagi.site_wind_lower_bound ? ' (cận dưới)' : ''}; ERA5 chỉ {num(storm.yagi.era5_max_wind_ms, 1)} m/s (cấp {storm.yagi.era5_max_wind_beaufort ?? '—'}) vì tái phân tích 0,25° đọc thấp lõi bão.</p>}
        <p className="m-0">Gió tại lồng ước từ quỹ đạo IBTrACS (mô hình Rankine / bán kính gió), hệ số 10 phút 0,93. Run {storm.source_run}.</p>
      </Disclosure>
    </Tile>
  )
}

function LeadTile({ lead }: { lead: HazardStormLead }) {
  const at = (day: number) => lead.by_lead.find(row => row.lead_day === day)
  const ranked = lead.storms.filter(row => row.consistent_lead_days != null).sort((a, b) => (b.consistent_lead_days ?? 0) - (a.consistent_lead_days ?? 0))
  const top = ranked.slice(0, 2).map(row => `${titleCase(row.name)} ${row.consistent_lead_days} ngày`).join(', ')
  const events = lead.by_lead[0]?.n_event_days
  return (
    <Tile icon={<Radar size={15} />} question={`Dự báo gió cấp ${lead.level_bf}+ trước bao lâu?`}
      value={num(at(1)?.csi, 2)} unit="CSI trước 1 ngày"
      line={`Còn ${num(at(5)?.csi, 2)} trước 5 ngày, ${num(at(7)?.csi, 2)} trước 7 ngày.${top ? ` Báo liên tục lâu nhất: ${top}.` : ''}`}>
      <MiniBars values={lead.by_lead.map(row => row.csi)} labels={lead.by_lead.map(row => `${row.lead_day}`)} label={`CSI dự báo gió cấp ${lead.level_bf}+ theo số ngày báo trước`} format={value => `CSI ${num(value, 2)}`} />
      <div className="-mt-1 text-[10.5px] text-fg-subtle">số ngày báo trước</div>
      <Disclosure summary="Chi tiết" hint={events != null ? `${events} ngày có gió cấp ${lead.level_bf}+` : undefined}>
        <div className="scroll-thin overflow-x-auto">
          <table className="data-table">
            <thead><tr><th>Trước</th><th className="num">POD</th><th className="num">FAR</th><th className="num">CSI</th><th className="num">Trúng / sự kiện</th></tr></thead>
            <tbody>{lead.by_lead.map(row => (
              <tr key={row.lead_day}><td>{row.lead_day} ngày</td><td className="num">{num(row.pod, 2)}</td><td className="num">{num(row.far, 2)}</td><td className="num">{num(row.csi, 2)}</td><td className="num">{row.hits}/{row.n_event_days}</td></tr>
            ))}</tbody>
          </table>
        </div>
        <p className="m-0">Báo liên tục theo cơn (số ngày liên tiếp trước sự kiện đều báo trúng): {lead.storms.map(row => `${titleCase(row.name)} ${row.consistent_lead_days ?? '0'}`).join(' · ')}.</p>
        <p className="m-0">Mô hình {lead.model} (cố định) so với {lead.truth}{lead.truth_independent ? ' (độc lập)' : ''}, {lead.period.replace('/', ' → ')}; ngày UTC đủ 24 h. Run {lead.source_run}.</p>
      </Disclosure>
    </Tile>
  )
}

function HeatTile({ heat }: { heat: HazardHeat }) {
  const trend = heat.trend_days_per_decade
  const weeks = heat.peak_weeks_watch ?? []
  const peak = weeks.reduce<{ iso_week: number; share_years: number } | null>((best, row) => (!best || row.share_years > best.share_years ? row : best), null)
  const watch = heat.thresholds_c.watch
  return (
    <Tile icon={<ThermometerSun size={15} />} question={`Ngày nước ≥ ${watch ?? '—'} °C có tăng không?`}
      value={trend ? `${(trend.value ?? 0) >= 0 ? '+' : ''}${num(trend.value, 1)}` : '—'} unit="ngày / thập kỷ"
      line={<>{trend ? `CI 95 % ${num(trend.ci95[0], 1)}–${num(trend.ci95[1], 1)}, ${trend.years?.[0]}–${trend.years?.[1]} (OISST).` : 'Không có xu hướng.'}{peak ? ` Hay gặp nhất tuần ${peak.iso_week} (${pct(peak.share_years)} số năm).` : ''}</>}>
      <Disclosure summary="Chi tiết">
        <p className="m-0">Ngưỡng cá giò: theo dõi {watch} °C, căng thẳng {heat.thresholds_c.stress} °C, nghiêm trọng {heat.thresholds_c.severe} °C (đợt ≥ {heat.thresholds_c.min_run_days} ngày). {heat.peak_weeks_stress?.length ? '' : `Chưa năm nào có ngày ≥ ${heat.thresholds_c.stress} °C theo OISST.`}</p>
        {heat.trend_days_per_decade_adjusted && <p className="m-0">Nếu cộng độ lệch cảm biến {num(heat.oisst_offset_c, 2)} °C: {num(heat.trend_days_per_decade_adjusted.value, 1)} ngày / thập kỷ (CI {num(heat.trend_days_per_decade_adjusted.ci95[0], 1)}–{num(heat.trend_days_per_decade_adjusted.ci95[1], 1)}). Độ lệch chỉ từ một mùa, là kịch bản nhạy, không phải hiệu chỉnh.</p>}
        {weeks.length > 0 && <p className="m-0">Tuần có ngày ≥ {watch} °C: {weeks[0].iso_week}–{weeks[weeks.length - 1].iso_week}.</p>}
        <p className="m-0">Run {heat.source_run}.</p>
      </Disclosure>
    </Tile>
  )
}

function HeatSkillTile({ skill }: { skill: HazardHeatSkill }) {
  const best = skill.rows.reduce((top, row) => ((row.csi ?? -1) > (top.csi ?? -1) ? row : top), skill.rows[0])
  return (
    <Tile icon={<Thermometer size={15} />} question="Nguồn nào bắt được ngày nóng ≥ 31 °C?"
      value={num(best?.csi, 2)} unit={`CSI · ${best?.label.toLowerCase()}`}
      line={`Trên ${skill.sensor_days ?? '—'} ngày cảm biến (${skill.hot_days ?? '—'} ngày nóng), kiểm tra bỏ-một-tháng.`}>
      <ul className="m-0 list-none space-y-1 p-0" aria-label="CSI theo nguồn">
        {skill.rows.map(row => (
          <li key={`${row.product}-${row.method}`} className="grid grid-cols-[minmax(0,1fr)_88px_34px] items-center gap-2 text-[11.5px]">
            <span className="truncate text-fg-muted" title={row.label}>{row.label}</span>
            <span className="h-2 rounded-r-[3px] bg-surface-3"><span className="block h-full rounded-r-[3px] bg-[var(--series-1)]" style={{ width: `${Math.max(0, Math.min(1, row.csi ?? 0)) * 100}%` }} /></span>
            <span className="text-right text-fg tabular">{num(row.csi, 2)}</span>
          </li>
        ))}
      </ul>
      <Disclosure summary="Chi tiết">
        <p className="m-0">OISST chưa bao giờ ≥ 31 °C trong mùa này nên không dùng để báo ngày; chỉ dùng cho lịch / khí hậu. Phần lớn kỹ năng đến từ nhiệt độ không khí. Lead 1–3 ngày chỉ là persistence (không có lưu trữ dự báo SST).</p>
        <p className="m-0">{skill.sensor_period[0]} → {skill.sensor_period[1]} · Run {skill.source_run}.</p>
      </Disclosure>
    </Tile>
  )
}

const DISEASE_VERDICT: Record<string, VerdictStatus> = {
  no_skill_over_climatology: { tone: 'warn', label: 'Không hơn khí hậu' },
  insufficient_evidence: { tone: 'neutral', label: 'Chưa đủ bằng chứng' },
  above_climatology_small_n: { tone: 'info', label: 'Hơn khí hậu (mẫu nhỏ)' },
}

function DiseaseTile({ disease }: { disease: HazardDisease }) {
  const verdict = DISEASE_VERDICT[disease.verdict ?? ''] ?? { tone: 'neutral' as const, label: disease.verdict ?? '—' }
  return (
    <Tile icon={<Virus size={15} />} question="Nhiệt độ nước báo trước được dịch bệnh không?"
      value={`${disease.hits_level2 ?? '—'}/${disease.n_events_scored ?? '—'}`} unit="sự kiện có ngày “cao”" status={verdict}
      line={`Kỳ vọng nếu đoán theo mùa: ${num(disease.expected_level2, 2)}. Mức “cao” chiếm ${num(disease.mean_days_high_per_year, 0)} ngày / năm nên không tách được ngày rủi ro.`}>
      <Disclosure summary="Chi tiết">
        {disease.note_vi && <p className="m-0">{disease.note_vi}</p>}
        <p className="m-0">Rét kéo dài: OISST {num(disease.mean_days_cold_high_oisst, 2)} ngày / năm, nhiệt độ không khí ERA5 {num(disease.mean_days_cold_high_era5_air, 2)} ngày / năm (OISST bỏ sót rét 2008, 2016). Đây là phần dùng được hiện tại.</p>
        <p className="m-0">Chỉ {disease.n_pathogen_attributed ?? '—'} sự kiện có tên mầm bệnh ({DISEASE_VERDICT[disease.verdict_pathogen_attributed ?? '']?.label ?? disease.verdict_pathogen_attributed}); {disease.robust_to_shift_1c ? 'vững' : 'không vững'} khi lệch ±1 °C. Run {disease.source_run}.</p>
      </Disclosure>
    </Tile>
  )
}

const titleCase = (name: string | null) => (name ? name.charAt(0) + name.slice(1).toLowerCase() : '—')

const SECTION_LABEL: Record<string, string> = { storm: 'Khí hậu bão', storm_lead: 'Kỹ năng báo trước bão', heat: 'Khí hậu nắng nóng', heat_skill: 'Kỹ năng ngày nóng', disease: 'Dịch bệnh', stocking: 'Lịch thả giống' }

/**
 * Storm / heat / disease / stocking theory track (H2 · weather-aware advisory),
 * from `hazards.json` of the newest research export. Nothing typed in; a
 * missing section says why. Observation only, never an alert input.
 */
export function HazardCard({ poll }: { poll: PollState<Hazards> }) {
  const data = poll.data?.status === 'ready' ? poll.data : null
  if (!data) {
    if (!poll.data && !poll.error) return <Skeleton className="h-48" />
    return (
      <Panel title="Bão, nắng nóng & lịch thả giống" icon={<CloudLightning size={15} />} actions={<StateChip size="xs" state="unavailable" label="Chưa có trong export" />}
        summary={poll.data?.reason ? researchReason(poll.data.reason) : 'Không đọc được export'}>
        <p className="m-0 text-[12px] text-fg-subtle">Chạy lại <span className="font-mono">scripts/export_research_map_artifacts.py</span> để có hazards.json.</p>
      </Panel>
    )
  }
  const omitted = Object.entries(data.sections_omitted ?? {})
  return (
    <Panel title="Bão, nắng nóng & lịch thả giống" icon={<CloudLightning size={15} />} summary="Khí hậu và kỹ năng dự báo tại NB1"
      actions={<StateChip size="xs" state="research_only" />}>
      <div className="grid gap-2.5 sm:grid-cols-2 xl:grid-cols-3">
        {data.storm && <StormTile storm={data.storm} />}
        {data.storm_lead && <LeadTile lead={data.storm_lead} />}
        {data.heat && <HeatTile heat={data.heat} />}
        {data.heat_skill && <HeatSkillTile skill={data.heat_skill} />}
        {data.disease && <DiseaseTile disease={data.disease} />}
      </div>
      {data.stocking && <StockingStrip stocking={data.stocking} />}
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1">
        <Disclosure summary="Nguồn" hint={omitted.length ? `${omitted.length} mục chưa có` : undefined}>
          <p className="m-0">Chỉ quan sát lịch sử, không kích hoạt cảnh báo hay khuyến cáo (used_by_alerts = false). Export {data.export_version}.</p>
          {omitted.map(([key, reason]) => <p key={key} className="m-0">{SECTION_LABEL[key] ?? key}: {researchReason(reason)}</p>)}
        </Disclosure>
      </div>
    </Panel>
  )
}
