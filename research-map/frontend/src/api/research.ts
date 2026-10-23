import { ApiError, getJson } from './client'
import type { ApiStatus, ForecastBenchmark, ForeignDetail, ForeignIndex, ForeignQuery, LongForecast, ReliabilitySummary, ReliabilityVn, ResearchEnvelope, ResearchOverview, Suitability, SuitabilityRegion, SuitabilityVariant, WeatherStatus } from '../types/research'

type Signal = AbortSignal | undefined
const q = encodeURIComponent
const BASE = '/research'

/**
 * Research endpoints are read-only views over versioned exports. A 404 means
 * the backend predates the research router; surface it as an explicit
 * `unavailable` envelope instead of throwing, so views show a reason.
 */
async function research<T extends ResearchEnvelope>(path: string, signal?: Signal): Promise<T> {
  try {
    return await getJson<T>(`${BASE}${path}`, signal)
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return { status: 'unavailable', export_version: null, reason: 'research_api_missing' } as T
    throw error
  }
}

const query = (params: Record<string, string | undefined>) => {
  const entries = Object.entries(params).filter(([, value]) => value !== undefined && value !== '') as Array<[string, string]>
  return entries.length ? `?${entries.map(([key, value]) => `${q(key)}=${q(value)}`).join('&')}` : ''
}

export const getResearchOverview = (signal?: Signal) => research<ResearchOverview>('/overview', signal)
export const getLongForecast = (station: string, signal?: Signal) => research<LongForecast>(`/forecast/long${query({ station })}`, signal)
export const getForecastBenchmark = (signal?: Signal) => research<ForecastBenchmark>('/forecast/benchmark', signal)
export const getWeatherStatus = (station: string, signal?: Signal) => research<WeatherStatus>(`/weather/status${query({ station })}`, signal)
export const getSuitability = (variant: SuitabilityVariant, region: SuitabilityRegion, signal?: Signal) => research<Suitability>(`/suitability${query({ variant, region })}`, signal)
export const getForeignIndex = (signal?: Signal) => research<ForeignIndex>('/reliability/foreign', signal)
export const getForeignDetail = (id: string, params: ForeignQuery = {}, signal?: Signal) => research<ForeignDetail>(`/reliability/foreign/${q(id)}${query({ var: params.var, scale: params.scale, transfer: params.transfer })}`, signal)
export const getReliabilityVn = (signal?: Signal) => research<ReliabilityVn>('/reliability/vn', signal)
export const getReliabilitySummary = (signal?: Signal) => research<ReliabilitySummary>('/reliability/summary', signal)
/** Light shell status (snapshot + sensor freshness, export version); not a research envelope. */
export const getApiStatus = (station: string, signal?: Signal) => getJson<ApiStatus>(`/status${query({ station })}`, signal)

/** Human-readable reasons for `unavailable` research envelopes. */
export const RESEARCH_REASON: Record<string, string> = {
  research_api_missing: 'Backend chưa có research router (/api/v1/research).',
  no_export: 'Chưa có bản export nghiên cứu (artifacts/research-map/).',
  research_export_missing: 'Chưa có bản export nghiên cứu (artifacts/research-map/).',
  artifact_not_in_export: 'Bản export mới nhất không chứa mục này.',
  run_dir_missing: 'Thư mục run nghiên cứu chưa có: chưa chạy hoặc chưa export.',
  a6_not_exported: 'Lớp chế độ mặn VN (A6) chưa được export.',
  ledger_missing: 'Sổ ghi shadow dài hạn (runtime/forecast-shadow/long_*.jsonl) chưa tồn tại: runner chưa phát hành bản dự báo dài hạn nào.',
  snapshot_file_missing: 'Chưa có file snapshot thời tiết.',
  no_records_for_station: 'File snapshot không có bản ghi cho trạm này.',
  stale_last_capture: 'Lần thu gần nhất đã quá 2 giờ.',
  coverage_below_min: 'Độ phủ 7 ngày dưới ngưỡng tối thiểu.',
  database_unavailable: 'Không kết nối được Postgres của research-map.',
  no_context_snapshot: 'Chưa có snapshot context nào.',
  sensor_observations_missing: 'Chưa có quan trắc cảm biến.',
}
export const researchReason = (reason?: string | null) => (reason ? RESEARCH_REASON[reason] ?? reason : 'Không rõ lý do.')
