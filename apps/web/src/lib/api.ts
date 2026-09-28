/** SkillForge HTTP API client. Base URL from Vite env or local default. */

export const API_BASE =
  import.meta.env.VITE_API_BASE?.replace(/\/$/, '') || 'http://127.0.0.1:8000'

/** Derive the TraceEvent WebSocket URL from the HTTP API base. */
export function eventsWebSocketUrl(apiBase: string = API_BASE): string {
  const url = new URL(apiBase)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  url.pathname = '/api/events'
  url.search = ''
  url.hash = ''
  return url.toString()
}

export class ApiError extends Error {
  readonly status: number
  readonly body: string

  constructor(status: number, body: string) {
    super(`API ${status}: ${body}`)
    this.name = 'ApiError'
    this.status = status
    this.body = body
  }
}

function resolveUrl(path: string): string {
  return path.startsWith('http')
    ? path
    : `${API_BASE}${path.startsWith('/') ? path : `/${path}`}`
}

/** Build headers; never force JSON Content-Type onto FormData (browser sets multipart boundary). */
export function buildApiHeaders(init?: RequestInit): Headers {
  const headers = new Headers(init?.headers)
  if (!headers.has('Accept')) {
    headers.set('Accept', 'application/json')
  }
  const body = init?.body
  const isFormData = typeof FormData !== 'undefined' && body instanceof FormData
  if (body && !isFormData && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  return headers
}

export type ApiSuccess<T> = { ok: true; status: number; data: T }
export type ApiFailure = { ok: false; status: number; body: string }
export type ApiResult<T> = ApiSuccess<T> | ApiFailure

/** Low-level request that always returns HTTP status (success or failure). */
export async function apiRequest<T>(
  path: string,
  init?: RequestInit,
): Promise<ApiResult<T>> {
  const response = await fetch(resolveUrl(path), {
    ...init,
    headers: buildApiHeaders(init),
  })
  if (!response.ok) {
    return { ok: false, status: response.status, body: await response.text() }
  }
  if (response.status === 204) {
    return { ok: true, status: response.status, data: undefined as T }
  }
  return {
    ok: true,
    status: response.status,
    data: (await response.json()) as T,
  }
}

export async function apiFetch<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const result = await apiRequest<T>(path, init)
  if (!result.ok) {
    throw new ApiError(result.status, result.body)
  }
  return result.data
}

/** Multipart upload helper — omits JSON Content-Type so the browser sets the boundary. */
export async function apiUploadForm<T>(
  path: string,
  formData: FormData,
  init?: Omit<RequestInit, 'body'>,
): Promise<T> {
  return apiFetch<T>(path, { ...init, method: init?.method ?? 'POST', body: formData })
}
