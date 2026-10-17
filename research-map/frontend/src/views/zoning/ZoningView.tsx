import { ResearchPlaceholder } from '../ResearchPlaceholder'

export default function ZoningView() {
  return (
    <ResearchPlaceholder direction="H3" title="H3 · Phân vùng phù hợp"
      planned={[
        'Bản đồ điểm phù hợp với chuyển biến thể (Ghaderi A_W_SUM / nearshore N1_W_SUM)',
        'Chuyển vùng Việt Nam / Hồng Kông, lớp trang trại kiểm chứng',
        'AUC và ghi chú giới hạn',
      ]}
      endpoints={['/suitability?variant=A_W_SUM&region=vn', '/suitability?variant=N1_W_SUM&region=hk']} />
  )
}
