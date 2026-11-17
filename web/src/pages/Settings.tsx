import { useEffect, useState, type ReactNode } from 'react'
import {
  ApiError, errorMessage, getAccount, getHealth, getStorage, getToken, getWorkerStatus,
  setPublishingPaused, type RunResult, type TokenStatus,
} from '../api/client'
import { button } from '../inbox/ui'

// ponytail: fixed threshold (~a week of daily batches); make it a setting if it nags.
const LOW_FREE_BYTES = 5e9

type Load<T> = { data?: T; error?: unknown }

/** Loads once on mount; `set` replaces the data (e.g. with a route's answer). */
function useLoad<T>(fn: () => Promise<T>) {
  const [state, setState] = useState<Load<T>>({})
  useEffect(() => {
    fn().then((data) => setState({ data }), (error: unknown) => setState({ error }))
  }, [fn])
  return [state, (data: T) => setState({ data })] as const
}

const UNITS: [number, Intl.RelativeTimeFormatUnit][] = [[86400, 'day'], [3600, 'hour'], [60, 'minute']]
/** "3 minutes ago", "in 2 hours". */
function relative(iso: string) {
  const s = (Date.parse(iso) - Date.now()) / 1000
  const [size, unit] = UNITS.find(([n]) => Math.abs(s) >= n) ?? [1, 'second']
  return new Intl.RelativeTimeFormat('en', { numeric: 'auto' }).format(Math.round(s / size), unit)
}

function formatBytes(n: number) {
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0
  while (n >= 1000 && i < units.length - 1) { n /= 1000; i++ }
  return `${i ? n.toFixed(1) : n} ${units[i]}`
}

function runSummary(r: RunResult | null) {
  if (!r) return 'No run yet'
  if (r.error) return `Failed: ${r.error}`
  if (r.paused) return 'Paused, nothing published'
  const counts = (['published', 'failed', 'retrying', 'replanned'] as const)
    .filter((k) => r[k]?.length).map((k) => `${r[k]!.length} ${k}`)
  return counts.join(', ') || 'Nothing due'
}

function Section({ title, load, children }: { title: string; load: Load<unknown>; children?: ReactNode }) {
  return (
    <section aria-label={title} className="mt-4 rounded-lg border border-gray-200 bg-white p-4">
      <h3 className="font-semibold">{title}</h3>
      {load.error !== undefined ? (
        <p role="alert" className="mt-2 text-sm text-red-700">{errorMessage(load.error)}</p>
      ) : load.data === undefined ? (
        <p className="mt-2 text-sm text-gray-500">Loading…</p>
      ) : (
        <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">{children}</dl>
      )}
    </section>
  )
}

const Row = ({ label, children }: { label: string; children: ReactNode }) => (
  <>
    <dt className="text-gray-500">{label}</dt>
    <dd>{children}</dd>
  </>
)

function tokenExpiry(t: TokenStatus) {
  if (!t.configured) return 'No token'
  if (t.valid === null) return 'Unknown'
  if (!t.valid) return 'Expired or invalid'
  if (!t.expires_at) return 'Never (system-user token)'
  return `${new Date(t.expires_at).toLocaleDateString()} (${t.days_left} days left)`
}

const str = (v: unknown) => (typeof v === 'string' || typeof v === 'number' ? String(v) : undefined)

export default function Settings() {
  const [health] = useLoad(getHealth)
  const [account] = useLoad(getAccount)
  const [worker, setWorker] = useLoad(getWorkerStatus)
  const [storage] = useLoad(getStorage)
  const [token] = useLoad(getToken)
  const [toggleError, setToggleError] = useState<string | null>(null)

  const setupMode = health.data?.instagram_configured === false ||
    (account.error instanceof ApiError && account.error.code === 'instagram_not_configured')

  async function togglePause(paused: boolean) {
    const question = paused
      ? 'Pause publishing? Nothing goes out until you resume.'
      : 'Resume publishing? Due posts go out at the next run.'
    if (!window.confirm(question)) return
    setToggleError(null)
    try {
      setWorker(await setPublishingPaused(paused))
    } catch (e) {
      setToggleError(errorMessage(e))
    }
  }

  const w = worker.data
  const profile = account.data?.profile
  const limit = account.data?.publishing_limit
  const quotaTotal = (limit?.config as Record<string, unknown> | undefined)?.quota_total
  const s = storage.data

  return (
    <section>
      <h2 className="text-2xl font-semibold">Settings</h2>
      {setupMode && (
        <p role="status" className="mt-4 rounded-lg bg-amber-100 p-4 text-amber-900">
          Setup mode: add your Instagram token
        </p>
      )}

      <Section title="Worker" load={worker}>
        {w && (
          <>
            <Row label="Status">
              <span aria-hidden className={`mr-1 inline-block size-2 rounded-full ${w.alive ? 'bg-green-500' : 'bg-red-500'}`} />
              {w.alive ? 'Running' : 'Not running'}
            </Row>
            <Row label="Heartbeat">{w.heartbeat_at ? relative(w.heartbeat_at) : 'Never'}</Row>
            <Row label="Next slot">{w.next_slot ? new Date(w.next_slot).toLocaleString() : 'Nothing queued'}</Row>
            <Row label="Last run">{runSummary(w.last_result)}</Row>
            <Row label="Publishing">{w.paused ? 'Paused' : 'On'}</Row>
          </>
        )}
      </Section>
      {w && (
        <div className="mt-2">
          <button type="button" onClick={() => void togglePause(!w.paused)}
            className={`${button} w-full md:w-auto ${w.paused ? 'bg-blue-600 text-white' : 'bg-amber-100 text-amber-900'}`}>
            {w.paused ? 'Resume publishing' : 'Pause publishing'}
          </button>
          {toggleError && <p role="alert" className="mt-1 text-sm text-red-700">{toggleError}</p>}
        </div>
      )}

      <Section title="Instagram" load={setupMode ? { data: true } : account}>
        <Row label="Configured">{setupMode ? 'No' : 'Yes'}</Row>
        {!setupMode && (
          <>
            <Row label="Token">{account.data?.token_valid ? 'Valid' : 'Invalid'}</Row>
            <Row label="Account">{str(profile?.username) ?? '—'}</Row>
            <Row label="Publishing limit">
              {str(limit?.quota_usage) ?? '?'} / {str(quotaTotal) ?? '?'} in 24 h
            </Row>
          </>
        )}
        <Row label="Token expiry">
          {token.error !== undefined ? errorMessage(token.error) : token.data ? tokenExpiry(token.data) : 'Loading…'}
        </Row>
      </Section>

      <Section title="Storage" load={storage}>
        {s && (
          <>
            <Row label="Media">{formatBytes(s.media_bytes)}</Row>
            <Row label="Database">{formatBytes(s.db_bytes)}</Row>
            <Row label="Free space">
              {formatBytes(s.free_bytes)}
              {s.free_bytes < LOW_FREE_BYTES && (
                <span role="alert" className="ml-2 font-medium text-red-700">Low: free some space</span>
              )}
            </Row>
          </>
        )}
      </Section>

      <Section title="Backups" load={storage}>
        <Row label="Last backup">{s?.last_backup ? new Date(s.last_backup).toLocaleString() : 'No backups yet'}</Row>
      </Section>

      <Section title="Server" load={health}>
        <Row label="Version">{health.data ? `${health.data.status}, v${health.data.version}` : ''}</Row>
      </Section>
    </section>
  )
}
