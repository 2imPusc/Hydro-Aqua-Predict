/** Alert-config admin client (Track B). No auth yet: owner decision 2026-10-23. Contract: phase1-parallel C3. */
import { API_BASE, ApiError, getJson, isAbortError } from './client'
import type {
  AlertConfig, AlertConfigInvalid, AlertConfigPreview, AlertConfigResponse, AlertConfigSaved,
  AlertConfigVersionResponse, AlertConfigVersionsResponse,
} from '../types/alerts'

type Signal = AbortSignal | undefined

export const getAlertConfig = (signal?: Signal) => getJson<AlertConfigResponse>('/admin/alert-config', signal)
export const getAlertConfigVersions = (signal?: Signal) => getJson<AlertConfigVersionsResponse>('/admin/alert-config/versions', signal)
export const getAlertConfigVersion = (version: string, signal?: Signal) =>
  getJson<AlertConfigVersionResponse>(`/admin/alert-config/versions/${encodeURIComponent(version)}`, signal)

/**
 * POST JSON. A 422 is a normal answer here (server-side validation), so its
 * `{status: "invalid", errors}` body is returned instead of thrown.
 */
async function postJson<T>(path: string, body: unknown, signal?: Signal): Promise<T | AlertConfigInvalid> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method: 'POST', signal,
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  } catch (error) {
    if (isAbortError(error)) throw error
    throw new ApiError('api_unreachable', 0)
  }
  if (response.status === 422) {
    const payload = await response.json().catch(() => null) as { errors?: unknown; detail?: unknown } | null
    const errors = Array.isArray(payload?.errors) ? payload.errors.map(String) : ['Dữ liệu không hợp lệ (422)']
    return { status: 'invalid', errors }
  }
  if (!response.ok) throw new ApiError(`api_${response.status}`, response.status)
  return response.json() as Promise<T>
}

export const previewAlertConfig = (config: AlertConfig, signal?: Signal) =>
  postJson<AlertConfigPreview>('/admin/alert-config/preview', { config }, signal)

export const saveAlertConfig = (config: AlertConfig, reasonVi: string, changedBy?: string) =>
  postJson<AlertConfigSaved>('/admin/alert-config', { config, reason_vi: reasonVi, ...(changedBy ? { changed_by: changedBy } : {}) })

export const isInvalid = (value: unknown): value is AlertConfigInvalid =>
  typeof value === 'object' && value !== null && (value as { status?: string }).status === 'invalid'
