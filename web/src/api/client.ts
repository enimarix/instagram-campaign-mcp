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
  // the detail page (016)
  best_before?: string | null
  duration?: number | null
  recipe?: { template?: string; edit?: string; ops?: { op: string }[] }
  qc?: { passed?: boolean; reason?: string; reasons?: string[]; warnings?: string[] } | null
  // from the asset's idea; only the list carries them
  track?: string
  strategy?: 'explore' | 'exploit' | null
}

export type Vocabulary = { values: { id: string; label: string }[] }
export type Taxonomy = {
  feedback_reasons: Vocabulary
  tracks?: Vocabulary
  pillars?: Vocabulary
  hook_types?: Vocabulary
  templates?: Vocabulary
}

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

export type Comment = {
  id: number
  text: string | null
  reason_codes: string[]
  video_time_s: number | null
  wants_changes: number // 0/1
  created_at: string
}
export type CommentIn = {
  text?: string
  reason_codes: string[]
  video_time_s?: number
  wants_changes?: boolean
}
/** What saving a comment did: `moved` = sent back for a new version, else `reason` says why not. */
export type CommentResult = { feedback: Comment; asset: Asset; moved: boolean; reason: string | null }

export const addFeedback = (id: number, fb: CommentIn) =>
  post<CommentResult>(`/api/assets/${id}/feedback`, fb)

const send = <T>(method: string, path: string, body?: unknown) =>
  request<T>(path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })

export const getAsset = (id: number) => request<Asset>(`/api/assets/${id}`)
export const editAsset = (id: number, fields: { caption?: string; best_before?: string | null }) =>
  send<Asset>('PATCH', `/api/assets/${id}`, fields)
export const unapproveAsset = (id: number) => post<Asset>(`/api/assets/${id}/unapprove`)
export const archiveAsset = (id: number) => post<Asset>(`/api/assets/${id}/archive`)
export const listFeedback = (id: number) => request<Comment[]>(`/api/assets/${id}/feedback`)
export const editFeedback = (id: number, fields: { text: string | null }) =>
  send<CommentResult>('PATCH', `/api/feedback/${id}`, fields)
export const deleteFeedback = (id: number) => request<null>(`/api/feedback/${id}`, { method: 'DELETE' })

export type Citation = { title?: string; url?: string }
/** GET /api/assets/{id}/context: the idea, its rights source and the version chain. */
export type AssetContext = {
  idea: {
    track: string
    pillar: string | null
    hook: string | null
    hook_type: string | null
    hypothesis: string | null
    strategy: 'explore' | 'exploit' | null
    citations: Citation[]
  }
  source: { rights_basis: string; author: string | null; url: string | null } | null
  parent: Asset | null
  children: Asset[]
}
export const getAssetContext = (id: number) => request<AssetContext>(`/api/assets/${id}/context`)

/** The server's own words for a refused request (`message`), else the error itself. */
export function errorMessage(e: unknown): string {
  if (e instanceof ApiError && e.body && typeof e.body === 'object' && 'message' in e.body)
    return String(e.body.message)
  return e instanceof Error ? e.message : String(e)
}

/** A publish slot: `publish_at` in UTC, `local` in the owner's time zone (both ISO). */
export type Slot = { publish_at: string; local: string }
/** GET /api/assets/{id}/proposed-slot; `needs_confirmation`: a commentary clip (GOAL §5.1). */
export type ProposedSlot = Slot & { needs_confirmation: boolean }
export const getProposedSlot = (id: number) => request<ProposedSlot>(`/api/assets/${id}/proposed-slot`)
/** Where a scheduled asset sits in the queue (404 when it has no pending slot). */
export const getSlot = (id: number) => request<Slot & { post_id: number }>(`/api/assets/${id}/slot`)
export const scheduleAsset = (id: number, publish_at: string, confirmed: boolean) =>
  post<{ asset: Asset }>(`/api/assets/${id}/schedule`, { publish_at, confirmed })
export const unscheduleAsset = (id: number) => post<Asset>(`/api/assets/${id}/unschedule`)

/** GET /api/bench: liked videos from every batch still waiting for approval, freshest
 * best-before first; `suggestion` = the freshest one for a free slot within 24 h. */
export type Bench = {
  assets: Asset[]
  supply_days: number
  max_posts_per_day: number
  suggestion: (Slot & { asset_id: number }) | null
}
export const getBench = () => request<Bench>('/api/bench')

/** A publish-queue row on the calendar (src/studio/calendar.py); `local`: owner's time zone. */
export type CalendarPost = Slot & {
  id: number
  kind: string
  status: 'pending' | 'publishing' | 'published' | 'failed' | 'cancelled'
  attempts: number
  caption: string
  asset_id: number | null
  preview_url: string | null
  permalink: string | null
  error: string | null
  replanned: boolean // moved by the worker: it would have gone out late
}
/** GET /api/calendar: every owner-local day of the range, and the publish_check videos. */
export type Calendar = { days: { date: string; posts: CalendarPost[] }[]; publish_check: Asset[] }
export const getCalendar = (from: string, to: string) =>
  request<Calendar>(`/api/calendar?${new URLSearchParams({ from, to })}`)
/** The raw queue row the post actions answer with (the page reloads the calendar). */
type QueueRow = { id: number; status: string; publish_at: string }
export const reschedulePost = (id: number, publish_at: string) =>
  post<QueueRow>(`/api/posts/${id}/reschedule`, { publish_at })
export const cancelPost = (id: number) => post<QueueRow>(`/api/posts/${id}/cancel`)
export const replanPost = (id: number, confirmed = false) =>
  post<QueueRow>(`/api/posts/${id}/replan`, { confirmed })
export const releaseAsset = (id: number) => post<Asset>(`/api/assets/${id}/release`)

/** What the worker's last pass did (campaign.run_due), or `error` when it crashed. */
export type RunResult = {
  error?: string
  paused?: boolean
  published?: unknown[]
  failed?: unknown[]
  retrying?: unknown[]
  replanned?: unknown[]
}
/** GET /api/worker/status (src/worker.py); times ISO UTC. */
export type WorkerStatus = {
  heartbeat_at: string | null
  alive: boolean
  paused: boolean
  next_slot: string | null
  last_result: RunResult | null
}
export const getWorkerStatus = () => request<WorkerStatus>('/api/worker/status')
export const setPublishingPaused = (paused: boolean) =>
  post<WorkerStatus>(`/api/worker/${paused ? 'pause' : 'resume'}`)

/** GET /api/storage (src/studio/storage.py): sizes in bytes; `free_bytes` of the media disk. */
export type Storage = { media_bytes: number; db_bytes: number; free_bytes: number; last_backup: string | null }
export const getStorage = () => request<Storage>('/api/storage')

/** GET /api/token. `valid`/`expires_at` null = unknown; valid with no expires_at = never expires. */
export type TokenStatus = {
  configured: boolean
  valid: boolean | null
  expires_at: string | null
  days_left: number | null
  can_refresh: boolean
  scopes: string[]
}
export const getToken = () => request<TokenStatus>('/api/token')

/** A row of GET /api/agent/runs (src/agent/runs.py), newest first; times ISO UTC. */
export type AgentRun = {
  id: number
  playbook: string
  status: 'running' | 'succeeded' | 'failed' | 'cancelled'
  started_at: string
  finished_at: string | null
  summary: string | null
  duration_s: number
  num_turns: number | null
  cost_usd: number | null
  permission_denials: number | null
  has_log: boolean
}
export const getPlaybooks = () => request<string[]>('/api/agent/playbooks')
export const getAgentRuns = (limit = 50) => request<AgentRun[]>(`/api/agent/runs?limit=${limit}`)
export const getAgentLog = (id: number) => request<{ id: number; lines: string[] }>(`/api/agent/runs/${id}/log`)
/** Starts `ig-campaign agent run` detached; 409 already_running, 404 unknown_playbook. */
export const startAgentRun = (playbook: string) =>
  post<{ started: boolean; playbook: string }>('/api/agent/runs', { playbook })
