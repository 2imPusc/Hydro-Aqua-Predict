import { ResearchPlaceholder } from '../ResearchPlaceholder'

export default function ForecastView() {
  return (
    <ResearchPlaceholder direction="H1" title="H1 · Dự báo ngắn hạn"
      planned={[
        'Thẻ dự báo shadow theo biến / horizon (có và không có pH), dải PI80/PI90',
        'Bundle pH đã rút (withdrawn) kèm lý do; lý do bỏ qua (skip)',
        'Benchmark gate #16: skill so với persistence, số fold thắng, DM p',
        'Độ phủ conformal (v3, aci_amp)',
      ]}
      endpoints={['/forecast/long?station=06M26042804', '/forecast/benchmark']} />
  )
}
