import { ArrowRight, Ban, Globe2, Lock, Sigma, Unlock } from 'lucide-react'
import { getForeignDetail, getForeignIndex, getReliabilitySummary, researchReason } from '../../api/research'
import { foreignDatasetHash } from '../../app/routes'
import { Chip, Disclosure, Panel, Skeleton } from '../../components/ui'
import { radiusText, splitRefs, stopLabel, variableLabel } from '../../lib/format'
import type { Direction, ForeignDataset, ReliabilitySummary } from '../../types/research'
import { FindingList, RefChips, ResearchGate, useResearch } from '../shared/research'

/** Featured order (owner recommendation): HK EPD and USGS SF Bay first. */
export const FEATURED = ['hk_epd', 'usgs_sfbay', 'nerrs_multi', 'mddnr', 'twdb', 'nerrs_jobos']
const order = (id: string) => { const i = FEATURED.indexOf(id); return i < 0 ? 99 : i }
/** Datasets the plan expects but that may not be exported yet: probed, shown disabled with the reason. */
const EXPECTED = [{ id: 'irlon', name: 'IRLON: Indian River Lagoon (HBOI-FAU)', credit: 'Harbor Branch Oceanographic Institute at Florida Atlantic University (IRLON)' }]

export function RedistributableBadge({ value }: { value: boolean }) {
  return value
    ? <Chip size="xs" tone="ok" icon={<Unlock size={11} />} title="Dữ liệu công khai, có thể phân phối lại">Phân phối lại được</Chip>
    : <Chip size="xs" tone="warn" icon={<Lock size={11} />} title="Không phân phối lại dữ liệu thô: chỉ hiển thị thống kê tổng hợp theo cặp/bán kính">Chỉ thống kê tổng hợp</Chip>
}

function DatasetCard({ dataset }: { dataset: ForeignDataset }) {
  return (
    <a href={foreignDatasetHash(dataset.id)} className="group flex flex-col gap-2 rounded-[var(--radius-lg)] border border-line bg-surface p-3.5 no-underline shadow-[var(--shadow-sm)] transition-colors hover:border-accent focus-visible:border-accent">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className="text-[12px] text-fg-muted">{dataset.region} · {dataset.country} · {dataset.period}</div>
          <h3 className="m-0 mt-0.5 text-[13.5px] font-semibold leading-snug text-fg">{dataset.name}</h3>
        </div>
        <ArrowRight size={16} className="mt-1 flex-none text-fg-subtle transition-transform group-hover:translate-x-0.5 group-hover:text-accent" aria-hidden />
      </div>
      <p className="m-0 line-clamp-2 text-[13px] leading-snug text-fg" title={dataset.headline}>{splitRefs(dataset.headline).text}</p>
      <div className="flex flex-wrap gap-1">
        <Chip size="xs" tone="neutral">{dataset.n_stations} trạm · {dataset.n_pairs} cặp</Chip>
        <Chip size="xs" tone="neutral">{dataset.cadence}</Chip>
        <RedistributableBadge value={dataset.redistributable} />
      </div>
      <div className="mt-auto border-t border-line pt-2 text-[11.5px] leading-snug text-fg-subtle">
        <span title={dataset.licence}><span className="font-semibold text-fg-muted">Nguồn:</span> {dataset.credit}</span>
      </div>
    </a>
  )
}

function ExpectedCard({ id, name, credit }: { id: string; name: string; credit: string }) {
  const probe = useResearch(signal => getForeignDetail(id, {}, signal))
  if (probe.data?.status === 'ready') return null  // exported: the index card covers it
  const reason = probe.data?.reason ?? (probe.error ? probe.error : null)
  return (
    <div aria-disabled="true" className="flex flex-col gap-2 rounded-[var(--radius-lg)] border border-dashed border-line-strong bg-surface-2 p-3.5 opacity-80">
      <div className="flex items-center gap-2"><Ban size={14} className="text-fg-subtle" aria-hidden /><h3 className="m-0 text-[13.5px] font-semibold text-fg-muted">{name}</h3></div>
      <p className="m-0 text-[12px] text-fg-subtle">{probe.data || probe.error ? `Chưa xuất: ${researchReason(reason)}` : 'Đang kiểm tra…'}</p>
      {reason && <span className="font-mono text-[10.5px] text-fg-subtle">{reason}</span>}
      <div className="mt-auto border-t border-line pt-2 text-[11px] text-fg-subtle"><span className="font-semibold">Nguồn:</span> {credit}</div>
    </div>
  )
}

const SUMMARY_VARS = ['Temp', 'Sal', 'pH', 'DO', 'Turb', 'TSS']

function SummaryTable({ data }: { data: ReliabilitySummary }) {
  const datasets = [...(data.datasets ?? [])].sort((a, b) => order(a.id) - order(b.id))
  const extra = [...new Set(datasets.flatMap(d => d.rows.map(r => r.var)))].filter(v => !SUMMARY_VARS.includes(v)).sort()
  const vars = [...SUMMARY_VARS.filter(v => datasets.some(d => d.rows.some(r => r.var === v))), ...extra]
  return (
    <div className="scroll-thin overflow-x-auto rounded-[var(--radius-sm)] border border-line">
      <table className="data-table" aria-label="Bán kính 80 % thô theo bộ dữ liệu và biến">
        <thead>
          <tr><th>Bộ dữ liệu</th><th>Thang</th>{vars.map(v => <th key={v} className="num">{variableLabel(v)}</th>)}</tr>
        </thead>
        <tbody>{datasets.map(d => (
          <tr key={d.id}>
            <td className="whitespace-nowrap"><a href={foreignDatasetHash(d.id)} className="font-semibold text-accent no-underline hover:underline">{d.name.split(' — ')[0]}</a> <span className="text-fg-subtle">{d.research_log}</span></td>
            <td className="whitespace-nowrap text-fg-muted">{d.cadence}</td>
            {vars.map(v => {
              const row = d.rows.find(r => r.var === v)
              if (!row) return <td key={v} className="num text-fg-subtle">—</td>
              const zero = row.radius_km === 0
              return (
                <td key={v} className="num whitespace-nowrap" title={`${row.regime === 'same' ? 'cùng chế độ' : 'tất cả cặp'} · ${row.scale}${row.stop ? ` · ${stopLabel(row.stop)}` : ''}`}>
                  <span className={zero ? 'text-fg-subtle' : row.radius_km == null && !row.radius_label ? 'text-fg-subtle italic' : 'font-semibold text-fg'}>{radiusText(row)}</span>
                  {row.regime !== 'same' && <sup className="ml-0.5 text-fg-subtle" title="Bộ này không tách theo chế độ mặn: dùng tất cả cặp">†</sup>}
                </td>
              )
            })}
          </tr>
        ))}</tbody>
      </table>
      <div className="border-t border-line px-2 py-1.5">
        <Disclosure summary="Cách đọc bảng">
          <p className="m-0">Mỗi ô = khoảng cách lớn nhất mà giá trị lấy nguyên từ trạm này sang trạm kia vẫn đúng ≥ 80 % thời gian (cặp cùng chế độ mặn).</p>
          <p className="m-0">† = bộ không tách chế độ (dùng tất cả cặp). “—” = biến không có trong bộ. Jobos không có bảng bán kính (4 trạm, phân theo môi trường sống). Số lấy từ bản export, không gõ tay.</p>
        </Disclosure>
      </div>
    </div>
  )
}

export function ForeignOverview({ direction }: { direction: Direction | null }) {
  const index = useResearch(getForeignIndex)
  const summary = useResearch(getReliabilitySummary)
  return (
    <div className="scroll-thin h-full overflow-y-auto">
      <div className="mx-auto flex max-w-[1320px] flex-col gap-4 px-4 py-4 md:px-6 md:py-5">
        <div>
          <h2 className="m-0 text-[20px] font-semibold tracking-tight text-fg">Mượn giá trị trạm được bao xa?</h2>
          <p className="m-0 mt-1 line-clamp-2 max-w-[70ch] text-[13px] text-fg-muted">{direction?.headline ?? 'Kiểm tra cùng một giao thức cặp trạm trên dữ liệu nước ngoài.'} Chỉ chuyển phương pháp sang VN, không chuyển con số.</p>
        </div>
        <Panel title="Bán kính đạt 80 % theo bộ dữ liệu" icon={<Sigma size={15} />} actions={<RefChips refs={['RL-24']} />}>
          <ResearchGate poll={summary} title="Chưa có bảng tổng hợp">{data => <SummaryTable data={data} />}</ResearchGate>
        </Panel>
        <h3 className="m-0 mt-1 text-[14px] font-semibold text-fg">Chọn một bộ để xem bản đồ cặp trạm</h3>
        <ResearchGate poll={index} title="Chưa có danh mục bộ dữ liệu" skeleton={<div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{[0, 1, 2].map(i => <Skeleton key={i} className="h-40" />)}</div>}>
          {data => (
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {[...(data.datasets ?? [])].sort((a, b) => order(a.id) - order(b.id)).map(dataset => <DatasetCard key={dataset.id} dataset={dataset} />)}
              {EXPECTED.filter(e => !(data.datasets ?? []).some(d => d.id === e.id)).map(e => <ExpectedCard key={e.id} {...e} />)}
            </div>
          )}
        </ResearchGate>
        <Panel title="Phát hiện chính" icon={<Globe2 size={15} />} collapsible defaultOpen={false}
          summary={direction ? `${direction.findings.length} phát hiện · ${direction.limitations.length} giới hạn` : undefined}>
          {direction ? (
            <>
              <FindingList items={direction.findings} />
              <div className="mt-3"><FindingList items={direction.limitations} icon="!" /></div>
            </>
          ) : <Skeleton className="h-24" />}
        </Panel>
      </div>
    </div>
  )
}
