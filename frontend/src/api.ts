// Provide typed, cancellable calls to every current gateway endpoint.
import type {
  ChatCompletion, ChatMessage, Feedback, Health, Page, RequestDetail,
  RequestFilters, RequestSummary, RunMode, RuntimeSettings, Stats, Suite,
  TestLabResult, TestLabRun, Tier, TrainingResult, TrainingStatus,
} from './types'

export class ApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

function errorMessage(payload: unknown, status: number): string {
  if (payload && typeof payload === 'object' && 'detail' in payload) {
    const detail = payload.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      return detail.map((entry: unknown) => (
        entry && typeof entry === 'object' && 'msg' in entry ? String(entry.msg) : ''
      )).filter(Boolean).join('; ') || `Request failed (${status}).`
    }
  }
  return `Request failed (${status}).`
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  headers.set('Accept', 'application/json')
  headers.set('X-SmartRoute-Source', 'playground')
  if (options.body) headers.set('Content-Type', 'application/json')
  let response: Response
  try {
    response = await fetch(path, { ...options, headers })
  } catch (error) {
    if (options.signal?.aborted) throw error
    throw new ApiError('Cannot reach the gateway. Check the backend connection.', 0)
  }
  let payload: unknown
  try {
    payload = await response.json()
  } catch {
    throw new ApiError('The gateway returned an unreadable response.', response.status)
  }
  if (!response.ok) throw new ApiError(errorMessage(payload, response.status), response.status)
  return payload as T
}

function query(values: Record<string, string | number | boolean | undefined>): string {
  const parameters = new URLSearchParams()
  for (const [name, value] of Object.entries(values)) {
    if (value !== undefined && value !== '') parameters.set(name, String(value))
  }
  return parameters.toString()
}

export const api = {
  health: (signal?: AbortSignal) => request<Health>('/health', { signal }),
  tiers: (signal?: AbortSignal) => request<Tier[]>('/v1/tiers', { signal }),
  chat: (messages: ChatMessage[], mode: RunMode, signal?: AbortSignal) => (
    request<ChatCompletion>('/v1/chat/completions', {
      method: 'POST', signal,
      body: JSON.stringify({ model: `smartroute/${mode}`, messages, temperature: 0.2, max_tokens: 1024, stream: false }),
    })
  ),
  feedback: (requestId: string, score: 1 | -1, note?: string, signal?: AbortSignal) => (
    request<Feedback>('/v1/feedback', {
      method: 'POST', signal, body: JSON.stringify({ request_id: requestId, score, note: note || null }),
    })
  ),
  stats: (days = 7, signal?: AbortSignal) => request<Stats>(`/v1/stats?${query({ days })}`, { signal }),
  requests: (filters: RequestFilters = {}, signal?: AbortSignal) => (
    request<Page<RequestSummary>>(`/v1/requests?${query({ ...filters })}`, { signal })
  ),
  request: (id: string, signal?: AbortSignal) => (
    request<RequestDetail>(`/v1/requests/${encodeURIComponent(id)}`, { signal })
  ),
  settings: (signal?: AbortSignal) => request<RuntimeSettings>('/v1/settings', { signal }),
  updateSettings: (values: Partial<RuntimeSettings>, signal?: AbortSignal) => (
    request<RuntimeSettings>('/v1/settings', { method: 'PUT', signal, body: JSON.stringify(values) })
  ),
  train: (signal?: AbortSignal) => request<TrainingResult>('/v1/train', { method: 'POST', signal }),
  trainingStatus: (signal?: AbortSignal) => request<TrainingStatus>('/v1/train/status', { signal }),
  suites: (signal?: AbortSignal) => request<Suite[]>('/v1/testlab/suites', { signal }),
  runSuite: (mode: RunMode, limit?: number, signal?: AbortSignal) => (
    request<TestLabResult>('/v1/testlab/run', {
      method: 'POST', signal, body: JSON.stringify({ suite: 'default', mode, limit }),
    })
  ),
  runs: (limit = 50, offset = 0, signal?: AbortSignal) => (
    request<Page<TestLabRun>>(`/v1/testlab/runs?${query({ limit, offset })}`, { signal })
  ),
}