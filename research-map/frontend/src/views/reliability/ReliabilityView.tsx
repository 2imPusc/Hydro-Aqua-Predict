import { Chip } from '../../components/ui'
import { ResearchPlaceholder } from '../ResearchPlaceholder'

export default function ReliabilityView({ datasetId }: { datasetId?: string }) {
  return (
    <ResearchPlaceholder direction="H4" title={datasetId ? `H4 · Bộ dữ liệu nước ngoài “${datasetId}”` : 'H4 · Độ tin cậy không gian'}
      planned={[
        'Tab VN: lớp regime độ mặn (A6) hoặc trạng thái không khả dụng; HSI legacy “chưa kiểm chứng”',
        'Tab nước ngoài: thẻ bộ dữ liệu (HK EPD, NOAA NERRS, USGS, TWDB, IRLON/HBOI-FAU, Maryland DNR) kèm giấy phép & ghi công',
        'Bản đồ cặp trạm theo regime, lọc biến / thang thời gian / transfer, bảng bán kính',
        'Maryland DNR: chỉ thống kê tổng hợp — không phân phối lại dữ liệu thô',
      ]}
      endpoints={datasetId ? [`/reliability/foreign/${datasetId}?var=Temp&scale=hourly&transfer=raw`] : ['/reliability/vn', '/reliability/foreign', '/reliability/foreign/{id}']}>
      {datasetId && <Chip tone="accent">#/reliability/foreign/{datasetId}</Chip>}
    </ResearchPlaceholder>
  )
}
