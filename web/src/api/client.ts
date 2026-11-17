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
/** A row of GET /api/agent/schedule (src/agent/schedule.py overview). */
export type AgentScheduleEntry = {
  playbook: string
  time: string
  next_at: string
  exists: boolean
  last_run: Pick<AgentRun, 'id' | 'status' | 'started_at' | 'finished_at'> | null
}
export const getAgentSchedule = () => request<AgentScheduleEntry[]>('/api/agent/schedule')
export const getPlaybooks = () => request<string[]>('/api/agent/playbooks')
export const getAgentRuns = (limit = 50) => request<AgentRun[]>(`/api/agent/runs?limit=${limit}`)
export const getAgentLog = (id: number) => request<{ id: number; lines: string[] }>(`/api/agent/runs/${id}/log`)
/** Starts `ig-campaign agent run` detached; 409 already_running, 404 unknown_playbook. */
export const startAgentRun = (playbook: string) =>
  post<{ started: boolean; playbook: string }>('/api/agent/runs', { playbook })

/** A row of GET /api/watchlist (step 051): value is normalised (lowercase, no #/@). */
export type Watch = { id: number; kind: 'hashtag' | 'account'; value: string; note: string | null }
export const listWatchlist = () => request<Watch[]>('/api/watchlist')
export const addWatch = (kind: Watch['kind'], value: string) => post<Watch>('/api/watchlist', { kind, value })
export const removeWatch = (id: number) => request<null>(`/api/watchlist/${id}`, { method: 'DELETE' })

/** A row of GET /api/inspirations (step 051b): url is the canonical Reel / post link. */
export type Inspiration = {
  id: number
  url: string
  note: string | null
  status: 'new' | 'used' | 'dismissed'
  created_at: string
  used_at: string | null
}
export const listInspirations = () => request<Inspiration[]>('/api/inspirations')
export const addInspiration = (url: string, note: string) =>
  post<Inspiration>('/api/inspirations', { url, note: note || null })
export const setInspirationStatus = (id: number, status: Inspiration['status']) =>
  send<Inspiration>('PATCH', `/api/inspirations/${id}`, { status })
export const deleteInspiration = (id: number) => request<null>(`/api/inspirations/${id}`, { method: 'DELETE' })

/** A post of GET /api/trends (src/studio/research.py trend_report). Quotes are other people's words. */
export type TrendItem = {
  source_id: number
  ranked_within: 'account' | 'hashtag'
  account?: string
  hashtag?: string
  url: string | null
  posted_at: string
  hour: number
  duration_s: number | null
  outlier: number | null
  metric: 'views' | 'likes' | null
  median: number | null
  outlier_note: string | null
  hook_quote: string | null
  hashtags: string[]
}
export type TrendReport = { accounts: TrendItem[]; hashtags: Record<string, TrendItem[]>; generated_at: string }
export const getTrends = (days = 14) => request<TrendReport>(`/api/trends?days=${days}`)

// --- Analytics (steps 074, 077; page 078) ---
type AccountValues = { followers: number | null; reach: number | null; views: number | null }
/** A day of GET /api/analytics/account; `deltas`: change since the previous stored day. */
export type AccountDay = AccountValues & { date: string; deltas: AccountValues }
export const getAccountSeries = (days: number) =>
  request<{ since: string; until: string; days: AccountDay[] }>(`/api/analytics/account?days=${days}`)

/** A row of GET /api/analytics/posts (src/learning/analytics.py posts_table). */
export type AnalyticsPost = {
  media_id: string
  permalink: string | null
  posted_at: string | null
  group: string
  metrics: Record<string, number | null>
  caption: string
  deleted: boolean
  verdict: string // src/scoring.py: winner, promising, average, weak, too_early, ...
  why: string | null
  asset_id: number | null
  thumbnail_url?: string | null // studio posts only (079)
  preview_url?: string | null
  engagement_index?: number | null
  reach_index?: number | null
  watch_ratio?: number | null
  view_rate?: number | null
  tags?: Record<string, string | null> | null
}
export const getAnalyticsPosts = (limit = 100) =>
  request<{ total: number; posts: AnalyticsPost[] }>(`/api/analytics/posts?limit=${limit}`)

/** Stage counts of GET /api/analytics/funnel (src/learning/funnel.py). */
export type FunnelStats = Record<'produced' | 'reviewed' | 'liked' | 'approved' | 'published' | 'winner', number> & {
  like_rate: number | null
  approval_rate: number | null
}
export type Funnel = { since: string; until: string; approval_rate_note: string; totals: FunnelStats }
export const getFunnel = (days = 30) => request<Funnel>(`/api/analytics/funnel?days=${days}`)

/** GET /api/analytics/taste: like-rate series, calibration, waste, feedback reasons. */
export type Taste = {
  like_rate: { date: string; reviewed: number; liked: number; like_rate: number | null; rolling_7d: number | null }[]
  calibration: {
    days: { date: string; scored: number; top_liked: number; top_n: number }[]
    mean_self_score: { liked: number | null; disliked: number | null }
  }
  waste: { count: number; render_minutes: number }
  reasons: { code: string; label: string; count: number }[]
}
export const getTaste = (days = 30) => request<Taste>(`/api/analytics/taste?days=${days}`)

// --- Posts pages (step 079) ---
/** Filters and sort of GET /api/analytics/posts; empty values are left out of the URL. */
export type PostsQuery = { sort: string; type: string; verdict: string; tagged: string; offset: number; limit: number }
export const listAnalyticsPosts = (q: PostsQuery) =>
  request<{ total: number; posts: AnalyticsPost[] }>(`/api/analytics/posts?${new URLSearchParams(
    Object.entries(q).flatMap(([k, v]) => (v === '' ? [] : [[k, String(v)]])))}`)

/** GET /api/analytics/posts/{media_id}: the snapshot series oldest first, plus the studio side. */
export type PostDetail = Omit<AnalyticsPost, 'metrics' | 'verdict' | 'why'> & {
  hypothesis: string | null
  feedback: Comment[]
  series: { captured_at: string; age_hours: number; metrics: Record<string, number | null> }[]
}
export const getAnalyticsPost = (mediaId: string) =>
  request<PostDetail>(`/api/analytics/posts/${encodeURIComponent(mediaId)}`)

// --- Clip intake (step 063; src/api/sources.py) ---
export type RightsBasis = 'own' | 'licensed' | 'public_domain' | 'cc' | 'permission' | 'commentary'
export type AudioRights = 'covered' | 'not_covered' | 'no_audio'
/** A clip of GET /api/sources?role=clip; `attribution`: the credit its posts must carry. */
export type Clip = {
  id: number
  provider: string
  url: string | null
  author: string | null
  rights_basis: RightsBasis
  rights_note: string | null
  audio_rights: AudioRights | null
  stats: { duration_s?: number; original_name?: string }
  licence: string | null
  attribution: string | null
}
/** A file of GET /api/sources/inbox, waiting for its rights. */
export type InboxFile = { name: string; size_bytes: number; modified_at: string }
export type ClipIntake = {
  rights_basis: RightsBasis
  rights_note: string
  audio_rights: AudioRights
  author: string | null
  url: string | null
  licence: string | null
}
export const listClips = () => request<Clip[]>('/api/sources?role=clip')
export const listInbox = () => request<InboxFile[]>('/api/sources/inbox')
export const addInboxClip = (name: string, body: ClipIntake) =>
  post<Clip>(`/api/sources/inbox/${encodeURIComponent(name)}`, body)

// --- Breakdowns and A/B (step 080) ---
type Median = { median: number | null }
/** A group of GET /api/analytics/breakdown (src/learning/breakdowns.py); `watch_ratio` only when known. */
export type BreakdownGroup = {
  tag_value: string | number
  n: number
  small_sample: boolean
  engagement_index: { median: number; p25: number; p75: number } | null
  reach: Median
  views: Median
  watch_ratio?: Median
}
export type Breakdown = { tag: string; post_type: string; days: number; since: string; groups: BreakdownGroup[] }
export const getBreakdown = (tag: string, type: string, days = 90) =>
  request<Breakdown>(`/api/analytics/breakdown?${new URLSearchParams({ tag, type, days: String(days) })}`)

/** GET /api/analytics/ab (scoring.compare_variants): `leader` null while `note` says why. */
export type AbVariant = {
  variant: string
  posts: number
  avg_engagement_index: number
  avg_reach: number
  winners: number
  hypothesis: string | null
}
export type AbResult = { campaign: string; variants: AbVariant[]; leader: string | null; note: string | null }
export const getCampaigns = () => request<string[]>('/api/analytics/campaigns')
export const getAb = (campaign: string) =>
  request<AbResult>(`/api/analytics/ab?campaign=${encodeURIComponent(campaign)}`)
