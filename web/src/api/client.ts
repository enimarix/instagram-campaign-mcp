// Typed client for the FastAPI server (src/api/app.py). Same-origin: the Vite
// dev proxy forwards /api in development; FastAPI serves the build later.

export type Health = {
  status: string
  instagram_configured: boolean
  version: string
}

export type Account = {
  token_valid: boolean
  // ponytail: Graph payloads left loose until a page actually renders them
  profile: Record<string, unknown> | null
  publishing_limit: Record<string, unknown> | null
}

/** A non-2xx answer; `code` is the server's `error` field (e.g. "instagram_not_configured"). */
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly body: unknown

  constructor(status: number, code: string, body: unknown) {
    super(`API ${status}: ${code}`)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.body = body
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    credentials: 'same-origin', // session cookie (step 008)
    ...init,
    headers: { Accept: 'application/json', ...init?.headers },
  })
  const body: unknown = await res.json().catch(() => null)
  if (!res.ok) {
    const code =
      body && typeof body === 'object' && 'error' in body && typeof body.error === 'string'
        ? body.error
        : 'http_error'
    throw new ApiError(res.status, code, body)
  }
  return body as T
}

export const getHealth = () => request<Health>('/api/health')
export const getAccount = () => request<Account>('/api/account')

export type Verdict = 'none' | 'liked' | 'disliked'

/** A row of GET /api/assets (src/api/assets.py); only the fields the website reads. */
export type Asset = {
  id: number
  status: string
  verdict: Verdict
  self_score: number | null
  self_score_reason: string | null
  caption: string | null
  batch_date: string
  preview_url: string | null
  thumbnail_url: string | null
  // from the asset's idea; only the list carries them
  track?: string
  strategy?: 'explore' | 'exploit' | null
}

export type Vocabulary = { values: { id: string; label: string }[] }
export type Taxonomy = { feedback_reasons: Vocabulary; tracks?: Vocabulary }

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, {
    method: 'POST',
    ...(body !== undefined && {
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  })

export const listAssets = (query: Record<string, string>) =>
  request<Asset[]>(`/api/assets?${new URLSearchParams(query)}`)
export const setVerdict = (id: number, verdict: Verdict) =>
  post<Asset>(`/api/assets/${id}/verdict`, { verdict })
export const approveAsset = (id: number) => post<Asset>(`/api/assets/${id}/approve`)
export const getTaxonomy = () => request<Taxonomy>('/api/taxonomy')
export const addFeedback = (id: number, fb: { text?: string; reason_codes: string[] }) =>
  post<unknown>(`/api/assets/${id}/feedback`, fb)
