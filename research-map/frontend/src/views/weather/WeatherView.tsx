import { ResearchPlaceholder } from '../ResearchPlaceholder'

export default function WeatherView() {
  return (
    <ResearchPlaceholder direction="H2" title="H2 · Thời tiết & khuyến nghị"
      planned={[
        'Dải phủ snapshot thời tiết 7 ngày × 24 giờ',
        'Trạng thái healthy / degraded (độ phủ 7 ngày < 90%)',
        'Ghi chú: thời tiết chỉ để quan sát, không kích hoạt cảnh báo',
      ]}
      endpoints={['/weather/status?station=06M26042804']} />
  )
}
