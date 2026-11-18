import { useState, type FormEvent } from 'react'
import {
  ApiError, approveAdTest, cancelAdTest, errorMessage, getAdsAudit, getAdsBudget, killAds, listAdTests, listAdWinners,
  proposeAdTest, unkillAds, type AdsBudget, type AdTest, type AdTestStatus, type AdVariable, type BudgetScope,
} from '../api/client'
import { Button } from '../ui/Button'
import { Card, EmptyState, Skeleton } from '../ui/Card'
import { Chip } from '../ui/Chip'
import { PageHeader } from '../ui/PageHeader'
import { Sheet } from '../ui/Sheet'
import { field, type Tone } from '../ui/styles'
import { Tabs } from '../ui/Tabs'
import { dateTime, humanize, pct, useLoad } from './load'

// Steps 094 (API) and 094b (this page). No results view yet: 095b adds it.
// ponytail: mirrors PRESETS in src/ads/promote.py (no route lists them); the server re-checks.
const PRESETS: Record<string, string> = {
  fr_reels: 'France, Reels',
  fr_feed_reels: 'France, Feed and Reels',
  francophone_reels: 'France, Belgium, Switzerland, Luxembourg, Reels',
}
// Presets that differ in only that one thing, per variable.
const VARIES: Record<Exclude<AdVariable, 'creative'>, string[]> = {
  audience: ['fr_reels', 'francophone_reels'],
  placement: ['fr_reels', 'fr_feed_reels'],
}
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
      {b.killed && (
        <div role="status" className="mt-2 rounded-control bg-danger/12 p-3 text-sm text-danger">
          All ads are stopped{b.killed_reason ? `: ${b.killed_reason}` : ''}
          {b.killed_at && ` (since ${dateTime(b.killed_at)})`}. No new spend until you allow ads again.
        </div>
      )}
      {zero && (
        <p className="mt-2 text-sm text-muted">
          Set ADS_DAILY_CAP / ADS_TEST_CAP / ADS_LIFETIME_CAP in .env to allow spend.
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

function ProposeSheet({ act, onClose }: { act: Act; onClose: () => void }) {
  const winners = useLoad(listAdWinners, 0)
  const [variable, setVariable] = useState<AdVariable>('creative')
  const [medias, setMedias] = useState<string[]>([])
  const [presets, setPresets] = useState<string[]>([])
  const [preset, setPreset] = useState('fr_reels')
  const [hypothesis, setHypothesis] = useState('')
  const [lift, setLift] = useState('20')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState<AdTest>()
  const creative = variable === 'creative'
  const toggle = (list: string[], v: string) => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v])
  const variants = creative
    ? medias.map((media_id) => ({ media_id, preset }))
    : presets.map((p) => ({ media_id: medias[0], preset: p }))
  const ready = hypothesis.trim() && (creative ? medias.length >= 2 && medias.length <= 4 : medias.length === 1 && presets.length >= 2)

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
          onChange={(v) => { setVariable(v); setMedias([]); setPresets([]) }} />
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
            <select value={preset} onChange={(e) => setPreset(e.target.value)} className={`${field} mt-1 block w-full`}>
              {Object.entries(PRESETS).map(([id, label]) => <option key={id} value={id}>{label}</option>)}
            </select>
          </label>
        ) : (
          <fieldset>
            <legend className="font-medium">Compare</legend>
            <div className="mt-1 flex flex-wrap gap-2">
              {VARIES[variable].map((p) => (
                <Chip key={p} pressed={presets.includes(p)} onClick={() => setPresets(toggle(presets, p))}>{PRESETS[p]}</Chip>
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
  const [password, setPassword] = useState('')
  const [anyway, setAnyway] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const short = t.underpowered
    ?? (Number(budget) < t.needed.total ? `the budget is below the ${money(t.needed.total, t.currency)} the test needs` : null)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    const err = await act(() => approveAdTest(t.id, { budget, password, underpowered_ok: Boolean(short) && anyway }))
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
        <label>Password
          <input type="password" value={password} required autoComplete="current-password"
            onChange={(e) => setPassword(e.target.value)} className={`${field} mt-1 block w-full`} />
        </label>
        {error && <p role="alert" className="text-danger">{error}</p>}
        <Button type="submit" variant="primary" loading={busy} disabled={Boolean(short) && !anyway}>
          Approve and spend
        </Button>
      </form>
    </Sheet>
  )
}

function TestRow({ t, act }: { t: AdTest; act: Act }) {
  const [approving, setApproving] = useState(false)
  const [confirm, setConfirm] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const budget = t.budget_total ? money(t.budget_total, t.currency) : `needs about ${money(t.needed.total, t.currency)}`
  return (
    <li className="py-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <Chip tone={STATUS_TONE[t.status]}>{t.status}</Chip>
        <span className="font-medium break-words">{t.hypothesis}</span>
      </div>
      <p className="mt-1 text-muted">
        {humanize(t.variable)} · {t.variants.length} versions · {budget}{t.end_date && ` · ends ${t.end_date}`}
      </p>
      {t.reason && <p className="mt-1 text-muted">{t.reason}</p>}
      {(t.status === 'proposed' || t.status === 'running') && (
        <div className="mt-2 flex flex-wrap gap-2">
          {t.status === 'proposed' && <Button size="sm" variant="primary" onClick={() => setApproving(true)}>Approve</Button>}
          {confirm ? (
            <>
              <span className="self-center">Cancel this test? Its ads stop.</span>
              <Button size="sm" variant="danger" onClick={() => void act(() => cancelAdTest(t.id)).then(setError)}>
                Yes, cancel it
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setConfirm(false)}>Keep it</Button>
            </>
          ) : <Button size="sm" variant="ghost" onClick={() => setConfirm(true)}>Cancel</Button>}
        </div>
      )}
      {error && <p role="alert" className="mt-1 text-danger">{error}</p>}
      {approving && <ApproveSheet t={t} act={act} onClose={() => setApproving(false)} />}
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

/** The /ads page: budget and kill switch, propose and approve A/B tests, the audit log. */
export default function Ads() {
  const [version, setVersion] = useState(0)
  const [unset, setUnset] = useState(false)
  const [proposing, setProposing] = useState(false)
  const budget = useLoad(getAdsBudget, version)
  const tests = useLoad(listAdTests, version)

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
        Paid A/B tests on your proven winners. Nothing spends until you approve it with your password.
      </PageHeader>
      <div className="grid gap-4">
        {unset && <p role="status" className="rounded-card bg-info/12 p-4 text-sm text-info">{H6_NOTE}</p>}
        {budget.error ? <p role="alert" className="text-sm text-danger">{budget.error}</p>
          : <BudgetCard b={budget.data} act={act} />}
        <Card as="section" aria-label="Tests">
          <h2 className="font-semibold">Tests</h2>
          {tests.error && <p role="alert" className="mt-2 text-sm text-danger">{tests.error}</p>}
          {!tests.data ? !tests.error && <Skeleton className="mt-3 h-12" /> : tests.data.length === 0 ? (
            <div className="mt-3"><EmptyState title="No tests yet">Propose one from your winners.</EmptyState></div>
          ) : (
            <ul className="mt-2 divide-y divide-line/60">{tests.data.map((t) => <TestRow key={t.id} t={t} act={act} />)}</ul>
          )}
        </Card>
        <AuditLog version={version} />
      </div>
      {proposing && <ProposeSheet act={act} onClose={() => setProposing(false)} />}
    </>
  )
}
