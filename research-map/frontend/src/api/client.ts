/// <reference types="vite/client" />

export const API_BASE: string = import.meta.env.VITE_CONTEXT_API_URL || 'http://localhost:8010/api/v1'

/** HTTP or network failure; `status` is 0 when the backend could not be reached. */
export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message)
    this.name = 'ApiError'
  }
}

export async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, { signal, headers: { Accept: 'application/json' } })
  } catch (error) {
    if (isAbortError(error)) throw error
    throw new ApiError('api_unreachable', 0)
  }
  if (!response.ok) throw new ApiError(`api_${response.status}`, response.status)
  return response.json() as Promise<T>
}

export function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError'
}

export function describeApiError(error: string | null | undefined): string {
  if (!error) return ''
  if (error === 'api_unreachable') return 'Không kết nối được backend'
  if (error === 'api_404') return 'Endpoint chưa có trên backend (404)'
  if (error.startsWith('api_5')) return `Backend lỗi (${error.slice(4)})`
  return error
}
