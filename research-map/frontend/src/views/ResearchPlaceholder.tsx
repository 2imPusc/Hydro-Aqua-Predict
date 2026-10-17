import type { ReactNode } from 'react'
import { Construction } from 'lucide-react'
import { getResearchOverview, researchReason } from '../api/research'
import { describeApiError } from '../api/client'
import { usePolling } from '../hooks/usePolling'
import { EmptyState, Panel, StateChip } from '../components/ui'
import type { DirectionId } from '../types/research'

type Props = {
  direction: DirectionId
  title: string
  planned: ReactNode[]
  endpoints: string[]
  children?: ReactNode
}

/** Placeholder for research views (Task 3) with an honest probe of the research API. */
export function ResearchPlaceholder({ direction, title, planned, endpoints, children }: Props) {
  const overview = usePolling(getResearchOverview, { maxErrorRetries: 2 })
  const summary = overview.data?.directions?.find(item => item.id === direction)
  const apiState = overview.data ? (overview.data.status === 'ready' ? 'ready' : 'unavailable') : overview.error ? 'unavailable' : 'loading'
  const apiNote = overview.data
    ? overview.data.status === 'ready' ? `export ${overview.data.export_version ?? '—'}` : researchReason(overview.data.reason)
    : overview.error ? describeApiError(overview.error) : 'đang kiểm tra…'

  return (
    <div className="scroll-thin h-full overflow-y-auto">
      <div className="mx-auto flex max-w-3xl flex-col gap-4 px-6 py-8">
        <Panel>
          <EmptyState icon={<Construction size={22} />} tone="info" title="Đang xây dựng" description={`${title} sẽ có ở bước tiếp theo của bản thiết kế lại. Giao diện chỉ hiển thị dữ liệu từ bản export nghiên cứu — không bịa số liệu khi thiếu.`}>
            {children}
          </EmptyState>
        </Panel>
        <div className="grid gap-4 md:grid-cols-2">
          <Panel title="Sẽ hiển thị">
            <ul className="m-0 list-disc space-y-1 pl-4 text-[12.5px] text-fg-muted">{planned.map((item, index) => <li key={index}>{item}</li>)}</ul>
          </Panel>
          <Panel title="Nguồn dữ liệu" actions={<StateChip size="xs" state={apiState} />}>
            <p className="m-0 text-[12px] text-fg-muted">Research API: {apiNote}</p>
            <ul className="m-0 mt-2 list-none space-y-1 p-0">{endpoints.map(endpoint => <li key={endpoint}><code className="rounded bg-surface-2 px-1.5 py-0.5 font-mono text-[11px] text-fg-muted">GET /api/v1/research{endpoint}</code></li>)}</ul>
            {summary && <p className="m-0 mt-3 text-[12px] text-fg"><b>{summary.stage}</b> · {summary.headline}</p>}
          </Panel>
        </div>
      </div>
    </div>
  )
}
