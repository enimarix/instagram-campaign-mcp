// Typed client for the FastAPI server (src/api/app.py). Same-origin: the Vite
// dev proxy forwards /api in development; FastAPI serves the build later.

export type Health = {
  status: string
  instagram_configured: boolean
  version: string
}

/** `configured: false` (setup mode, no token yet) carries nothing else. */
export type Account = {
  configured?: false
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
  poster_url?: string | null
  // the detail page (016)
  best_before?: string | null
  duration?: number | null
  recipe?: { template?: string; edit?: string; ops?: { op: string }[]; inputs?: Record<string, string> }
  qc?: { passed?: boolean; reason?: string; reasons?: string[]; warnings?: string[] } | null
  // what happens in the video (110): 2-3 sentences, and events in seconds (t, d)
  description?: string | null
  timeline?: TimelineEvent[] | null
  // from the asset's idea; only the list carries them
  track?: string
  strategy?: 'explore' | 'exploit' | null
  experiment?: string | null // 'exp:<id>:<variant>' when the idea fills an experiment (086)
  // shown by the feed when a row carries them (list rows: the source's rights and the
  // pinned account that sent it by DM; no pillar yet)
  pillar?: string | null
  rights_basis?: string | null
  dm_pick_sender?: string | null
  // list rows of a revised video: the owner's newest change request on the version it replaces (133)
  change_request?: { text: string | null; reason_codes: string[] } | null
  // list rows: the owner's work order its idea was made for (134; `source` from 136)
  // (`source` is not sent yet: AssetCard falls back to the mode, see orderSource)
  work_order?: { id: number; mode: WorkMode; instruction: string | null; permalink: string | null; source?: 'dm' | 'trend' } | null
}

/** One event; the last may be only {e: "+N more"} when the timeline was cut. */
export type TimelineEvent = { t?: number; d?: number; e: string }

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

export type Session = { authenticated: boolean; password_required: boolean }
export const getSession = () => request<Session>('/api/session')
export const login = (password: string) => post<{ authenticated: true }>('/api/login', { password })

export const listAssets = (query: Record<string, string>) =>
  request<Asset[]>(`/api/assets?${new URLSearchParams(query)}`)
export const setVerdict = (id: number, verdict: Verdict) =>
  post<Asset>(`/api/assets/${id}/verdict`, { verdict })
export const approveAsset = (id: number) => post<Asset>(`/api/assets/${id}/approve`)
/** GET /api/assets/{id}/reaction (072): the reel piece a reaction remix uses, its clip,
 * and the clip's transcript lines in the part used (clip seconds). */
export type ReactionInfo = {
  piece: { id: number; start_s: number; end_s: number; url: string | null }
  reel: { id: number; duration_s: number; created_at: string }
  source: { id: number; author: string | null; url: string | null; rights_basis: string; attribution: string | null }
  trim: { start_s: number; end_s: number }
  transcript: { index: number; start_s: number; end_s: number; text: string }[]
}
export const getReaction = (id: number) => request<ReactionInfo>(`/api/assets/${id}/reaction`)
/** Re-render with the next reel piece (a failed video in place, else a newer version). */
export const nextReactionPiece = (id: number) => post<{ asset: Asset }>(`/api/assets/${id}/next-piece`)
/** Save the corrected transcript lines (same order) and re-render the captions from them. */
export const fixTranscript = (id: number, texts: string[]) =>
  post<{ asset: Asset }>(`/api/assets/${id}/transcript`, { texts })
/** The feed's one-tap Approve: approved and queued into the next free slot; `slot` null =
 * the planner's week is full, approved only. `confirmed`: the commentary confirmation. */
/** A trial Reel's graduation (shown to non-followers first): by hand in the app, or automatic when it performs. */
export type Trial = 'MANUAL' | 'SS_PERFORMANCE'
export const approveAndQueue = (id: number, confirmed: boolean, trial?: Trial) =>
  post<{ asset: Asset; slot: Slot | null }>(`/api/assets/${id}/approve-and-queue`, { confirmed, trial })
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
export const editAsset = (
  id: number,
  fields: { caption?: string; best_before?: string | null; description?: string },
) =>
  send<Asset>('PATCH', `/api/assets/${id}`, fields)
export const unapproveAsset = (id: number) => post<Asset>(`/api/assets/${id}/unapprove`)
export const archiveAsset = (id: number) => post<Asset>(`/api/assets/${id}/archive`)
/** The feed's Decline in one call: disliked + archived + the motive (reasons and/or text,
 * at least one: 422 otherwise). keepalive: it still lands when the feed flushes it as the
 * tab closes. */
export const declineAsset = (id: number, reason_codes: string[], text?: string) =>
  request<Asset>(`/api/assets/${id}/decline`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reason_codes, ...(text && { text }) }),
    keepalive: true,
  })
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
  /** Published with Instagram's AI label (GOAL §5.6). */
  ai_label: boolean
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
/** GET /api/assets/{id}/proposed-slot; `needs_confirmation`: a commentary clip (GOAL §5.1);
 * `ai_label`: published with Instagram's AI label (§5.6). */
export type ProposedSlot = Slot & { needs_confirmation: boolean; ai_label: boolean; trial_eligible: boolean }
export const getProposedSlot = (id: number) => request<ProposedSlot>(`/api/assets/${id}/proposed-slot`)
/** Where a scheduled asset sits in the queue (404 when it has no pending slot). */
export const getSlot = (id: number) => request<Slot & { post_id: number }>(`/api/assets/${id}/slot`)
export const scheduleAsset = (id: number, publish_at: string, confirmed: boolean, trial?: Trial) =>
  post<{ asset: Asset }>(`/api/assets/${id}/schedule`, { publish_at, confirmed, trial })
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

/** GET /api/settings (src/settings_overrides.py): an owner-editable setting and its form.
 * Money is a decimal string. `default` is the .env value. */
export type SettingField = {
  name: string
  section: string
  value: string | number | null | AdPresetValue[]
  default: string | number | null | AdPresetValue[]
  overridden: boolean
  type: 'money' | 'int' | 'float' | 'bool' | 'text' | 'choice' | 'presets'
  choices?: string[]
  ge?: number
  gt?: number
  le?: number
  lt?: number
  max_length?: number
  description: string | null
}
export type EditableSettings = { version: number; fields: SettingField[] }
export const getSettings = () => request<EditableSettings>('/api/settings')
/** `password`: only when a money cap rises (the server answers 400 password_required). */
export const saveSettings = (body: { values?: Record<string, unknown>; reset?: string[]; password?: string }) =>
  send<EditableSettings>('PATCH', '/api/settings', body)

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

// --- Reaction reel (step 071) ---
/** A reel of GET /api/reactions (src/studio/reactions.py reel_status). */
export type ReactionReel = {
  id: number
  path: string
  duration_s: number
  cursor_s: number
  pieces_used: number
  used_pct: number
  active: boolean
  created_at: string
}
export const listReactionReels = () => request<ReactionReel[]>('/api/reactions')
export const activateReactionReel = (id: number) => post<ReactionReel>(`/api/reactions/${id}/activate`)
export const resetReactionReel = (id: number) => post<ReactionReel>(`/api/reactions/${id}/reset`)
/** Sends the file itself as the body (the server streams it to disk). XHR, not fetch:
 * fetch reports no upload progress. `onProgress` gets 0..1. */
const uploadFile = <T>(path: string, file: File, onProgress?: (fraction: number) => void) =>
  new Promise<T>((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', path)
    xhr.setRequestHeader('Accept', 'application/json')
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress?.(e.loaded / e.total) }
    xhr.onload = () => {
      let body: unknown = null
      try { body = JSON.parse(xhr.responseText) } catch { /* not JSON */ }
      if (xhr.status >= 200 && xhr.status < 300) return resolve(body as T)
      const code = (body as { error?: unknown } | null)?.error
      reject(new ApiError(xhr.status, typeof code === 'string' ? code : 'http_error', body))
    }
    xhr.onerror = () => reject(new Error('Upload failed: check the connection and try again'))
    xhr.send(file)
  })
export const uploadReactionReel = (file: File, onProgress?: (fraction: number) => void) =>
  uploadFile<ReactionReel>(`/api/reactions/upload?name=${encodeURIComponent(file.name)}`, file, onProgress)

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
  retention: RetentionFinding[]
  // the studio video's story (step 110); null outside the studio
  description: string | null
  timeline: TimelineEvent[] | null
  duration: number | null
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
// --- Permission tracker (step 065; src/api/permissions.py). The studio never sends the message. ---
export type PermissionStatus = 'requested' | 'granted' | 'denied'
export type PermissionChannel = 'dm' | 'email' | 'other'
/** A clip by source id, or a Reel link not stored yet (an inspiration). */
export type PermissionTarget = { source_id: number } | { url: string }
export type PermissionRequest = {
  id: number
  source_id: number
  creator: string
  channel: PermissionChannel
  status: PermissionStatus
  requested_at: string
  answered_at: string | null
  proof_note: string | null
  ads_allowed: boolean
  url: string | null
  rights_basis: RightsBasis | 'unknown'
  has_file: boolean
}
export type PermissionDraft = { creator: string | null; url: string | null; message: string }
export const listPermissions = () => request<PermissionRequest[]>('/api/permissions')
export const getPermissionDraft = (target: PermissionTarget, creator?: string) =>
  request<PermissionDraft>(`/api/permissions/draft?${new URLSearchParams({
    ...('source_id' in target ? { source_id: String(target.source_id) } : { url: target.url }),
    ...(creator && { creator }),
  })}`)
export const askPermission = (
  body: PermissionTarget & { channel: PermissionChannel; note?: string; creator?: string },
) => post<{ request: PermissionRequest; draft: PermissionDraft }>('/api/permissions', body)
export const answerPermission = (
  id: number, body: { status: 'granted' | 'denied'; proof_note?: string; ads_allowed?: boolean },
) => post<PermissionRequest>(`/api/permissions/${id}/answer`, body)
/** The creator's file, as the request body (like the reaction reel upload). */
export const attachPermissionFile = (id: number, file: File, audio: AudioRights) =>
  uploadFile<Clip>(`/api/permissions/${id}/attach?${new URLSearchParams({ name: file.name, audio_rights: audio })}`, file)
/** POST /api/sources/download (step 063b): a public Reel saved for a reaction; `reason` says why not. */
export type ReelDownload = {
  status: 'downloaded' | 'exists' | 'refused' | 'failed'
  reason?: string
  source?: { id: number; author: string | null } | null
}
export const downloadReel = (target: { source_id: number } | { url: string }) =>
  post<ReelDownload>('/api/sources/download', target)

// --- Stock clips (step 064; src/api/stock.py) ---
/** A video of GET /api/stock/search (Pexels); `image`: its preview picture. */
export type StockResult = {
  id: number
  url: string | null
  author: string | null
  duration_s: number | null
  width: number | null
  height: number | null
  image: string | null
}
export const stockStatus = () => request<{ configured: boolean; provider: string }>('/api/stock')
export const searchStock = (q: string) =>
  request<StockResult[]>(`/api/stock/search?${new URLSearchParams({ q })}`)
export const addStockClip = (result_id: number) => post<Clip>('/api/stock/add', { result_id })

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

// --- Pinned accounts and DM picks (step 113) ---
/** A row of GET /api/pinned-accounts: username normalised (lowercase, no @). */
export type PinnedAccount = { id: number; username: string; ig_user_id: string | null; note: string | null; created_at: string }
export type DmPickStatus = 'new' | 'downloaded' | 'in_production' | 'posted' | 'skipped'
/** A row of GET /api/dm-picks (newest first): a Reel a pinned account sent by DM; sender_note is their text (untrusted). */
export type DmPick = {
  id: number
  pinned_account_id: number | null
  sender_username: string
  reel_url: string
  reel_media_id: string | null
  sender_note: string | null
  received_at: string
  status: DmPickStatus
  skip_reason: string | null
  source_id: number | null
  created_at: string
  updated_at: string
}
export const listPinnedAccounts = () => request<PinnedAccount[]>('/api/pinned-accounts')
export const pinAccount = (username: string, note: string) =>
  post<PinnedAccount>('/api/pinned-accounts', { username, note: note || null })
export const unpinAccount = (id: number) => request<null>(`/api/pinned-accounts/${id}`, { method: 'DELETE' })
export const listDmPicks = (status?: DmPickStatus) =>
  request<DmPick[]>(`/api/dm-picks${status ? `?status=${status}` : ''}`)
export const skipDmPick = (id: number, reason: string) => post<DmPick>(`/api/dm-picks/${id}/skip`, { reason })

// --- Retention findings (step 111) ---
/** A finding of src/learning/retention.py; `at_s`/`event`: where in the video it points. */
export type RetentionFinding = {
  kind: 'hook' | 'exit' | 'payoff' | 'strong'
  at_s?: number
  event?: string
  evidence: Record<string, number | null>
  confidence: 'low' | 'medium' | 'high'
  text: string
}

// --- Reel downloader (step 063a; src/api/downloader.py) ---
export type DownloaderHealth = { status: 'up' | 'down' | 'broken' | 'not_configured'; checked_at: string; detail?: string }
/** GET /api/downloader/status: `health` is the worker's last daily check (null: never ran). */
export type DownloaderStatus = {
  set_up: boolean
  host: string
  port: number
  health_configured: boolean
  health: DownloaderHealth | null
}
export const getDownloaderStatus = () => request<DownloaderStatus>('/api/downloader/status')

// --- Daily report (steps 082, 083; page 085; src/api/reports.py) ---
type Window = {
  published?: { count: number }
  matured?: { count: number }
  funnel?: FunnelStats
}
/** A best / worst pick of the nightly analysis (083). */
export type ReportPick = { media_id: string; why: string }
export type ReportExperiment = { hypothesis: string; variable: string; variants: string[] }
/** GET /api/reports/latest | /api/reports/{date}: `posts` describes every media id it names. */
export type DailyReport = {
  report_date: string
  summary: string | null // markdown; null on a quiet day the analysis skipped
  facts: {
    yesterday?: Window
    last_7_days?: Window
    // other people's words: shown as quotes, never as the studio's
    audience_comments?: { note: string | null; posts: { media_id: string; permalink: string | null; comments: { quote: string; likes: number }[] }[] }
  }
  analysis: { best?: ReportPick[]; worst?: ReportPick[]; experiments?: ReportExperiment[] }
  posts: Record<string, {
    media_id: string
    permalink: string | null
    title: string | null
    asset_id: number | null
    thumbnail_url: string | null
    verdict: string | null
    retention: RetentionFinding[]
  }>
}
/** A row of GET /api/reports: the archive, newest first. */
export type ReportDay = {
  report_date: string
  first_line: string | null
  published: number | null
  matured: number | null
  best: number
  worst: number
  experiments: number
}
export const getReport = (date?: string) =>
  request<DailyReport>(`/api/reports/${date ? encodeURIComponent(date) : 'latest'}`)
export const listReports = (limit = 60) => request<ReportDay[]>(`/api/reports?limit=${limit}`)

// --- Learnings (steps 081, 084; src/api/learnings.py) ---
export type LearningKind = 'do' | 'dont' | 'hypothesis'
export type Predicate = { tag: string; value: string }
/** One evidence item: a comment (with its video), the numbers (081), a conflict, or the agent's own. */
export type Evidence = {
  feedback_id?: number
  text?: string | null
  asset_id?: number
  thumbnail_url?: string | null
  kind?: 'audience_index' | 'conflict' | string
  n?: number
  index?: number | null
  verdict?: 'supports' | 'contradicts' | 'inconclusive' | 'needs_n' | 'untested'
  note?: string
  with?: number | null
  detail?: string
}
export type Learning = {
  id: number
  statement: string
  kind: LearningKind
  origin: 'taste' | 'audience' | 'ads'
  confidence: 'low' | 'medium' | 'high' | 'owner'
  status: 'active' | 'retired' | 'contradicted'
  scope: Partial<Predicate>
  evidence: Evidence[]
  created_at: string
  updated_at: string
}
export type LearningFilters = Partial<Record<'kind' | 'status' | 'origin' | 'confidence', string>>
export type RuleInput = { statement: string; kind: LearningKind; predicate: Predicate | null }
export const listLearnings = (filters: LearningFilters) =>
  request<Learning[]>(`/api/learnings?${new URLSearchParams(filters as Record<string, string>)}`)
export const addRule = (rule: RuleInput) => post<Learning>('/api/learnings', rule)
export const editLearning = (id: number, rule: RuleInput) => send<Learning>('PATCH', `/api/learnings/${id}`, rule)
export const setLearning = (id: number, action: 'confirm' | 'retire' | 'reactivate') =>
  post<Learning>(`/api/learnings/${id}/${action}`)
export const refreshLearnings = () =>
  post<{ evaluated: number; contradicted: number[]; conflicts: number[] }>('/api/learnings/refresh')

// --- Alerts (step 098; src/api/alerts.py) ---
/** What needs the owner's attention, newest first; `link` is a website path. */
export type Alert = {
  id: string
  kind: string
  severity: 'info' | 'warn' | 'error'
  title: string
  detail: string
  link: string
  since: string | null
}
export const getAlerts = () => request<Alert[]>('/api/alerts')
export const dismissAlert = (id: string) => post<{ id: string }>(`/api/alerts/${encodeURIComponent(id)}/dismiss`)

// --- Ads (steps 091, 094, 095; src/api/ads.py) ---
/** Money comes as decimal strings, in `currency`. */
export type BudgetScope = { cap: string; used: string; remaining: string }
export type AdsBudget = {
  killed: boolean
  killed_at: string | null
  killed_reason: string | null
  currency: string
  day: string
  daily: BudgetScope
  lifetime: BudgetScope
  test_cap: string
  tests: (BudgetScope & { test_id: number })[]
  /** src/ads/sync.py near_caps(): the scopes at 80 % of their cap or more. */
  near_cap: { daily: boolean; lifetime: boolean; tests: number[] }
}
export type AdVariable = 'creative' | 'audience' | 'placement'
export type AdTestStatus = 'proposed' | 'approved' | 'running' | 'finished' | 'cancelled'
export type AdTest = {
  id: number
  hypothesis: string
  variable: AdVariable
  variants: { media_id: string; preset: string }[]
  min_lift: number
  spec: { min_days: number; max_days: number; min_sample: number; primary_metric: AdMetric }
  needed: { total: number; per_variant: number; sample_per_variant: number }
  budget_total: string | null
  currency: string
  end_date: string | null
  status: AdTestStatus
  reason: string | null
  proposed_by: 'owner' | 'agent'
  /** GET /api/ads/tests only (126): who launched it, the owner's Approve or the AI; null before. */
  launched_by?: 'owner' | 'agent' | null
  /** Proposed tests only: why the caps cannot fund the test, or null. */
  underpowered: string | null
  created_at: string
  /** The worker's latest snapshot (095); null until the first sync. */
  result: AdResult | null
}
export type AdMetric = 'ctr' | 'result_rate' | 'conversion_rate'
/** src/ads/abtest.py evaluate(); 'error' (only `error` set) when the snapshot could not be judged. */
export type AdEvaluation = {
  status: 'too_early' | 'running' | 'winner' | 'no_difference' | 'error'
  error?: string
  metric: AdMetric
  days: number
  variants: Record<string, { successes: number; trials: number; rate: number | null }>
  winner: string | null
  p_values: Record<string, number>
  lift: { vs: string; value: number; ci_low: number; ci_high: number; confidence: number } | null
}
export type AdReviewIssue = { ad_id: string; media_id: string; effective_status: string; reason: string }
export type AdResult = {
  synced_at: string
  days: number
  variants: Record<string, { media_id: string; preset: string; impressions: number; clicks: number; results: number; spend: string }>
  evaluation: AdEvaluation
  review: AdReviewIssue[]
}
/** GET /api/ads/tests/{id} (src/ads/sync.py results). */
export type AdTestResults = AdTest & {
  spend: { reported: string | null; counted: string; budget: string | null; currency: string }
  near_cap: { daily: boolean; lifetime: boolean; test: boolean }
}
export type AdWinner = {
  media_id: string
  permalink: string | null
  posted_at: string
  caption: string
  asset_id: number
  thumbnail_url: string | null
}
/** Who sees an ad (src/config.py AdPreset, setting `ads_presets`, step 127). age_max null = 65+. */
export type AdPlacement = 'reels' | 'stream' | 'story' | 'explore'
export type AdPresetValue = {
  id: string
  label: string
  countries: string[]
  age_min: number
  age_max: number | null
  placements: AdPlacement[]
}
/** src/ads/tests.py presets(): `varies` = the variables a test may compare it on. */
export type AdPreset = AdPresetValue & { varies: Exclude<AdVariable, 'creative'>[] }
export type AdProposal = {
  hypothesis: string
  variable: AdVariable
  variants: { media_id: string; preset: string }[]
  min_lift: number
}
export type AdsAuditRow = {
  id: number
  at: string
  actor: 'owner' | 'agent' | 'system'
  action: string
  test_id: number | null
  detail: Record<string, unknown>
}
export type AdsAudit = { total: number; limit: number; offset: number; rows: AdsAuditRow[] }
export const getAdsBudget = () => request<AdsBudget>('/api/ads/budget')
export const killAds = (reason?: string) => post<AdsBudget>('/api/ads/kill', reason ? { reason } : undefined)
export const unkillAds = (password: string) => post<AdsBudget>('/api/ads/unkill', { password })
export const listAdTests = () => request<{ tests: AdTest[] }>('/api/ads/tests').then((r) => r.tests)
export const listAdWinners = () => request<{ winners: AdWinner[] }>('/api/ads/winners').then((r) => r.winners)
export const listAdPresets = () => request<{ presets: AdPreset[] }>('/api/ads/presets').then((r) => r.presets)
export const proposeAdTest = (p: AdProposal) => post<AdTest>('/api/ads/tests', p)
/** The owner's Approve: launches the test within the caps, no password (126). */
export const approveAdTest = (id: number, body: { budget: string; underpowered_ok: boolean }) =>
  post<AdTest>(`/api/ads/tests/${id}/approve`, body)
export const getAdTest = (id: number) => request<AdTestResults>(`/api/ads/tests/${id}`)
export const cancelAdTest = (id: number) => post<AdTest>(`/api/ads/tests/${id}/cancel`)
export const getAdsAudit = (offset = 0, limit = 20) => request<AdsAudit>(`/api/ads/audit?limit=${limit}&offset=${offset}`)

// --- Trending page (step 134 research feed, step 136 work orders; page 135) ---
/** owner: follow the owner's own instruction (DM orders, 136); Trending orders are inspired | react. */
export type WorkMode = 'inspired' | 'react' | 'owner'
export type TrendMode = Exclude<WorkMode, 'owner'>
/** A Reel of GET /api/research/feed, best outlier first; caption_quote is other people's
 * words (shown as a quote only). `work_order`: its open order, else null. */
export type FeedItem = {
  id: number
  permalink: string | null
  embed_url: string | null
  media_url: string | null
  thumbnail_url: string | null
  media_type: string | null // VIDEO | IMAGE | CAROUSEL_ALBUM
  product_type: string | null // REELS | FEED
  caption_quote: string | null
  likes: number | null
  comments: number | null
  views: number | null
  posted_at: string | null
  topic: string | null
  topic_kind: 'account' | 'hashtag' | null
  outlier: number | null
  outlier_metric: 'views' | 'likes' | null
  reaction: 'like' | 'dislike' | null
  work_order: { id: number; mode: WorkMode; instruction: string | null; status: OpenOrderStatus } | null
}
export type HashtagBudget = { limit: number; used: number; left: number }
/** POST /api/research/refresh (409 already_running, 503 instagram_not_configured). */
export type RefreshResult = {
  hashtags_searched: string[]
  hashtags_skipped_budget: string[]
  accounts: string[]
  stored: number
  updated: number
  errors: Record<string, string>
  stopped: 'request_budget' | 'rate_limited' | null
  hashtag_budget: HashtagBudget
}
export type SuggestedTopics = {
  topics: { tag: string; lang: string; watched: boolean }[]
  hashtag_budget: HashtagBudget
  note: string
}
export const refreshResearch = () => post<RefreshResult>('/api/research/refresh')
export const getResearchFeed = (topic?: string | null, limit = 50) =>
  request<FeedItem[]>(`/api/research/feed?${new URLSearchParams({ ...(topic && { topic }), limit: String(limit) })}`)
export const getSuggestedTopics = () => request<SuggestedTopics>('/api/research/suggested-topics')
export const setFeedReaction = (sourceId: number, reaction: 'like' | 'dislike' | 'none') =>
  post<{ id: number; reaction: FeedItem['reaction'] }>(`/api/research/feed/${sourceId}/reaction`, { reaction })
export const createWorkOrders = (items: { source_id: number; mode: TrendMode; instruction?: string }[]) =>
  post<unknown[]>('/api/research/work-orders', { items })
export const cancelWorkOrder = (id: number) => request<null>(`/api/research/work-orders/${id}`, { method: 'DELETE' })

export type OpenOrderStatus = 'needs_instruction' | 'scheduled' | 'in_production'
export type WorkOrderStatus = OpenOrderStatus | 'in_feed' | 'analysed' | 'skipped'
/** A row of GET /api/work-orders (step 136), newest first: a Reel the owner sent by DM
 * (source dm) or from the Trending feed (trend). */
export type WorkOrder = {
  id: number
  source: 'dm' | 'trend'
  source_id: number | null
  pick_id: number | null
  sender_username: string | null // dm only
  received_at: string | null // dm only
  created_at: string
  scheduled_at: string | null
  permalink: string | null
  embed_url: string | null
  own_reel: boolean // the brand's own Reel (a recut, or analyse only)
  instruction: string | null
  mode: WorkMode
  status: WorkOrderStatus
  skip_reason: string | null
  blocked_reason: string | null
  analysis: string | null // status analysed: the AI's analysis, no video
  idea_id: number | null
  asset_id: number | null
  // what the Reel was (trend orders; a DM Reel has none until downloaded); caption: other people's words
  topic: string | null
  caption_quote: string | null
  thumbnail_url: string | null
  likes: number | null
  comments: number | null
  views: number | null
}
export const listWorkOrders = (source: 'dm' | 'trend' | 'all' = 'all') =>
  request<WorkOrder[]>(`/api/work-orders?source=${source}`)
/** Allowed while needs_instruction or scheduled; 409 once the AI started. */
export const editWorkOrder = (id: number, body: { instruction: string; mode?: WorkMode }) =>
  send<WorkOrder>('PATCH', `/api/work-orders/${id}`, body)
