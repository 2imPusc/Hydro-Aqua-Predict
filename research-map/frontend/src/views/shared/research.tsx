import type { ReactNode } from 'react'
import { Archive, BookOpen, CircleAlert, FlaskConical, RefreshCw, ShieldAlert } from 'lucide-react'
import { getResearchOverview, researchReason } from '../../api/research'
import { describeApiError } from '../../api/client'
import { usePolling, type PollState } from '../../hooks/usePolling'
import { Chip, EmptyState, Panel, SectionLabel, Skeleton } from '../../components/ui'
import { splitRefs } from '../../lib/format'
import type { Direction, DirectionId, ResearchEnvelope } from '../../types/research'

/** Fetch-once research endpoint (exports are immutable; the backend caches by mtime). */
export function useResearch<T>(fetcher: (signal: AbortSignal) => Promise<T>, deps: readonly unknown[] = [], options: { intervalMs?: number | null; keepPreviousData?: boolean } = {}) {
  return usePolling<T>(fetcher, { intervalMs: options.intervalMs ?? null, deps, maxErrorRetries: 3, retryBaseMs: 3_000, keepPreviousData: options.keepPreviousData })
}

/** Shared overview (one request per view mount; the backend serves it from cache). */
export function useDirection(id: DirectionId): { direction: Direction | null; poll: PollState<Awaited<ReturnType<typeof getResearchOverview>>> } {
  const poll = useResearch(getResearchOverview)
  return { direction: poll.data?.directions?.find(item => item.id === id) ?? null, poll }
}

/** Research-log reference chips (RL-14 …) pulled from the end of a finding. */
export function RefChips({ refs }: { refs: string[] }) {
  if (!refs.length) return null
  return <>{refs.map(ref => <Chip key={ref} size="xs" tone="neutral" title={`Xem docs/research-log.md · ${ref}`}>{ref}</Chip>)}</>
}

export function FindingList({ items, icon, empty = 'Không có mục nào.' }: { items: string[] | undefined; icon?: ReactNode; empty?: string }) {
  if (!items?.length) return <p className="m-0 text-[12px] text-fg-subtle">{empty}</p>
  return (
    <ul className="m-0 list-none space-y-1.5 p-0">
      {items.map((item, index) => {
        const { text, refs } = splitRefs(item)
        return (
          <li key={index} className="flex gap-2 text-[12.5px] leading-snug text-fg">
            <span className="mt-[3px] flex-none text-fg-subtle" aria-hidden>{icon ?? '•'}</span>
            <span className="min-w-0">{text} <span className="inline-flex flex-wrap gap-1 align-middle"><RefChips refs={refs} /></span></span>
          </li>
        )
      })}
    </ul>
  )
}

/**
 * Compact page header for research views: code, title and provenance chips.
 * The answer itself lives in the view's Verdict card, so the export headline
 * is not repeated here as prose.
 */
/** Export stamp "20261023-0332" → "23/10 03:32"; any other shape is shown as is. */
const exportStamp = (version: string) => {
  const match = /^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})/.exec(version)
  return match ? `${match[3]}/${match[2]} ${match[4]}:${match[5]}` : version
}

export function ResearchHeader({ code, title, direction, exportVersion, children }: { code: string; title: string; direction: Direction | null; exportVersion?: string | null; children?: ReactNode }) {
  return (
    <header className="flex flex-wrap items-center gap-x-3 gap-y-2">
      <span className="rounded-[var(--radius-xs)] bg-accent-soft px-1.5 py-0.5 text-[12px] font-bold text-accent">{code}</span>
      <h2 className="m-0 text-[20px] font-semibold tracking-tight text-fg">{title}</h2>
      <div className="flex flex-wrap items-center gap-1.5">
        <Chip size="xs" tone="info" icon={<FlaskConical size={11} />} title="Kết quả nghiên cứu, không dùng cho cảnh báo hay người nuôi">Chỉ nghiên cứu</Chip>
        {direction?.stage && <Chip size="xs" tone="neutral" title="Giai đoạn nghiên cứu">{direction.stage}</Chip>}
        {children}
        {exportVersion !== undefined && (
          <Chip size="xs" tone={exportVersion ? 'neutral' : 'warn'} icon={<Archive size={11} />} title={`Bản xuất kết quả nghiên cứu ${exportVersion ?? ''} (artifacts/research-map/)`}>
            {exportVersion ? `Kết quả ${exportStamp(exportVersion)}` : 'chưa có bản xuất'}
          </Chip>
        )}
      </div>
    </header>
  )
}

/** Explicit unavailable state for a research envelope or a failed request. Never fabricated values. */
export function Unavailable({ envelope, error, title = 'Không có dữ liệu', onRetry, compact }: { envelope?: ResearchEnvelope | null; error?: string | null; title?: string; onRetry?: () => void; compact?: boolean }) {
  const description = envelope && envelope.status === 'unavailable' ? researchReason(envelope.reason) : error ? describeApiError(error) : 'Không rõ lý do.'
  return (
    <EmptyState compact={compact} tone="danger" icon={<ShieldAlert size={compact ? 15 : 20} />} title={title} description={<>{description}{envelope?.reason && <span className="mt-1 block font-mono text-[10.5px] text-fg-subtle">{envelope.reason}</span>}</>}>
      {onRetry && (
        <button type="button" onClick={onRetry} className="inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] border border-line bg-surface px-2.5 py-1 text-[12px] font-semibold text-fg hover:bg-surface-3">
          <RefreshCw size={13} /> Thử lại
        </button>
      )}
    </EmptyState>
  )
}

/** Renders loading / error / unavailable for a research poll, else the children with ready data. */
export function ResearchGate<T extends ResearchEnvelope>({ poll, title, children, skeleton }: { poll: PollState<T>; title?: string; children: (data: T) => ReactNode; skeleton?: ReactNode }) {
  if (!poll.data) {
    if (poll.error) return <Unavailable error={poll.error} title={title} onRetry={poll.refresh} />
    return <>{skeleton ?? <div className="space-y-2 py-4" aria-busy="true"><Skeleton className="h-4 w-1/3" /><Skeleton className="h-24 w-full" /></div>}</>
  }
  if (poll.data.status !== 'ready') return <Unavailable envelope={poll.data} title={title} onRetry={poll.refresh} />
  return <>{children(poll.data)}</>
}

/** Findings / limitations / next steps / research log for one direction (from overview.json). */
export function DirectionPanel({ direction, poll, defaultOpen = false }: { direction: Direction | null; poll: PollState<unknown>; defaultOpen?: boolean }) {
  const summary = direction ? `${direction.findings.length} phát hiện · ${direction.limitations.length} giới hạn · ${direction.next.length} bước tiếp` : undefined
  return (
    <Panel title="Tóm tắt nghiên cứu" icon={<BookOpen size={15} />} collapsible defaultOpen={defaultOpen} summary={summary}>
      {!direction && poll.error && <Unavailable compact error={poll.error} />}
      {!direction && !poll.error && <div className="space-y-2"><Skeleton className="h-3 w-full" /><Skeleton className="h-3 w-5/6" /></div>}
      {direction && (
        <>
          <SectionLabel>Phát hiện</SectionLabel>
          <FindingList items={direction.findings} />
          <SectionLabel icon={<CircleAlert size={12} />}>Giới hạn</SectionLabel>
          <FindingList items={direction.limitations} icon="!" />
          <SectionLabel>Bước tiếp theo</SectionLabel>
          <FindingList items={direction.next} icon="→" />
          <details className="mt-3 text-[12px] text-fg-muted">
            <summary className="cursor-pointer font-semibold text-fg-subtle">Nhật ký nghiên cứu ({direction.research_log.length})</summary>
            <ul className="m-0 mt-1.5 list-none space-y-1 p-0">{direction.research_log.map(item => <li key={item}>{item}</li>)}</ul>
          </details>
        </>
      )}
    </Panel>
  )
}

/** Scrollable page body used by the non-map research views. */
export function PageScroll({ children }: { children: ReactNode }) {
  return (
    <div className="scroll-thin h-full overflow-y-auto">
      <div className="mx-auto flex max-w-[1320px] flex-col gap-4 px-4 py-4 md:px-6 md:py-5">{children}</div>
    </div>
  )
}

export function GateChip({ gate, size = 'xs' }: { gate: string | null | undefined; size?: 'xs' | 'sm' }) {
  if (gate === 'pass') return <Chip size={size} tone="ok" title="Đạt gate #16">Đạt</Chip>
  if (gate === 'fail') return <Chip size={size} tone="danger" title="Không đạt gate #16">Không đạt</Chip>
  return <Chip size={size} tone="neutral" title="Không có gate cho dòng này">—</Chip>
}
