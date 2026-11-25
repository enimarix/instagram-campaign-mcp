import { useState, type FormEvent } from 'react'
import { Link } from 'react-router'
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
  { id: 'creative', label: 'Vidéo' }, { id: 'audience', label: 'Public' }, { id: 'placement', label: 'Emplacement' },
]
const STATUS: Record<AdTestStatus, [Tone, string]> = {
  proposed: ['info', 'proposé'], approved: ['accent', 'approuvé'], running: ['success', 'en cours'],
  finished: ['neutral', 'terminé'], cancelled: ['neutral', 'annulé'],
}
// The audit log's actions and detail keys (src/ads/*.py audit() calls); unknown ones are humanized.
const ACTION: Record<string, string> = {
  kill: 'Arrêt de toutes les pubs', kill_enforced: 'Arrêt appliqué', unkill: 'Pubs réautorisées', propose: 'Test proposé',
  approve: 'Test approuvé', activate: 'Pub lancée', cancel: 'Test annulé', cancel_failed: 'Échec de l’annulation',
  release: 'Budget libéré', finish: 'Test terminé', finish_failed: 'Échec de la fin du test', settings: 'Réglages changés',
}
const DETAIL: Record<string, string> = {
  reason: 'Raison', paused: 'En pause', failed: 'Échecs', list_error: 'Erreur de liste', spent: 'Dépensé', stop: 'Arrêt',
  pause_failed: 'Pause échouée', winner: 'Gagnante', needed: 'Nécessaire', budget: 'Budget', per_variant: 'Par version',
  end_date: 'Fin', underpowered: 'Trop petit', media_id: 'Publication', campaign: 'Campagne', adset: 'Ensemble de pubs',
  changes: 'Changements',
}
const ACTOR: Record<string, string> = { owner: 'toi', agent: 'l’IA', system: 'le système' }
const REAUTH: Record<string, string> = {
  password_not_set: 'Mets d’abord UI_PASSWORD dans .env : les actions qui dépensent demandent le mot de passe du site.',
  password_required: 'Tape le mot de passe du site.',
  bad_password: 'Mauvais mot de passe.',
}
const H6_NOTE = 'Les pubs ne sont pas encore configurées. Étape H6 : mets INSTAGRAM_ACCESS_TOKEN (avec ads_read et ' +
  'ads_management) et META_AD_ACCOUNT_ID dans .env, puis fixe une limite de dépense sur le compte pub dans Meta.'
const PAGE = 20
// Per metric (src/ads/abtest.py METRICS): its name, what "more" counts, what a version's sample counts.
const METRIC: Record<AdMetric, [string, string, string]> = {
  ctr: ['CTR', 'clics', 'vues'], result_rate: ['Taux de résultat', 'résultats', 'vues'],
  conversion_rate: ['Taux de conversion', 'résultats', 'clics'],
}

const money = (v: string | number, currency: string) => {
  try {
    return new Intl.NumberFormat('fr-FR', { style: 'currency', currency }).format(Number(v))
  } catch {
    return `${v} ${currency}` // not an ISO currency code
  }
}
/** 1.2345 → "1,23" (2 digits). */
const decimal = (n: number, digits: number) =>
  n.toLocaleString('fr-FR', { minimumFractionDigits: digits, maximumFractionDigits: digits })
const notConfigured = (e: unknown) =>
  e instanceof ApiError && (e.code === 'ads_not_configured' || e.code === 'not_configured')

/** The server's refusal in plain words; the re-typed password errors are mapped. */
function adsError(e: unknown) {
  if (e instanceof ApiError && e.code === 'locked') {
    const s = (e.body as { retry_after?: number } | null)?.retry_after ?? 60
    return `Trop de mauvais mots de passe : réessaie dans ${Math.ceil(s / 60)} min.`
  }
  if (e instanceof ApiError && REAUTH[e.code]) return REAUTH[e.code]
  return errorMessage(e)
}

/** "Pour voir une hausse de 20 %, il faut environ 84,00 € sur 7 jours". */
const needSentence = (t: AdTest) =>
  `Pour voir une hausse de ${pct(t.min_lift)}, il faut environ ${money(t.needed.total, t.currency)} sur ${t.spec.min_days} jours`

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
    <Sheet title="Réautoriser les pubs" onClose={onClose}>
      <form onSubmit={(e) => void submit(e)} className="mt-3 grid gap-3 text-sm">
        <p className="text-muted">Les nouvelles dépenses redeviennent possibles, dans les plafonds. Tape le mot de passe du site.</p>
        <label>Mot de passe
          <input type="password" value={password} required autoComplete="current-password"
            onChange={(e) => setPassword(e.target.value)} className={`${field} mt-1 block w-full`} />
        </label>
        {error && <p role="alert" className="text-danger">{error}</p>}
        <Button type="submit" variant="primary" loading={busy}>Réautoriser les pubs</Button>
      </form>
    </Sheet>
  )
}

function Scope({ label, s, currency }: { label: string; s: BudgetScope; currency: string }) {
  return (
    <div>
      <dt className="text-xs font-medium text-muted">{label}</dt>
      <dd className="mt-1 font-semibold tabular-nums">{money(s.remaining, currency)} restants</dd>
      <dd className="text-xs text-muted">{money(s.used, currency)} utilisés sur {money(s.cap, currency)}</dd>
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
        Un test ne dépense qu’une fois que tu l’approuves, dans ces plafonds. <Link to="/settings#ads" className="text-accent underline">Les changer dans Réglages, Pubs</Link>.
      </p>
      {b.killed && (
        <div role="status" className="mt-2 rounded-control bg-danger/12 p-3 text-sm text-danger">
          Toutes les pubs sont arrêtées{b.killed_reason ? ` : ${b.killed_reason}` : ''}
          {b.killed_at && ` (depuis le ${dateTime(b.killed_at)})`}. Aucune nouvelle dépense tant que tu ne réautorises pas les pubs.
        </div>
      )}
      {zero && (
        <p className="mt-2 text-sm text-muted">
          Un plafond à 0 n’autorise aucune dépense : monte-le dans Réglages, Pubs.
        </p>
      )}
      <dl className="mt-3 grid grid-cols-2 gap-3 md:grid-cols-3">
        <Scope label={`Aujourd’hui (${b.day})`} s={b.daily} currency={c} />
        <Scope label="Au total" s={b.lifetime} currency={c} />
        <div>
          <dt className="text-xs font-medium text-muted">Par test</dt>
          <dd className="mt-1 font-semibold tabular-nums">{money(b.test_cap, c)} au maximum</dd>
        </div>
      </dl>
      {b.tests.length > 0 && (
        <ul className="mt-3 text-sm text-muted">
          {b.tests.map((t) => (
            <li key={t.test_id}>Test #{t.test_id} : {money(t.used, c)} utilisés, {money(t.remaining, c)} restants</li>
          ))}
        </ul>
      )}
      <div className="mt-4 flex flex-wrap items-center gap-2">
        {b.killed ? (
          <Button variant="primary" onClick={() => setUnkill(true)}>Réautoriser les pubs</Button>
        ) : (
          <>
            <input aria-label="Raison (facultatif)" value={reason} maxLength={200} placeholder="raison (facultatif)"
              onChange={(e) => setReason(e.target.value)} className={`${field} min-w-0 flex-1 md:flex-none`} />
            <Button variant="danger" size="lg" onClick={() => void kill()}>Arrêter toutes les pubs</Button>
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
      <Sheet title="Test proposé" onClose={onClose}>
        <p className="mt-3 font-medium">{needSentence(done)}.</p>
        {done.underpowered && <p role="alert" className="mt-2 text-sm text-warn">Trop petit : {done.underpowered}.</p>}
        <p className="mt-2 text-sm text-muted">Rien n’est dépensé tant que tu ne l’approuves pas dans la liste des tests.</p>
        <Button variant="primary" className="mt-4 w-full" onClick={onClose}>OK</Button>
      </Sheet>
    )
  return (
    <Sheet title="Proposer un test" onClose={onClose}>
      <form onSubmit={(e) => void submit(e)} className="mt-3 grid gap-3 text-sm">
        <Tabs label="Ce qui change" tabs={VARIABLES} value={variable}
          onChange={(v) => { setVariable(v); setMedias([]); setCompared([]) }} />
        <fieldset>
          <legend className="font-medium">{creative ? 'Choisis 2 à 4 gagnantes' : 'Choisis une gagnante'}</legend>
          {winners.error && <p role="alert" className="text-danger">{winners.error}</p>}
          {!winners.data ? !winners.error && <Skeleton className="h-12" /> : winners.data.length === 0 ? (
            <p className="text-muted">Pas encore de gagnante : un Reel le devient quand il bat le compte, une fois ses chiffres mûrs.</p>
          ) : (
            <ul className="mt-1 grid gap-1">
              {winners.data.map((w) => (
                <li key={w.media_id}>
                  <label className="flex min-h-11 items-center gap-2">
                    <input type={creative ? 'checkbox' : 'radio'} name="winner" checked={medias.includes(w.media_id)}
                      onChange={() => setMedias(creative ? toggle(medias, w.media_id) : [w.media_id])} />
                    {w.thumbnail_url && <img src={w.thumbnail_url} alt="" className="h-10 w-6 shrink-0 rounded object-cover" />}
                    <span className="min-w-0 truncate">{w.caption || `Publication ${w.media_id}`}</span>
                    <span className="ml-auto shrink-0 text-muted">{dateTime(w.posted_at)}</span>
                  </label>
                </li>
              ))}
            </ul>
          )}
        </fieldset>
        {creative ? (
          <label>Qui le voit
            <select value={preset} onChange={(e) => setPicked(e.target.value)} className={`${field} mt-1 block w-full`}>
              {presets.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
            </select>
          </label>
        ) : (
          <fieldset>
            <legend className="font-medium">Comparer</legend>
            <div className="mt-1 flex flex-wrap gap-2">
              {presets.filter((p) => p.varies.includes(variable)).map((p) => (
                <Chip key={p.id} pressed={compared.includes(p.id)} onClick={() => setCompared(toggle(compared, p.id))}>
                  {p.label}
                </Chip>
              ))}
            </div>
          </fieldset>
        )}
        <label>Ce que tu attends
          <textarea value={hypothesis} required maxLength={500} rows={2} onChange={(e) => setHypothesis(e.target.value)}
            placeholder="la vidéo du boss fait plus de clics" className={`${field} mt-1 block w-full py-2`} />
        </label>
        <label>Plus petit écart qui vaut la peine (%)
          <input type="number" min={1} max={500} value={lift} required onChange={(e) => setLift(e.target.value)}
            className={`${field} mt-1 block w-full`} />
        </label>
        {error && <p role="alert" className="text-danger">{error}</p>}
        <Button type="submit" variant="primary" loading={busy} disabled={!ready}>Calculer le budget</Button>
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
    ?? (Number(budget) < t.needed.total ? `le budget est sous les ${money(t.needed.total, t.currency)} dont le test a besoin` : null)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    const err = await act(() => approveAdTest(t.id, { budget, underpowered_ok: Boolean(short) && anyway }))
    setBusy(false)
    if (err) setError(err)
    else onClose()
  }
  return (
    <Sheet title="Approuver et lancer" onClose={onClose}>
      <form onSubmit={(e) => void submit(e)} className="mt-3 grid gap-3 text-sm">
        <p>{t.hypothesis}</p>
        <p className="text-muted">{needSentence(t)}. Les pubs démarrent dès que tu approuves.</p>
        <label>Budget ({t.currency})
          <input type="number" min={0.01} step={0.01} value={budget} required onChange={(e) => setBudget(e.target.value)}
            className={`${field} mt-1 block w-full`} />
        </label>
        {short && (
          <div role="alert" className="rounded-control bg-warn/12 p-3 text-warn">
            <p>Trop petit pour s’y fier : {short}. Tu risques de dépenser cet argent sans rien apprendre.</p>
            <label className="mt-2 flex min-h-11 items-center gap-2 font-medium">
              <input type="checkbox" checked={anyway} onChange={(e) => setAnyway(e.target.checked)} />
              Lancer quand même
            </label>
          </div>
        )}
        {error && <p role="alert" className="text-danger">{error}</p>}
        <Button type="submit" variant="primary" loading={busy} disabled={Boolean(short) && !anyway}>
          Approuver et dépenser
        </Button>
      </form>
    </Sheet>
  )
}

/** The latest verdict in plain words: "B fait 24 % de clics de plus que A (entre 10 % et 38 %), sûr à 95 %". */
function verdict(t: AdTest) {
  const e = t.result?.evaluation
  if (!e) return 'Pas encore de chiffres : les premiers arrivent dans l’heure qui suit le lancement'
  const [, more, unit] = METRIC[t.spec.primary_metric]
  const days = Math.floor(e.days)
  switch (e.status) {
    case 'winner': {
      const l = e.lift
      return l ? `${e.winner} fait ${pct(l.value)} de ${more} de plus que ${l.vs} (entre ${pct(l.ci_low)} et ` +
        `${pct(l.ci_high)}), sûr à ${pct(l.confidence)}` : `${e.winner} fait nettement plus de ${more} que les autres`
    }
    case 'too_early': {
      const seen = Math.min(...Object.values(e.variants).map((v) => v.trials))
      return `Trop tôt : ${days < t.spec.min_days ? `jour ${days} sur ${t.spec.min_days}, ` : ''}` +
        `${num(seen)} ${unit} sur ${num(t.spec.min_sample)} par version`
    }
    case 'running': return 'Pas encore de différence nette'
    case 'no_difference': return `Pas de différence nette après ${days} jours`
    default: return `Les chiffres n’ont pas pu être jugés : ${e.error}`
  }
}

/** What each version shows: the post for a video test, the audience or placement otherwise. */
const versionLabel = (t: AdTest, v: { media_id: string; preset: string }, labels: Labels) =>
  t.variable === 'creative' ? `Publication ${v.media_id}` : labels[v.preset] ?? v.preset

function Issues({ issues }: { issues: AdReviewIssue[] }) {
  return issues.map((i) => (
    <p key={i.ad_id} className="mt-1 flex flex-wrap items-center gap-2">
      <Chip tone={i.effective_status === 'DISAPPROVED' ? 'danger' : 'warn'}>
        {i.effective_status === 'DISAPPROVED' ? 'Refusée par Meta' : 'Limitée par Meta'}
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
    <Sheet title={`Résultats du test #${id}`} onClose={onClose}>
      {r.error && <p role="alert" className="mt-3 text-sm text-danger">{r.error}</p>}
      {!d ? !r.error && <Skeleton className="mt-3 h-24" /> : (
        <div className="mt-3 grid gap-3 text-sm">
          <p className="text-muted break-words">{d.hypothesis}</p>
          <p className="font-medium">{verdict(d)}.</p>
          <Issues issues={res?.review ?? []} />
          <div>
            <p>{money(spent, d.currency)} dépensés sur {d.spend.budget ? money(d.spend.budget, d.currency) : 'aucun budget'}</p>
            <div role="progressbar" aria-label="Dépense" aria-valuemin={0} aria-valuemax={100}
              aria-valuenow={total ? Math.min(100, Math.round((spent / total) * 100)) : 0}
              className="mt-1 h-2 overflow-hidden rounded-full bg-surface-2">
              <div className="h-full rounded-full bg-accent" style={{ width: `${total ? Math.min(100, (spent / total) * 100) : 0}%` }} />
            </div>
          </div>
          {res && (
            <table className="w-full text-left tabular-nums">
              <thead className="text-xs text-muted">
                <tr><th>Version</th><th>{METRIC[d.spec.primary_metric][0]}</th><th>Vues</th><th>Dépense</th></tr>
              </thead>
              <tbody>
                {Object.entries(res.variants).map(([name, v]) => {
                  const rate = res.evaluation.variants?.[name]?.rate
                  return (
                    <tr key={name}>
                      <td>{name} · {versionLabel(d, v, labels)}</td>
                      <td>{rate == null ? '–' : `${decimal(rate * 100, 2)} %`}</td>
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
              <summary className="cursor-pointer">Détails</summary>
              {pv.length ? (
                <ul className="mt-1">
                  {pv.map(([name, p]) => <li key={name}>{name} vs le meneur : p = {decimal(p, 4)}</li>)}
                </ul>
              ) : <p className="mt-1">Pas de p-values avant d’atteindre l’échantillon prévu.</p>}
              <p className="mt-1">Dernière mise à jour : {dateTime(res.synced_at)}.</p>
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
  const budget = t.budget_total ? money(t.budget_total, t.currency) : `il faut environ ${money(t.needed.total, t.currency)}`
  const winner = t.status === 'finished' ? t.result?.evaluation.winner : null
  const won = winner && t.result?.variants[winner]
  return (
    <li className="py-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <Chip tone={STATUS[t.status][0]}>{STATUS[t.status][1]}</Chip>
        {t.status === 'proposed' && <Chip tone="warn">
          {t.proposed_by === 'agent' ? 'Proposé par l’IA' : 'Proposé par toi'}, t’attend
        </Chip>}
        {t.launched_by && <Chip tone={t.launched_by === 'agent' ? 'accent' : 'neutral'}>
          {t.launched_by === 'agent' ? 'Lancé par l’IA' : 'Lancé par toi'}
        </Chip>}
        {winner && <Chip tone="success">Gagnante : {winner}{won && ` (${versionLabel(t, won, labels)})`}</Chip>}
        <span className="font-medium break-words">{t.hypothesis}</span>
      </div>
      <p className="mt-1 text-muted">
        {VARIABLES.find((v) => v.id === t.variable)?.label ?? humanize(t.variable)} · {t.variants.length} versions · {budget}{t.end_date && ` · fin le ${t.end_date}`}
      </p>
      {t.reason && <p className="mt-1 text-muted">{t.reason}</p>}
      <Issues issues={t.result?.review ?? []} />
      <div className="mt-2 flex flex-wrap gap-2">
        {t.status === 'proposed'
          ? <Button size="sm" variant="primary" onClick={() => setApproving(true)}>Approuver</Button>
          : <Button size="sm" onClick={() => setShowing(true)}>Résultats</Button>}
        {(t.status === 'proposed' || t.status === 'running') && (confirm ? (
          <>
            <span className="self-center">Annuler ce test ? Ses pubs s’arrêtent.</span>
            <Button size="sm" variant="danger" onClick={() => void act(() => cancelAdTest(t.id)).then(setError)}>
              Oui, l’annuler
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setConfirm(false)}>Le garder</Button>
          </>
        ) : <Button size="sm" variant="ghost" onClick={() => setConfirm(true)}>Annuler</Button>)}
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
    <Card as="section" aria-label="Ce qui s’est passé">
      <h2 className="font-semibold">Ce qui s’est passé</h2>
      {log.error && <p role="alert" className="mt-2 text-sm text-danger">{log.error}</p>}
      {!d ? !log.error && <Skeleton className="mt-3 h-12" /> : d.rows.length === 0 ? (
        <p className="mt-2 text-sm text-muted">Pas encore d’action sur les pubs.</p>
      ) : (
        <ul className="mt-2 divide-y divide-line/60 text-sm">
          {d.rows.map((r) => (
            <li key={r.id} className="py-2">
              <span className="font-medium">{ACTION[r.action] ?? humanize(r.action)}</span>
              {r.test_id != null && ` · test #${r.test_id}`}
              <span className="text-muted"> · {ACTOR[r.actor] ?? r.actor} · {dateTime(r.at)}</span>
              {Object.keys(r.detail).length > 0 && (
                <p className="text-muted break-words">
                  {Object.entries(r.detail).map(([k, v]) => `${DETAIL[k] ?? humanize(k)} : ${String(v)}`).join(' · ')}
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
      {d && d.total > PAGE && (
        <div className="mt-2 flex items-center gap-2 text-sm">
          <Button size="sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>Plus récentes</Button>
          <Button size="sm" disabled={offset + PAGE >= d.total} onClick={() => setOffset(offset + PAGE)}>Plus anciennes</Button>
          <span className="text-muted">{offset + 1}–{Math.min(offset + PAGE, d.total)} sur {d.total}</span>
        </div>
      )}
    </Card>
  )
}

/** src/ads/sync.py near_caps() in words: "La dépense pub du jour est à 85 % du plafond quotidien". */
function nearCaps(b: AdsBudget) {
  const share = (s: BudgetScope) => pct(Number(s.used) / Number(s.cap))
  const out = []
  if (b.near_cap.daily) out.push(`La dépense pub du jour est à ${share(b.daily)} du plafond quotidien`)
  if (b.near_cap.lifetime) out.push(`La dépense pub totale est à ${share(b.lifetime)} du plafond total`)
  for (const t of b.tests) if (b.near_cap.tests.includes(t.test_id)) out.push(`Le test #${t.test_id} est à ${share(t)} de son plafond`)
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
      <PageHeader title="Pubs" actions={<Button variant="primary" onClick={() => setProposing(true)}>Proposer un test</Button>}>
        Des tests A/B payants sur tes gagnantes confirmées. L’IA les propose ; rien n’est dépensé tant que tu n’approuves pas.
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
              {waiting === 1 ? '1 proposition t’attend' : `${waiting} propositions t’attendent`} : Approuver la lance, Annuler l’abandonne.
            </p>
          )}
          {tests.error && <p role="alert" className="mt-2 text-sm text-danger">{tests.error}</p>}
          {!tests.data ? !tests.error && <Skeleton className="mt-3 h-12" /> : tests.data.length === 0 ? (
            <div className="mt-3"><EmptyState title="Pas encore de test">Propose-en un à partir de tes gagnantes.</EmptyState></div>
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
