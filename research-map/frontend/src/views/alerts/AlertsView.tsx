import { BellRing } from 'lucide-react'
import { EmptyState } from '../../components/ui'

/** Placeholder (Wave 0). Track G builds the per-station alert view. */
export default function AlertsView() {
  return <EmptyState icon={<BellRing size={22} />} title="Cảnh báo theo trạm" description="Đang xây dựng (shadow, lý thuyết)." />
}
