import { BookOpen } from 'lucide-react'
import { Chip } from '../../components/ui'

/** Every hazard figure carries this: theory track, never checked against field outcomes. */
export function TheoryChip() {
  return <Chip size="xs" tone="neutral" icon={<BookOpen size={11} aria-hidden />} title="Tính từ dữ liệu tái phân tích / lịch sử theo lý thuyết; chưa đối chiếu với thiệt hại thực tế tại lồng. Không kích hoạt cảnh báo.">Lý thuyết · chưa kiểm chứng hiện trường</Chip>
}
