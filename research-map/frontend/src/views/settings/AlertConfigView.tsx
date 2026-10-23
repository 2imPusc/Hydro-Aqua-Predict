import { SlidersHorizontal } from 'lucide-react'
import { EmptyState } from '../../components/ui'

/** Placeholder (Wave 0). Track B builds the alert-tier configuration view. */
export default function AlertConfigView() {
  return <EmptyState icon={<SlidersHorizontal size={22} />} title="Cấu hình cảnh báo" description="Đang xây dựng." />
}
