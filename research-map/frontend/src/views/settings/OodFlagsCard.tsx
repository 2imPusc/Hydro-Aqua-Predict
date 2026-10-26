import { useId } from 'react'
import { Info } from 'lucide-react'
import { Chip, Disclosure, Toggle } from '../../components/ui'
import type { AlertConfig } from '../../types/alerts'

type Props = {
  draft: AlertConfig
  base: AlertConfig
  onToggle: (metric: string, enabled: boolean) => void
}

/**
 * Per-metric on/off for the imputer "outside training range" flag (alert-config `ood_flags`).
 * Global (not scoped). Off = the metric no longer raises the shared flag or warning text;
 * the out-of-range detail is still written to diagnostics and shadow ledgers.
 */
export function OodFlagsCard({ draft, base, onToggle }: Props) {
  const headingId = useId()
  const metrics = Object.entries(draft.ood_flags?.metrics ?? {})
  if (!metrics.length) return null
  const muted = metrics.filter(([, item]) => !item.enabled)

  return (
    <section aria-labelledby={headingId} className="min-w-0 rounded-[var(--radius-lg)] border border-line bg-surface p-3.5 shadow-[var(--shadow-sm)] md:p-4">
      <header className="mb-2 flex flex-wrap items-start gap-x-3 gap-y-1">
        <div className="min-w-0 flex-1">
          <h2 id={headingId} className="m-0 text-[14.5px] font-semibold leading-snug text-fg">Cờ ngoài phạm vi huấn luyện</h2>
          <p className="m-0 text-[12px] text-fg-subtle">
            Gắn khi số đo cảm biến nằm ngoài khoảng của dữ liệu tỉnh dùng để ước tính các chỉ số không đo được (DO, độ mặn…). Áp dụng chung cho mọi trạm.
          </p>
        </div>
        <Chip tone={muted.length ? 'warn' : 'ok'} size="xs">
          {muted.length ? `Đang tắt ${muted.length}/${metrics.length}` : 'Bật tất cả'}
        </Chip>
      </header>

      <div className="grid gap-x-3 sm:grid-cols-2" role="group" aria-label="Bật hoặc tắt cờ theo chỉ số">
        {metrics.map(([metric, item]) => {
          const changed = base.ood_flags?.metrics[metric]?.enabled !== item.enabled
          return (
            <Toggle key={metric} checked={item.enabled} onChange={checked => onToggle(metric, checked)} label={item.label_vi}
              description={item.enabled ? 'Bật · ngoài phạm vi thì gắn cờ' : (item.muted_reason_vi ? `Đã tắt · ${item.muted_reason_vi}` : 'Đã tắt · vẫn ghi vào nhật ký')}
              badge={<span className="flex items-center gap-1">
                {changed && <span className="size-1.5 rounded-full bg-accent" aria-label="Chưa lưu" />}
                {!item.enabled && <Chip tone="neutral" size="xs">Đã tắt</Chip>}
              </span>} />
          )
        })}
      </div>

      <Disclosure summary="Tắt cờ có tác dụng gì, cờ hiện ở đâu?" className="mt-2">
        <ul className="m-0 list-disc space-y-1 pl-4">
          <li>Chỉ số đã tắt không còn làm bật cờ chung và không hiện trong câu cảnh báo. Giá trị ngoài phạm vi của nó <strong className="font-semibold text-fg">vẫn được ghi đầy đủ</strong> trong chẩn đoán và nhật ký, kèm ghi chú “đã tắt”.</li>
          <li>Cờ hiện ở: báo cáo trạm (dòng lệnh), ghi chú kỹ thuật của bảng Streamlit, chẩn đoán trong nhật ký dự báo shadow. Bản đồ chưa hiển thị cờ này.</li>
        </ul>
        <p className="m-0 flex gap-1.5">
          <Info size={13} className="mt-0.5 flex-none text-info" aria-hidden />
          <span>Mô hình ước tính DO theo ngữ cảnh vẫn bỏ kết quả khi đầu vào ngoài phạm vi, kể cả chỉ số đã tắt — nút này không đổi điều đó.</span>
        </p>
      </Disclosure>
    </section>
  )
}
