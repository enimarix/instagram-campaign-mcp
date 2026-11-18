import { useState, type FormEvent } from 'react'
import {
  ApiError, approveAdTest, cancelAdTest, errorMessage, getAdsAudit, getAdsBudget, getAdTest, killAds, listAdTests,
  listAdPresets, listAdWinners, proposeAdTest, unkillAds, type AdMetric, type AdPreset, type AdReviewIssue,
  type AdsBudget, type AdTest, type AdTestStatus, type AdVariable, type BudgetScope,
} from '../api/client'
import { Button } from '../ui/Button'
import { Card, EmptyState, Skeleton } from '../ui/Card'
import { Chip } from '../ui/Chip'
import { PageHeader } from '../ui/PageHeader'
import { Sheet } from '../ui/Sheet'
import { field, type Tone } from '../ui/styles'
import { Tabs } from '../ui/Tabs'
import { dateTime, humanize, num, pct, useLoad } from './load'

// Steps 094 (API), 094b (this page), 095b (results), 126 and 128 (the AI proposes, you launch).
const VARIABLES: { id: AdVariable; label: string }[] = [
  { id: 'creative', label: 'Video' }, { id: 'audience', label: 'Audience' }, { id: 'placement', label: 'Placement' },
]
const STATUS_TONE: Record<AdTestStatus, Tone> = {
  proposed: 'info', approved: 'accent', running: 'success', finished: 'neutral', cancelled: 'neutral',
}
const REAUTH: Record<string, string> = {
  password_not_set: 'Set UI_PASSWORD in .env first: money actions need the website password.',
  password_required: 'Type your website password.',
  bad_password: 'Wrong password.',
}
const H6_NOTE = 'Ads are not set up yet. Setup step H6: put INSTAGRAM_ACCESS_TOKEN (with ads_read and ' +
  'ads_management) and META_AD_ACCOUNT_ID in .env, and set a spending limit on the ad account in Meta.'
const PAGE = 20
// Per metric (src/ads/abtest.py METRICS): its name, what "more" counts, what a version's sample counts.
const METRIC: Record<AdMetric, [string, string, string]> = {
  ctr: ['CTR', 'clicks', 'views'], result_rate: ['Result rate', 'results', 'views'],
  conversion_rate: ['Conversion rate', 'results', 'clicks'],
}

const money = (v: string | number, currency: string) => {
  try {
    return new Intl.NumberFormat('en', { style: 'currency', currency }).format(Number(v))
  } catch {
    return `${v} ${currency}` // not an ISO currency code
  }
}
const notConfigured = (e: unknown) =>
  e instanceof ApiError && (e.code === 'ads_not_configured' || e.code === 'not_configured')

/** The server's refusal in plain words; the re-typed password errors are mapped. */
function adsError(e: unknown) {
  if (e instanceof ApiError && e.code === 'locked') {
    const s = (e.body as { retry_after?: number } | null)?.retry_after ?? 60
    return `Too many wrong passwords: try again in ${Math.ceil(s / 60)} min.`
  }
  if (e instanceof ApiError && REAUTH[e.code]) return REAUTH[e.code]
  return errorMessage(e)
}

/** "To see a 20 % lift you need about €84.00 over 7 days". */
const needSentence = (t: AdTest) =>
  `To see a ${pct(t.min_lift)} lift you need about ${money(t.needed.total, t.currency)} over ${t.spec.min_days} days`

type Act = (fn: () => Promise<unknown>) => Promise<string | null>

function UnkillSheet({ act, onClose }: { act: Act; onClose: () => void }) {
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    const err = await act(() => unkillAds(password))
    setBusy(false)
    if (err) setError(err)
    else onClose()
  }
  return (
    <Sheet title="Allow ads again" onClose={onClose}>
      <form onSubmit={(e) => void submit(e)} className="mt-3 grid gap-3 text-sm">
        <p className="text-muted">New spend becomes possible again, within the caps. Type your website password.</p>
        <label>Password
          <input type="password" value={password} required autoComplete="current-password"
            onChange={(e) => setPassword(e.target.value)} className={`${field} mt-1 block w-full`} />
        </label>
        {error && <p role="alert" className="text-danger">{error}</p>}
        <Button type="submit" variant="primary" loading={busy}>Allow ads again</Button>
      </form>
    </Sheet>
  )
}

function Scope({ label, s, currency }: { label: string; s: BudgetScope; currency: string }) {
  return (
    <div>
      <dt className="text-xs font-medium text-muted">{label}</dt>
      <dd className="mt-1 font-semibold tabular-nums">{money(s.remaining, currency)} left</dd>
      <dd className="text-xs text-muted">{money(s.used, currency)} used of {money(s.cap, currency)}</dd>
    </div>
  )
}

function BudgetCard({ b, act }: { b?: AdsBudget; act: Act }) {
  const [reason, setReason] = useState('')
  const [unkill, setUnkill] = useState(false)
  const [error, setError] = useState<string | null>(null)
  if (!b) return <Skeleton className="h-40" />
  const c = b.currency
  const zero = [b.daily.cap, b.lifetime.cap, b.test_cap].some((v) => Number(v) === 0)
  async function kill() {
    setError(await act(() => killAds(reason.trim() || undefined)))
    setReason('')
  }
  return (
    <Card as="section" aria-label="Budget">
      <h2 className="font-semibold">Budget</h2>
      <p className="mt-1 text-sm text-muted">
        A test spends only once you approve it, within these caps. <a href="/settings" className="text-accent underline">Change them in Settings, Ads</a>.
      </p>
      {b.killed && (
        <div role="status" className="mt-2 rounded-control bg-danger/12 p-3 text-sm text-danger">
          All ads are stopped{b.killed_reason ? `: ${b.killed_reason}` : ''}
          {b.killed_at && ` (since ${dateTime(b.killed_at)})`}. No new spend until you allow ads again.
        </div>
      )}
      {zero && (
        <p className="mt-2 text-sm text-muted">
          A cap at 0 allows no spend: raise it in Settings, Ads.
        </p>
      )}
      <dl className="mt-3 grid grid-cols-2 gap-3 md:grid-cols-3">
        <Scope label={`Today (${b.day})`} s={b.daily} currency={c} />
        <Scope label="Lifetime" s={b.lifetime} currency={c} />
        <div>
          <dt className="text-xs font-medium text-muted">Per test</dt>
          <dd className="mt-1 font-semibold tabular-nums">{money(b.test_cap, c)} at most</dd>
        </div>
      </dl>
      {b.tests.length > 0 && (
        <ul className="mt-3 text-sm text-muted">
          {b.tests.map((t) => (
            <li key={t.test_id}>Test #{t.test_id}: {money(t.used, c)} used, {money(t.remaining, c)} left</li>
          ))}
        </ul>
      )}
      <div className="mt-4 flex flex-wrap items-center gap-2">
        {b.killed ? (
          <Button variant="primary" onClick={() => setUnkill(true)}>Allow ads again</Button>
        ) : (
          <>
            <input aria-label="Reason (optional)" value={reason} maxLength={200} placeholder="reason (optional)"
              onChange={(e) => setReason(e.target.value)} className={`${field} min-w-0 flex-1 md:flex-none`} />
            <Button variant="danger" size="lg" onClick={() => void kill()}>Stop all ads</Button>
          </>
        )}
      </div>
      {error && <p role="alert" className="mt-2 text-sm text-danger">{error}</p>}
      {unkill && <UnkillSheet act={act} onClose={() => setUnkill(false)} />}
    </Card>
  )
}

type Labels = Record<string, string> // preset id → its plain label

function ProposeSheet({ presets, act, onClose }: { presets: AdPreset[]; act: Act; onClose: () => void }) {
  const winners = useLoad(listAdWinners, 0)
  const [variable, setVariable] = useState<AdVariable>('creative')
  const [medias, setMedias] = useState<string[]>([])
  const [compared, setCompared] = useState<string[]>([])
  const [picked, setPicked] = useState<string>()
  const preset = picked ?? presets[0]?.id ?? ''
  const [hypothesis, setHypothesis] = useState('')
  const [lift, setLift] = useState('20')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState<AdTest>()
  const creative = variable === 'creative'
  const toggle = (list: string[], v: string) => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v])
  const variants = creative
    ? medias.map((media_id) => ({ media_id, preset }))
    : compared.map((p) => ({ media_id: medias[0], preset: p }))
  const ready = hypothesis.trim() && (creative ? preset && medias.length >= 2 && medias.length <= 4 : medias.length === 1 && compared.length >= 2)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    let made: AdTest | undefined
    const err = await act(async () => {
      made = await proposeAdTest({ hypothesis: hypothesis.trim(), variable, variants, min_lift: Number(lift) / 100 })
    })
    setBusy(false)
    setError(err)
    setDone(made)
  }

  if (done)
    return (
      <Sheet title="Test proposed" onClose={onClose}>
        <p className="mt-3 font-medium">{needSentence(done)}.</p>
        {done.underpowered && <p role="alert" className="mt-2 text-sm text-warn">Too small: {done.underpowered}.</p>}
        <p className="mt-2 text-sm text-muted">Nothing is spent until you approve it in the tests list.</p>
        <Button variant="primary" className="mt-4 w-full" onClick={onClose}>Done</Button>
      </Sheet>
    )
  return (
    <Sheet title="Propose a test" onClose={onClose}>
      <form onSubmit={(e) => void submit(e)} className="mt-3 grid gap-3 text-sm">
        <Tabs label="What to vary" tabs={VARIABLES} value={variable}
          onChange={(v) => { setVariable(v); setMedias([]); setCompared([]) }} />
        <fieldset>
          <legend className="font-medium">{creative ? 'Pick 2 to 4 winners' : 'Pick one winner'}</legend>
          {winners.error && <p role="alert" className="text-danger">{winners.error}</p>}
          {!winners.data ? !winners.error && <Skeleton className="h-12" /> : winners.data.length === 0 ? (
            <p className="text-muted">No winners yet: a Reel becomes one when it beats the account once it matures.</p>
          ) : (
            <ul className="mt-1 grid gap-1">
              {winners.data.map((w) => (
                <li key={w.media_id}>
                  <label className="flex min-h-11 items-center gap-2">
                    <input type={creative ? 'checkbox' : 'radio'} name="winner" checked={medias.includes(w.media_id)}
                      onChange={() => setMedias(creative ? toggle(medias, w.media_id) : [w.media_id])} />
                    {w.thumbnail_url && <img src={w.thumbnail_url} alt="" className="h-10 w-6 shrink-0 rounded object-cover" />}
                    <span className="min-w-0 truncate">{w.caption || `Post ${w.media_id}`}</span>
                    <span className="ml-auto shrink-0 text-muted">{dateTime(w.posted_at)}</span>
                  </label>
                </li>
              ))}
            </ul>
          )}
        </fieldset>
        {creative ? (
          <label>Who sees it
            <select value={preset} onChange={(e) => setPicked(e.target.value)} className={`${field} mt-1 block w-full`}>
              {presets.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
            </select>
          </label>
        ) : (
          <fieldset>
            <legend className="font-medium">Compare</legend>
            <div className="mt-1 flex flex-wrap gap-2">
              {presets.filter((p) => p.varies.includes(variable)).map((p) => (
                <Chip key={p.id} pressed={compared.includes(p.id)} onClick={() => setCompared(toggle(compared, p.id))}>
                  {p.label}
                </Chip>
              ))}
            </div>
          </fieldset>
        )}
        <label>What you expect
          <textarea value={hypothesis} required maxLength={500} rows={2} onChange={(e) => setHypothesis(e.target.value)}
            placeholder="the boss-fight video gets more clicks" className={`${field} mt-1 block w-full py-2`} />
        </label>
        <label>Smallest difference worth seeing (%)
          <input type="number" min={1} max={500} value={lift} required onChange={(e) => setLift(e.target.value)}
            className={`${field} mt-1 block w-full`} />
        </label>
        {error && <p role="alert" className="text-danger">{error}</p>}
        <Button type="submit" variant="primary" loading={busy} disabled={!ready}>Work out the budget</Button>
      </form>
    </Sheet>
  )
}

function ApproveSheet({ t, act, onClose }: { t: AdTest; act: Act; onClose: () => void }) {
  const [budget, setBudget] = useState(t.needed.total.toFixed(2))
  const [anyway, setAnyway] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const short = t.underpowered
    ?? (Number(budget) < t.needed.total ? `the budget is below the ${money(t.needed.total, t.currency)} the test needs` : null)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    const err = await act(() => approveAdTest(t.id, { budget, underpowered_ok: Boolean(short) && anyway }))
    setBusy(false)
    if (err) setError(err)
    else onClose()
  }
  return (
    <Sheet title="Approve and start" onClose={onClose}>
      <form onSubmit={(e) => void submit(e)} className="mt-3 grid gap-3 text-sm">
        <p>{t.hypothesis}</p>
        <p className="text-muted">{needSentence(t)}. The ads start as soon as you approve.</p>
        <label>Budget ({t.currency})
          <input type="number" min={0.01} step={0.01} value={budget} required onChange={(e) => setBudget(e.target.value)}
            className={`${field} mt-1 block w-full`} />
        </label>
        {short && (
          <div role="alert" className="rounded-control bg-warn/12 p-3 text-warn">
            <p>Too small to trust: {short}. You may spend this money and learn nothing.</p>
            <label className="mt-2 flex min-h-11 items-center gap-2 font-medium">
              <input type="checkbox" checked={anyway} onChange={(e) => setAnyway(e.target.checked)} />
              Run underpowered anyway
            </label>
          </div>
        )}
        {error && <p role="alert" className="text-danger">{error}</p>}
        <Button type="submit" variant="primary" loading={busy} disabled={Boolean(short) && !anyway}>
          Approve and spend
        </Button>
      </form>
    </Sheet>
  )
}

/** The latest verdict in plain words: "B gets 24 % more clicks than A (between 10 % and 38 %), 95 % sure". */
function verdict(t: AdTest) {
  const e = t.result?.evaluation
  if (!e) return 'No numbers yet: the first ones come within an hour of the start'
  const [, more, unit] = METRIC[t.spec.primary_metric]
  const days = Math.floor(e.days)
  switch (e.status) {
    case 'winner': {
      const l = e.lift
      return l ? `${e.winner} gets ${pct(l.value)} more ${more} than ${l.vs} (between ${pct(l.ci_low)} and ` +
        `${pct(l.ci_high)}), ${pct(l.confidence)} sure` : `${e.winner} gets clearly more ${more} than the others`
    }
    case 'too_early': {
      const seen = Math.min(...Object.values(e.variants).map((v) => v.trials))
      return `Too early: ${days < t.spec.min_days ? `day ${days} of ${t.spec.min_days}, ` : ''}` +
        `${num(seen)} of ${num(t.spec.min_sample)} ${unit} per version`
    }
    case 'running': return 'No clear difference yet'
    case 'no_difference': return `No clear difference after ${days} days`
    default: return `The numbers could not be judged: ${e.error}`
  }
}

/** What each version shows: the post for a video test, the audience or placement otherwise. */
const versionLabel = (t: AdTest, v: { media_id: string; preset: string }, labels: Labels) =>
  t.variable === 'creative' ? `Post ${v.media_id}` : labels[v.preset] ?? v.preset

function Issues({ issues }: { issues: AdReviewIssue[] }) {
  return issues.map((i) => (
    <p key={i.ad_id} className="mt-1 flex flex-wrap items-center gap-2">
      <Chip tone={i.effective_status === 'DISAPPROVED' ? 'danger' : 'warn'}>
        {i.effective_status === 'DISAPPROVED' ? 'Meta rejected' : 'Meta limits'}
      </Chip>
      <span className="break-words text-muted">{i.reason}</span>
    </p>
  ))
}

function ResultsSheet({ id, labels, onClose }: { id: number; labels: Labels; onClose: () => void }) {
  const r = useLoad(() => getAdTest(id), id)
  const d = r.data
  const res = d?.result
  const spent = Number(d?.spend.reported ?? 0)
  const total = Number(d?.spend.budget ?? 0)
  const pv = Object.entries(res?.evaluation.p_values ?? {})
  return (
    <Sheet title={`Test #${id} results`} onClose={onClose}>
      {r.error && <p role="alert" className="mt-3 text-sm text-danger">{r.error}</p>}
      {!d ? !r.error && <Skeleton className="mt-3 h-24" /> : (
        <div className="mt-3 grid gap-3 text-sm">
          <p className="text-muted break-words">{d.hypothesis}</p>
          <p className="font-medium">{verdict(d)}.</p>
          <Issues issues={res?.review ?? []} />
          <div>
            <p>{money(spent, d.currency)} spent of {d.spend.budget ? money(d.spend.budget, d.currency) : 'no budget'}</p>
            <div role="progressbar" aria-label="Spend" aria-valuemin={0} aria-valuemax={100}
              aria-valuenow={total ? Math.min(100, Math.round((spent / total) * 100)) : 0}
              className="mt-1 h-2 overflow-hidden rounded-full bg-surface-2">
              <div className="h-full rounded-full bg-accent" style={{ width: `${total ? Math.min(100, (spent / total) * 100) : 0}%` }} />
            </div>
          </div>
          {res && (
            <table className="w-full text-left tabular-nums">
              <thead className="text-xs text-muted">
                <tr><th>Version</th><th>{METRIC[d.spec.primary_metric][0]}</th><th>Views</th><th>Spend</th></tr>
              </thead>
              <tbody>
                {Object.entries(res.variants).map(([name, v]) => {
                  const rate = res.evaluation.variants?.[name]?.rate
                  return (
                    <tr key={name}>
                      <td>{name} · {versionLabel(d, v, labels)}</td>
                      <td>{rate == null ? '–' : `${(rate * 100).toFixed(2)} %`}</td>
                      <td>{num(v.impressions)}</td>
                      <td>{money(v.spend, d.currency)}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
          {res && (
            <details className="text-muted">
              <summary className="cursor-pointer">Details</summary>
              {pv.length ? (
                <ul className="mt-1">
                  {pv.map(([name, p]) => <li key={name}>{name} vs the leader: p = {p.toFixed(4)}</li>)}
                </ul>
              ) : <p className="mt-1">No p-values before the planned sample is reached.</p>}
              <p className="mt-1">Last update {dateTime(res.synced_at)}.</p>
            </details>
          )}
        </div>
      )}
    </Sheet>
  )
}

function TestRow({ t, labels, act }: { t: AdTest; labels: Labels; act: Act }) {
  const [showing, setShowing] = useState(false)
  const [approving, setApproving] = useState(false)
  const [confirm, setConfirm] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const budget = t.budget_total ? money(t.budget_total, t.currency) : `needs about ${money(t.needed.total, t.currency)}`
  const winner = t.status === 'finished' ? t.result?.evaluation.winner : null
  const won = winner && t.result?.variants[winner]
  return (
    <li className="py-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <Chip tone={STATUS_TONE[t.status]}>{t.status}</Chip>
        {t.status === 'proposed' && <Chip tone="warn">
          {t.proposed_by === 'agent' ? 'Proposed by the AI' : 'Proposed by you'}, waiting for you
        </Chip>}
        {t.launched_by && <Chip tone={t.launched_by === 'agent' ? 'accent' : 'neutral'}>
          {t.launched_by === 'agent' ? 'Launched by the AI' : 'Launched by you'}
        </Chip>}
        {winner && <Chip tone="success">Winner: {winner}{won && ` (${versionLabel(t, won, labels)})`}</Chip>}
        <span className="font-medium break-words">{t.hypothesis}</span>
      </div>
      <p className="mt-1 text-muted">
        {humanize(t.variable)} · {t.variants.length} versions · {budget}{t.end_date && ` · ends ${t.end_date}`}
      </p>
      {t.reason && <p className="mt-1 text-muted">{t.reason}</p>}
      <Issues issues={t.result?.review ?? []} />
      <div className="mt-2 flex flex-wrap gap-2">
        {t.status === 'proposed'
          ? <Button size="sm" variant="primary" onClick={() => setApproving(true)}>Approve</Button>
          : <Button size="sm" onClick={() => setShowing(true)}>Results</Button>}
        {(t.status === 'proposed' || t.status === 'running') && (confirm ? (
          <>
            <span className="self-center">Cancel this test? Its ads stop.</span>
            <Button size="sm" variant="danger" onClick={() => void act(() => cancelAdTest(t.id)).then(setError)}>
              Yes, cancel it
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setConfirm(false)}>Keep it</Button>
          </>
        ) : <Button size="sm" variant="ghost" onClick={() => setConfirm(true)}>Cancel</Button>)}
      </div>
      {error && <p role="alert" className="mt-1 text-danger">{error}</p>}
      {approving && <ApproveSheet t={t} act={act} onClose={() => setApproving(false)} />}
      {showing && <ResultsSheet id={t.id} labels={labels} onClose={() => setShowing(false)} />}
    </li>
  )
}

function AuditLog({ version }: { version: number }) {
  const [offset, setOffset] = useState(0)
  const log = useLoad(() => getAdsAudit(offset, PAGE), `${version}:${offset}`)
  const d = log.data
  return (
    <Card as="section" aria-label="Audit log">
      <h2 className="font-semibold">What happened</h2>
      {log.error && <p role="alert" className="mt-2 text-sm text-danger">{log.error}</p>}
      {!d ? !log.error && <Skeleton className="mt-3 h-12" /> : d.rows.length === 0 ? (
        <p className="mt-2 text-sm text-muted">No ad actions yet.</p>
      ) : (
        <ul className="mt-2 divide-y divide-line/60 text-sm">
          {d.rows.map((r) => (
            <li key={r.id} className="py-2">
              <span className="font-medium">{humanize(r.action)}</span>
              {r.test_id != null && ` · test #${r.test_id}`}
              <span className="text-muted"> · {r.actor} · {dateTime(r.at)}</span>
              {Object.keys(r.detail).length > 0 && (
                <p className="text-muted break-words">
                  {Object.entries(r.detail).map(([k, v]) => `${humanize(k)}: ${String(v)}`).join(' · ')}
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
      {d && d.total > PAGE && (
        <div className="mt-2 flex items-center gap-2 text-sm">
          <Button size="sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>Newer</Button>
          <Button size="sm" disabled={offset + PAGE >= d.total} onClick={() => setOffset(offset + PAGE)}>Older</Button>
          <span className="text-muted">{offset + 1}–{Math.min(offset + PAGE, d.total)} of {d.total}</span>
        </div>
      )}
    </Card>
  )
}

/** src/ads/sync.py near_caps() in words: "Today's ad spend is at 85 % of the daily cap". */
function nearCaps(b: AdsBudget) {
  const share = (s: BudgetScope) => pct(Number(s.used) / Number(s.cap))
  const out = []
  if (b.near_cap.daily) out.push(`Today's ad spend is at ${share(b.daily)} of the daily cap`)
  if (b.near_cap.lifetime) out.push(`Total ad spend is at ${share(b.lifetime)} of the lifetime cap`)
  for (const t of b.tests) if (b.near_cap.tests.includes(t.test_id)) out.push(`Test #${t.test_id} is at ${share(t)} of its cap`)
  return out
}

/** The /ads page: budget and kill switch, propose and approve A/B tests, the audit log. */
export default function Ads() {
  const [version, setVersion] = useState(0)
  const [unset, setUnset] = useState(false)
  const [proposing, setProposing] = useState(false)
  const budget = useLoad(getAdsBudget, version)
  const tests = useLoad(listAdTests, version)
  const presets = useLoad(listAdPresets, 0).data ?? []
  const labels: Labels = Object.fromEntries(presets.map((p) => [p.id, p.label]))
  const waiting = tests.data?.filter((t) => t.status === 'proposed').length ?? 0

  // Runs one action, reloads everything; the error in plain words, or null.
  const act: Act = async (fn) => {
    try {
      await fn()
      return null
    } catch (e) {
      if (notConfigured(e)) setUnset(true)
      return adsError(e)
    } finally {
      setVersion((v) => v + 1)
    }
  }

  return (
    <>
      <PageHeader title="Ads" actions={<Button variant="primary" onClick={() => setProposing(true)}>Propose a test</Button>}>
        Paid A/B tests on your proven winners. The AI proposes them; nothing spends until you approve it.
      </PageHeader>
      <div className="grid gap-4">
        {unset && <p role="status" className="rounded-card bg-info/12 p-4 text-sm text-info">{H6_NOTE}</p>}
        {budget.data && nearCaps(budget.data).map((n) => (
          <p key={n} role="status" className="rounded-card bg-warn/12 p-4 text-sm text-warn">{n}.</p>
        ))}
        {budget.error ? <p role="alert" className="text-sm text-danger">{budget.error}</p>
          : <BudgetCard b={budget.data} act={act} />}
        <Card as="section" aria-label="Tests">
          <h2 className="font-semibold">Tests</h2>
          {waiting > 0 && (
            <p role="status" className="mt-1 text-sm text-warn">
              {waiting === 1 ? '1 proposal waits' : `${waiting} proposals wait`} for you: Approve launches it, Cancel drops it.
            </p>
          )}
          {tests.error && <p role="alert" className="mt-2 text-sm text-danger">{tests.error}</p>}
          {!tests.data ? !tests.error && <Skeleton className="mt-3 h-12" /> : tests.data.length === 0 ? (
            <div className="mt-3"><EmptyState title="No tests yet">Propose one from your winners.</EmptyState></div>
          ) : (
            <ul className="mt-2 divide-y divide-line/60">{tests.data.map((t) => <TestRow key={t.id} t={t} labels={labels} act={act} />)}</ul>
          )}
        </Card>
        <AuditLog version={version} />
      </div>
      {proposing && <ProposeSheet presets={presets} act={act} onClose={() => setProposing(false)} />}
    </>
  )
}
