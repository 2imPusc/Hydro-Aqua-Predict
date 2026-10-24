import { useEffect, useState } from 'react'

export type ViewId = 'monitor' | 'alerts' | 'forecast' | 'weather' | 'zoning' | 'reliability' | 'settings'
export type ReliabilityTab = 'vn' | 'foreign'
export type Route = { view: ViewId; params: { tab?: ReliabilityTab; datasetId?: string } }

export const NAV: Array<{ view: ViewId; hash: string; label: string; short: string; code?: string; description: string }> = [
  { view: 'monitor', hash: '#/monitor', label: 'Bản đồ giám sát', short: 'Bản đồ', description: 'Bản đồ context môi trường, cảm biến và khuyến nghị nuôi trồng' },
  { view: 'alerts', hash: '#/alerts', label: 'Cảnh báo theo trạm', short: 'Cảnh báo', description: 'Cấp cảnh báo shadow theo từng điểm nuôi (lý thuyết)' },
  { view: 'forecast', hash: '#/forecast', label: 'H1 · Dự báo ngắn hạn', short: 'Dự báo', code: 'H1', description: 'Dự báo shadow theo biến/horizon và benchmark' },
  { view: 'weather', hash: '#/weather', label: 'H2 · Thời tiết & khuyến nghị', short: 'Thời tiết', code: 'H2', description: 'Độ phủ snapshot thời tiết (chỉ quan sát)' },
  { view: 'zoning', hash: '#/zoning', label: 'H3 · Phân vùng phù hợp', short: 'Phân vùng', code: 'H3', description: 'Bản đồ phù hợp nuôi trồng (VN / HK)' },
  { view: 'reliability', hash: '#/reliability', label: 'H4 · Độ tin cậy không gian', short: 'Độ tin cậy', code: 'H4', description: 'Độ tin cậy ngoại suy trạm, kiểm chứng nước ngoài' },
  { view: 'settings', hash: '#/settings/alerts', label: 'Cấu hình cảnh báo', short: 'Cấu hình', description: 'Chỉnh ngưỡng và hành động của các bậc cảnh báo (shadow)' },
]

/** Research pages grouped under one "Phân tích" entry (tabs inside); deep links keep their own hashes. */
export const ANALYSIS_VIEWS: ViewId[] = ['forecast', 'weather', 'zoning', 'reliability']
export type MainNavItem = { key: 'monitor' | 'alerts' | 'analysis' | 'settings'; hash: string; label: string; short: string; description: string; views: ViewId[] }
/** Four top-level entries (rail on desktop, bottom bar on phones). */
export const MAIN_NAV: MainNavItem[] = [
  { key: 'monitor', hash: '#/monitor', label: 'Bản đồ giám sát', short: 'Bản đồ', description: 'Bản đồ vùng nuôi: độ tin cậy, trạng thái nuôi, thời tiết & biển, độ sâu', views: ['monitor'] },
  { key: 'alerts', hash: '#/alerts', label: 'Cảnh báo theo trạm', short: 'Cảnh báo', description: 'Bậc cảnh báo 5 ngày tới của từng điểm nuôi (shadow)', views: ['alerts'] },
  { key: 'analysis', hash: '#/forecast', label: 'Phân tích', short: 'Phân tích', description: 'Dự báo, thời tiết, phân vùng, độ tin cậy (nghiên cứu)', views: ANALYSIS_VIEWS },
  { key: 'settings', hash: '#/settings/alerts', label: 'Cấu hình cảnh báo', short: 'Cấu hình', description: 'Chỉnh ngưỡng và hành động của các bậc cảnh báo', views: ['settings'] },
]

/** Parses `#/monitor`, `#/forecast`, …, `#/reliability` (VN tab), `#/reliability/foreign`, `#/reliability/foreign/<id>`; unknown hashes fall back to monitor. */
export function parseHash(hash: string): Route {
  const parts = hash.replace(/^#\/?/, '').split('/').filter(Boolean).map(decodeURIComponent)
  const head = parts[0] as ViewId | undefined
  if (head === 'reliability') return { view: 'reliability', params: parts[1] === 'foreign' ? { tab: 'foreign', datasetId: parts[2] || undefined } : { tab: 'vn' } }
  if (head === 'settings') return { view: 'settings', params: {} }
  if (head && NAV.some(item => item.view === head)) return { view: head, params: {} }
  return { view: 'monitor', params: {} }
}

export const foreignDatasetHash = (id: string) => `#/reliability/foreign/${encodeURIComponent(id)}`
export const RELIABILITY_HASH: Record<ReliabilityTab, string> = { vn: '#/reliability', foreign: '#/reliability/foreign' }

export function useHashRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parseHash(window.location.hash))
  useEffect(() => {
    const onChange = () => setRoute(parseHash(window.location.hash))
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  return route
}
