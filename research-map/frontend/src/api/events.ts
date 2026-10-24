/** Field event log client. No auth yet (same stage as the alert-config admin). */
import { API_BASE, ApiError, getJson, isAbortError } from './client'
import type { EventCreated, EventInvalid, EventRejected, FieldEventInput, FieldEventList } from '../types/events'

export type EventFilters = { station?: string; event_type?: string; from?: string; to?: string }

const query = (filters: EventFilters) => {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(filters)) if (value) params.set(key, value)
  const text = params.toString()
  return text ? `?${text}` : ''
}

export const listEvents = (filters: EventFilters = {}, signal?: AbortSignal) => getJson<FieldEventList>(`/events${query(filters)}`, signal)

/** Plain link target: the server answers with `Content-Disposition: attachment`, so a cross-origin download works. */
export const eventsCsvUrl = (filters: EventFilters = {}) => `${API_BASE}/events/export.csv${query(filters)}`

/**
 * POST one event. 422 (validation), 404/409 (correction target missing / already corrected) and
 * 503 (not writable, station registry missing) carry a JSON reason and are returned, not thrown.
 */
export async function createEvent(body: FieldEventInput): Promise<EventCreated | EventInvalid | EventRejected> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}/events`, {
      method: 'POST',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  } catch (error) {
    if (isAbortError(error)) throw error
    throw new ApiError('api_unreachable', 0)
  }
  const payload = await response.json().catch(() => null) as Record<string, unknown> | null
  if (response.status === 422) {
    const errors = Array.isArray(payload?.errors) ? payload.errors.map(String) : ['Dữ liệu không hợp lệ (422)']
    return { status: 'invalid', errors }
  }
  if (response.status === 413) return { status: 'invalid', errors: ['body: too large'] }
  if ([404, 409, 503].includes(response.status) && typeof payload?.reason === 'string') {
    return { status: response.status === 503 ? 'unavailable' : 'conflict', reason: payload.reason }
  }
  if (!response.ok || !payload) throw new ApiError(`api_${response.status}`, response.status)
  return payload as EventCreated
}
