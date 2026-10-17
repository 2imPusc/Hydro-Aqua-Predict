import { useEffect, useState } from 'react'

export type ViewId = 'monitor' | 'forecast' | 'weather' | 'zoning' | 'reliability'
export type Route = { view: ViewId; params: { datasetId?: string } }

export const NAV: Array<{ view: ViewId; hash: string; label: string; short: string; code?: string; description: string }> = [
  { view: 'monitor', hash: '#/monitor', label: 'Giám sát vùng biển', short: 'Giám sát', description: 'Bản đồ context môi trường, cảm biến và khuyến nghị nuôi trồng' },
  { view: 'forecast', hash: '#/forecast', label: 'H1 · Dự báo ngắn hạn', short: 'Dự báo', code: 'H1', description: 'Dự báo shadow theo biến/horizon và benchmark' },
  { view: 'weather', hash: '#/weather', label: 'H2 · Thời tiết & khuyến nghị', short: 'Thời tiết', code: 'H2', description: 'Độ phủ snapshot thời tiết (chỉ quan sát)' },
  { view: 'zoning', hash: '#/zoning', label: 'H3 · Phân vùng phù hợp', short: 'Phân vùng', code: 'H3', description: 'Bản đồ phù hợp nuôi trồng (VN / HK)' },
  { view: 'reliability', hash: '#/reliability', label: 'H4 · Độ tin cậy không gian', short: 'Độ tin cậy', code: 'H4', description: 'Độ tin cậy ngoại suy trạm, kiểm chứng nước ngoài' },
]

/** Parses `#/monitor`, `#/forecast`, …, `#/reliability/foreign/<id>`; unknown hashes fall back to monitor. */
export function parseHash(hash: string): Route {
  const parts = hash.replace(/^#\/?/, '').split('/').filter(Boolean).map(decodeURIComponent)
  const head = parts[0] as ViewId | undefined
  if (head === 'reliability') return { view: 'reliability', params: parts[1] === 'foreign' && parts[2] ? { datasetId: parts[2] } : {} }
  if (head && NAV.some(item => item.view === head)) return { view: head, params: {} }
  return { view: 'monitor', params: {} }
}

export const foreignDatasetHash = (id: string) => `#/reliability/foreign/${encodeURIComponent(id)}`

export function useHashRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parseHash(window.location.hash))
  useEffect(() => {
    const onChange = () => setRoute(parseHash(window.location.hash))
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  return route
}
