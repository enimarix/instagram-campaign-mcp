import { useEffect, useState, type ReactNode } from 'react'
import {
  ApiError, errorMessage, getAccount, getAgentSchedule, getDownloaderStatus, getHealth, getStorage, getToken,
  getWorkerStatus, setPublishingPaused, type AgentScheduleEntry, type DownloaderStatus, type RunResult,
  type TokenStatus,
} from '../api/client'
import { Button } from '../ui/Button'
import { Card, Skeleton } from '../ui/Card'
import { Chip } from '../ui/Chip'
import { PageHeader } from '../ui/PageHeader'
import { ThemeToggle } from '../ui/ThemeToggle'
import ClipsSection from './Clips'
import DmPicksSection from './DmPicks'
import { dateTime, playbookName } from './load'
import ReactionReelSection from './ReactionReel'

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
    <Card as="section" aria-label={title}>
      <h2 className="font-semibold">{title}</h2>
      {load.error !== undefined ? (
        <p role="alert" className="mt-2 text-sm text-danger">{errorMessage(load.error)}</p>
      ) : load.data === undefined ? (
        <Skeleton className="mt-3 h-12" />
      ) : (
        <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">{children}</dl>
      )}
    </Card>
  )
}

const Row = ({ label, children }: { label: string; children: ReactNode }) => (
  <>
    <dt className="text-muted">{label}</dt>
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

function scheduleLine(e: AgentScheduleEntry) {
  const next = e.exists ? `Next ${dateTime(e.next_at)}` : 'Playbook not written yet'
  const last = e.last_run ? `last ${e.last_run.status} ${relative(e.last_run.started_at)}` : 'never ran'
  return `${next} · ${last}`
}

const DOWNLOADER_TONE = { up: 'success', down: 'danger', broken: 'danger', not_configured: 'neutral' } as const

function DownloaderRows({ d }: { d: DownloaderStatus }) {
  const h = d.health
  return (
    <>
      <Row label="Status">
        {!d.set_up ? <Chip tone="warn">not set up</Chip>
          : <Chip tone={DOWNLOADER_TONE[h?.status ?? 'not_configured']}>{(h?.status ?? 'not checked yet').replace('_', ' ')}</Chip>}
      </Row>
      {h && <Row label="Last check">{relative(h.checked_at)}{h.detail && ` · ${h.detail}`}</Row>}
      {!d.set_up && (
        <Row label="Set it up">
          Run <code className="rounded bg-surface-2 px-1.5 py-0.5 select-all">ig-campaign downloader setup</code>
        </Row>
      )}
      {!d.health_configured && <Row label="Health check">Off: set <code>DOWNLOADER_HEALTH_URL</code> in .env</Row>}
      <Row label="Address">{d.host}:{d.port} (this computer only)</Row>
    </>
  )
}

const str = (v: unknown) => (typeof v === 'string' || typeof v === 'number' ? String(v) : undefined)

export default function Settings() {
  const [health] = useLoad(getHealth)
  const [account] = useLoad(getAccount)
  const [worker, setWorker] = useLoad(getWorkerStatus)
  const [storage] = useLoad(getStorage)
  const [token] = useLoad(getToken)
  const [schedule] = useLoad(getAgentSchedule)
  const [downloader] = useLoad(getDownloaderStatus)
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
      <PageHeader title="Settings" />
      {setupMode && (
        <p role="status" className="mb-4 rounded-card border border-warn/30 bg-warn/12 p-4 font-medium text-warn">
          Setup mode: add your Instagram token
        </p>
      )}

      <div className="gap-4 lg:columns-2 [&>*]:mb-4 [&>*]:break-inside-avoid">
        <Card as="section" aria-label="Appearance">
          <h2 className="font-semibold">Appearance</h2>
          <p className="mt-1 text-sm text-muted">Dark suits reviewing video; the choice is kept in this browser.</p>
          <div className="mt-3"><ThemeToggle /></div>
        </Card>

        <div>
          <Section title="Worker" load={worker}>
            {w && (
              <>
                <Row label="Status">
                  <span aria-hidden className={`mr-1.5 inline-block size-2 rounded-full ${w.alive ? 'bg-success' : 'bg-danger'}`} />
                  {w.alive ? 'Running' : 'Not running'}
                </Row>
                <Row label="Heartbeat">{w.heartbeat_at ? relative(w.heartbeat_at) : 'Never'}</Row>
                <Row label="Next slot">{w.next_slot ? dateTime(w.next_slot) : 'Nothing queued'}</Row>
                <Row label="Last run">{runSummary(w.last_result)}</Row>
                <Row label="Publishing">{w.paused ? 'Paused' : 'On'}</Row>
              </>
            )}
          </Section>
          {w && (
            <div className="mt-2">
              <Button variant={w.paused ? 'primary' : 'secondary'} className={`w-full md:w-auto ${w.paused ? '' : 'text-warn!'}`}
                onClick={() => void togglePause(!w.paused)}>
                {w.paused ? 'Resume publishing' : 'Pause publishing'}
              </Button>
              {toggleError && <p role="alert" className="mt-1 text-sm text-danger">{toggleError}</p>}
            </div>
          )}
        </div>

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
                  <span role="alert" className="ml-2 font-medium text-danger">Low: free some space</span>
                )}
              </Row>
            </>
          )}
        </Section>

        <Section title="Backups" load={storage}>
          <Row label="Last backup">{s?.last_backup ? dateTime(s.last_backup) : 'No backups yet'}</Row>
        </Section>

        <Section title="Agent schedule" load={schedule}>
          {schedule.data?.length === 0 && <Row label="Runs">None (AGENT_SCHEDULE is empty)</Row>}
          {schedule.data?.map((e) => (
            <Row key={e.playbook} label={`${playbookName(e.playbook)} at ${e.time}`}>{scheduleLine(e)}</Row>
          ))}
        </Section>

        <ClipsSection />
        <ReactionReelSection />
        <DmPicksSection />
        <Section title="Reel downloader" load={downloader}>
          {downloader.data && <DownloaderRows d={downloader.data} />}
        </Section>

        <Section title="Server" load={health}>
          <Row label="Version">{health.data ? `${health.data.status}, v${health.data.version}` : ''}</Row>
        </Section>
      </div>
    </section>
  )
}
