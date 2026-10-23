import type { ReactNode } from 'react'
import { Ban, BellOff, CircleCheck, Eye, History, OctagonAlert, Rewind, Settings2, Siren, Tornado, TriangleAlert } from 'lucide-react'
import { Chip, Disclosure } from '../../components/ui'
import type { DataStatus, StationAlerts, StationHazard, StationOutlookDay, StationStormWatch } from '../../types/alerts'
import {
  BAR, EXPOSURE_HINT, EXPOSURE_LABEL, STATUS_LABEL, dayLabel, hazardName, hazardValue, localTime, shortName, skipText,
  tierClass, tierLabel, tierTone, topHazard, usableTier, type TierMeta,
} from './model'

const TEXT = { ok: 'text-ok', info: 'text-info', warn: 'text-warn', danger: 'text-danger' } as const

/** Shape per tier so the state never rests on colour alone. */
export function TierIcon({ tier, size = 14 }: { tier: number; size?: number }) {
  const props = { size, strokeWidth: 2.2, 'aria-hidden': true as const }
  if (tier <= 0) return <CircleCheck {...props} />
  if (tier === 1) return <Eye {...props} />
  if (tier === 2) return <TriangleAlert {...props} />
  if (tier === 3) return <OctagonAlert {...props} />
  return <Siren {...props} />
}

/** Neutral hatch for "not a current state" (stale / no data / not evaluated). */
export const HATCH = { backgroundImage: 'repeating-linear-gradient(-45deg, var(--neutral-bg) 0 5px, transparent 5px 10px)' }

export function TierPill({ tiers, tier, size = 'sm' }: { tiers: TierMeta[]; tier: number; size?: 'xs' | 'sm' }) {
  const sizing = size === 'xs' ? 'h-5 px-1.5 text-[11px] gap-1' : 'h-6 px-2 text-[12px] gap-1.5'
  return (
    <span className={`inline-flex items-center whitespace-nowrap rounded-full border font-semibold ${sizing} ${tierClass(tiers, tier)}`}>
      <TierIcon tier={tier} size={size === 'xs' ? 11 : 13} />
      <span className="tabular">Bậc {tier}</span>
      <span className="font-medium">{tierLabel(tiers, tier)}</span>
    </span>
  )
}

/** "Không đánh giá" pill; the reason is visible text (tooltips do not exist on phones). */
export function NotEvaluated({ reason, status }: { reason?: string; status?: DataStatus }) {
  const label = status === 'stale' && !reason ? 'Cũ' : 'Không đánh giá'
  return (
    <span title={reason ? `Lý do: ${skipText(reason)} (${reason})` : undefined}
      className="inline-flex h-5 items-center gap-1 whitespace-nowrap rounded-full border border-dashed border-[var(--neutral-line)] px-1.5 text-[11px] font-semibold text-neutral">
      {status === 'stale' ? <History size={11} aria-hidden /> : <Ban size={11} aria-hidden />}{label}
    </span>
  )
}

export function StatusChip({ status, ageHours }: { status: DataStatus; ageHours?: number | null }) {
  const age = ageHours != null ? (ageHours < 1 ? `${Math.max(1, Math.round(ageHours * 60))} phút trước` : `${Math.round(ageHours)} giờ trước`) : null
  if (status === 'fresh') return <Chip size="xs" tone="ok" dot title="Lần chạy mới nhất trong 3 giờ">Mới{age ? <span className="font-medium opacity-80">· {age}</span> : null}</Chip>
  if (status === 'stale') return <Chip size="xs" tone="warn" icon={<History size={11} aria-hidden />} title="Lần chạy cuối quá 3 giờ hoặc bản tin đầu vào đã cũ: không phải trạng thái hiện tại">Dữ liệu cũ{age ? <span className="font-medium opacity-80">· {age}</span> : null}</Chip>
  return <Chip size="xs" tone="neutral" icon={<Ban size={11} aria-hidden />}>Không có dữ liệu</Chip>
}

export function ShadowChip() {
  return (
    <Chip size="xs" tone="neutral" icon={<BellOff size={11} aria-hidden />}
      title="Chạy song song để đánh giá (shadow); ngưỡng theo lý thuyết, chưa kiểm chứng hiện trường; không gửi thông báo cho người nuôi.">
      Shadow · lý thuyết · không gửi thông báo
    </Chip>
  )
}

export function ReplayChip({ size = 'xs' }: { size?: 'xs' | 'sm' }) {
  return <Chip size={size} tone="mock" title="Dữ liệu phát lại (quá khứ/tái phân tích chạy lại như bản tin), không phải hiện tại" icon={<Rewind size={size === 'xs' ? 11 : 12} aria-hidden />} className="mock-stripes">{size === 'xs' ? 'Phát lại · không phải hiện tại' : 'Dữ liệu phát lại, không phải hiện tại'}</Chip>
}

const pct = (p: number | null | undefined) => (p == null ? '—' : `${Math.round(p * 100)} %`)

/** Storm-watch chip, shown only when the watch reaches tier ≥ 1 (p ≥ threshold) on fresh data. */
export function StormChip({ watch }: { watch: StationStormWatch | null | undefined }) {
  if (!watch || watch.data_status !== 'fresh' || watch.tier == null || watch.tier < 1) return null
  const name = watch.storm_name ?? watch.storm_id
  return (
    <Chip size="xs" tone={watch.tier >= 2 ? 'warn' : 'info'} icon={<Tornado size={11} aria-hidden />}
      title={`Xác suất tâm bão đi trong 500 km quanh trạm trong 120 giờ (ECMWF ENS); ngưỡng theo dõi ${pct(watch.threshold)}. Không tự nâng thành cảnh báo.${watch.site_note ? ' Tính cho điểm tóm tắt của vùng, không riêng trạm.' : ''}`}>
      Bão{name ? ` ${name}` : ''}: {pct(watch.p_within_500km_120h)} trong 500 km · 5 ngày
    </Chip>
  )
}

/** 5 × 24 h lead blocks; a block with no fresh evaluated hazard is hatched and says so. */
export function OutlookStrip({ days, tiers, stationName }: { days: StationOutlookDay[]; tiers: TierMeta[]; stationName: string }) {
  if (!days.length) return null
  return (
    <ol className="m-0 grid list-none grid-cols-5 gap-1 p-0" aria-label={`Triển vọng 5 ngày, ${stationName}`}>
      {days.map((day, index) => {
        const label = dayLabel(day.date)
        const head = index === 0 ? 'Hôm nay' : label.weekday
        const window = `${day.lead_from_h ?? index * 24}–${day.lead_to_h ?? (index + 1) * 24} h`
        const tier = day.data_status === 'fresh' ? day.max_tier : null
        const text = tier == null
          ? (day.data_status === 'stale' ? 'cũ' : 'không có')
          : tierLabel(tiers, tier)
        const reason = tier == null ? (day.data_status === 'stale' ? 'Dữ liệu cũ' : 'Không có đánh giá') : `Bậc ${tier} · ${tierLabel(tiers, tier)}`
        return (
          <li key={day.date + index} title={`${head} ${label.date} · khung ${window} từ lúc phát · ${reason}`}
            aria-label={`${head} ${label.date}: ${reason}`}
            className={`flex min-w-0 flex-col items-center gap-0.5 rounded-[var(--radius-xs)] border px-0.5 py-1 text-center ${tier == null ? 'border-dashed border-[var(--neutral-line)] text-neutral' : tierClass(tiers, tier)}`}
            style={tier == null ? HATCH : undefined}>
            <span className="text-[10.5px] font-medium leading-none opacity-90">{head}</span>
            <span className="flex items-center gap-0.5 text-[13px] font-semibold leading-none">
              {tier == null ? <span aria-hidden>–</span> : <><TierIcon tier={tier} size={12} /><span className="tabular">{tier}</span></>}
            </span>
            <span className="w-full truncate text-[10px] leading-none opacity-90">{text}</span>
          </li>
        )
      })}
    </ol>
  )
}

function HazardRow({ h, tiers }: { h: StationHazard; tiers: TierMeta[] }) {
  const tier = usableTier(h)
  const stale = h.data_status === 'stale'
  return (
    <tr>
      <td className="whitespace-nowrap font-medium">{hazardName(h)}</td>
      <td className="whitespace-nowrap tabular">{h.skip_reason ? '—' : hazardValue(h)}</td>
      <td>
        {tier != null ? <TierPill tiers={tiers} tier={tier} size="xs" />
          : <NotEvaluated reason={h.skip_reason} status={h.data_status} />}
        {stale && h.tier != null && !h.skip_reason && <div className="mt-0.5 text-[11px] text-fg-subtle">bậc {h.tier} lúc chạy (cũ)</div>}
        {h.skip_reason && <div className="mt-0.5 text-[11px] text-fg-subtle">{skipText(h.skip_reason)}</div>}
      </td>
      <td className="min-w-[180px] text-fg-muted">{tier ? h.action_vi : ''}</td>
    </tr>
  )
}

function inputsText(h: StationHazard): string {
  const i = h.inputs ?? {}
  return [i.source, i.model].filter(Boolean).join(' / ')
}

export function StationDetails({ station, tiers }: { station: StationAlerts; tiers: TierMeta[] }) {
  const inputs = [...new Set(station.current.map(inputsText).filter(Boolean))]
  return (
    <Disclosure summary="Chi tiết" hint={`${station.current.length} mối nguy`}>
      {station.current.length > 0 ? (
        <div className="scroll-thin -mx-1 overflow-x-auto">
          <table className="data-table">
            <thead><tr><th scope="col">Mối nguy (0–24 h)</th><th scope="col">Giá trị</th><th scope="col">Bậc</th><th scope="col">Việc nên làm</th></tr></thead>
            <tbody>{station.current.map(h => <HazardRow key={h.hazard} h={h} tiers={tiers} />)}</tbody>
          </table>
        </div>
      ) : <p className="m-0">{skipText(station.reason) || 'Không có bản ghi.'}</p>}
      <dl className="m-0 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
        <dt className="text-fg-subtle">Đầu vào</dt><dd className="m-0 break-words text-fg">{inputs.join(' · ') || '—'}</dd>
        {station.replay && <><dt className="text-fg-subtle">Phát lại</dt><dd className="m-0 text-fg">{station.replay_labels?.join(', ') || 'có'} — không phải bản tin hiện tại</dd></>}
        <dt className="text-fg-subtle">Lần chạy</dt><dd className="m-0 text-fg">{localTime(station.issued_at)}</dd>
        <dt className="text-fg-subtle">Bộ ngưỡng</dt><dd className="m-0 text-fg"><code>{station.config_version ?? '—'}</code></dd>
        {station.storm_watch && <><dt className="text-fg-subtle">Theo dõi bão</dt><dd className="m-0 text-fg">
          {station.storm_watch.skip_reason ? skipText(station.storm_watch.skip_reason)
            : `${pct(station.storm_watch.p_within_500km_120h)} (ngưỡng ${pct(station.storm_watch.threshold)}) · ${STATUS_LABEL[station.storm_watch.data_status]} · ${station.storm_watch.model ?? station.storm_watch.source}`}
        </dd></>}
      </dl>
      <a href="#/settings/alerts" className="inline-flex items-center gap-1 font-semibold text-accent hover:underline">
        <Settings2 size={13} aria-hidden />Xem / chỉnh ngưỡng cảnh báo
      </a>
    </Disclosure>
  )
}

/** One station: answer line (tier now), the reason (top hazard + action), 5-day strip, provenance chips. */
export function StationCard({ station, tiers, id }: { station: StationAlerts; tiers: TierMeta[]; id: string }) {
  const fresh = station.data_status === 'fresh' && station.max_tier != null
  const tier = fresh ? station.max_tier! : null
  const top = fresh && station.max_tier! > 0 ? topHazard(station) : null
  const skipped = station.current.filter(h => h.skip_reason)
  const skipReasons = [...new Set(skipped.map(h => skipText(h.skip_reason)))]
  const name = shortName(station.name)
  let headline: ReactNode
  if (tier != null) {
    headline = <span className={`inline-flex items-center gap-1.5 ${TEXT[tierTone(tiers, tier)]}`}><TierIcon tier={tier} size={18} /><span>Bậc {tier} · {tierLabel(tiers, tier)}</span></span>
  } else if (station.data_status === 'stale') {
    headline = <span className="inline-flex items-center gap-1.5 text-neutral"><History size={18} aria-hidden /><span>Dữ liệu cũ — không xếp bậc</span></span>
  } else {
    headline = <span className="inline-flex items-center gap-1.5 text-neutral"><Ban size={18} aria-hidden /><span>Không có dữ liệu</span></span>
  }
  return (
    <article id={id} tabIndex={-1} aria-labelledby={`${id}-name`}
      className="relative flex min-w-0 flex-col gap-2.5 overflow-hidden rounded-[var(--radius-md)] border border-line bg-surface py-3 pl-4 pr-3.5 shadow-[var(--shadow-sm)] focus-visible:outline-2">
      <span className={`absolute inset-y-0 left-0 w-1 ${tier != null ? BAR[tierTone(tiers, tier)] : ''}`} style={tier == null ? HATCH : undefined} aria-hidden />
      <header className="flex flex-wrap items-start justify-between gap-x-2 gap-y-1">
        <div className="min-w-0">
          <h3 id={`${id}-name`} className="m-0 truncate text-[14.5px] font-semibold text-fg" title={station.name}>{name}</h3>
          <div className="text-[11.5px] text-fg-subtle tabular">{station.id}</div>
        </div>
        {station.exposure_class
          ? <Chip size="xs" tone="neutral" title={EXPOSURE_HINT[station.exposure_class]}>{EXPOSURE_LABEL[station.exposure_class]}</Chip>
          : <Chip size="xs" tone="neutral" title="Chưa có phân loại che chắn: gió được coi như ngoài khơi">Chưa phân loại</Chip>}
      </header>
      <div className="text-[16px] font-semibold leading-tight">{headline}</div>
      {top ? (
        <p className="m-0 line-clamp-1 text-[12.5px] leading-snug text-fg" title={top.action_vi ?? undefined}>
          <span className="font-semibold">{hazardName(top)} {hazardValue(top)}</span>
          {top.action_vi ? <span className="text-fg-muted"> — {top.action_vi}</span> : null}
        </p>
      ) : (
        <p className="m-0 text-[12.5px] text-fg-muted">
          {tier === 0 ? 'Mọi mối nguy được đánh giá đều bình thường.'
            : station.data_status === 'stale' ? `Lần chạy cuối ${localTime(station.issued_at)}; không dùng làm trạng thái hiện tại.`
              : skipText(station.reason) || 'Chưa có đánh giá cho trạm này.'}
        </p>
      )}
      {skipped.length > 0 && station.data_status !== 'unavailable' && (
        <p className="m-0 -mt-1 text-[11.5px] text-fg-subtle">
          {skipped.map(h => hazardName(h)).join(', ')}: không đánh giá ({skipReasons.join('; ')}).
        </p>
      )}
      <OutlookStrip days={station.outlook} tiers={tiers} stationName={name} />
      <div className="flex flex-wrap items-center gap-1.5">
        <StatusChip status={station.data_status} ageHours={station.age_hours} />
        <StormChip watch={station.storm_watch} />
        {station.replay && <ReplayChip />}
      </div>
      <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1">
        <StationDetails station={station} tiers={tiers} />
        <span className="inline-flex items-center gap-1 pt-0.5 text-[11px] text-fg-subtle" title="Chạy song song để đánh giá (shadow); ngưỡng theo lý thuyết, chưa kiểm chứng hiện trường; không gửi thông báo cho người nuôi.">
          <BellOff size={11} aria-hidden />Shadow · lý thuyết · không gửi thông báo
        </span>
      </div>
    </article>
  )
}
