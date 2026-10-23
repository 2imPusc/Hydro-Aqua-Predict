import { FlaskConical } from 'lucide-react'
import { RELIABILITY_HASH, type ReliabilityTab } from '../../app/routes'
import { Chip } from '../../components/ui'
import type { Theme } from '../../hooks/useTheme'
import { useDirection } from '../shared/research'
import { ForeignDetail } from './ForeignDetail'
import { ForeignOverview } from './ForeignOverview'
import { VnTab } from './VnTab'

const TABS: Array<{ value: ReliabilityTab; label: string }> = [
  { value: 'vn', label: 'Việt Nam' },
  { value: 'foreign', label: 'Kiểm chứng quốc tế' },
]

/** H4 with deep-linkable tabs: #/reliability (VN), #/reliability/foreign, #/reliability/foreign/<id>. */
export default function ReliabilityView({ tab = 'vn', datasetId, theme }: { tab?: ReliabilityTab; datasetId?: string; theme: Theme }) {
  const { direction } = useDirection('H4')
  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-none items-center gap-3 border-b border-line bg-surface px-4">
        <nav aria-label="Độ tin cậy" className="flex gap-1">
          {TABS.map(item => {
            const active = item.value === tab
            return (
              <a key={item.value} href={RELIABILITY_HASH[item.value]} aria-current={active ? 'page' : undefined}
                className={`-mb-px border-b-2 px-3 py-2.5 text-[13px] font-semibold no-underline transition-colors ${active ? 'border-accent text-fg' : 'border-transparent text-fg-subtle hover:text-fg'}`}>
                {item.label}
              </a>
            )
          })}
        </nav>
        <p className="m-0 hidden min-w-0 flex-1 truncate text-[12px] text-fg-muted lg:block" title={direction?.headline}>{direction?.headline}</p>
        <Chip size="xs" tone="info" icon={<FlaskConical size={11} />}>Chỉ nghiên cứu</Chip>
      </div>
      <div className="relative min-h-0 flex-1">
        {tab === 'vn' && <VnTab theme={theme} />}
        {tab === 'foreign' && !datasetId && <ForeignOverview direction={direction} />}
        {tab === 'foreign' && datasetId && <ForeignDetail id={datasetId} theme={theme} />}
      </div>
    </div>
  )
}
