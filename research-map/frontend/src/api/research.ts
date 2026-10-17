import { ApiError, getJson } from './client'
import type { ForecastBenchmark, ForeignDetail, ForeignIndex, ForeignQuery, LongForecast, ReliabilityVn, ResearchEnvelope, ResearchOverview, Suitability, SuitabilityRegion, SuitabilityVariant, WeatherStatus } from '../types/research'

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

/** Human-readable reasons for `unavailable` research envelopes. */
export const RESEARCH_REASON: Record<string, string> = {
  research_api_missing: 'Backend chưa có research router (/api/v1/research).',
  no_export: 'Chưa có bản export nghiên cứu (artifacts/research-map/).',
  a6_not_exported: 'Lớp regime độ mặn VN (A6) chưa được export.',
}
export const researchReason = (reason?: string) => (reason ? RESEARCH_REASON[reason] ?? reason : 'Không rõ lý do.')
