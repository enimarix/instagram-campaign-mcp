import { useState } from 'react'
import { Link, useParams } from 'react-router'
import {
  ApiError, errorMessage, getAnalyticsPost, listAnalyticsPosts, type AnalyticsPost, type PostDetail,
} from '../api/client'
import { localDate, safeUrl } from '../inbox/ui'
import { Button } from '../ui/Button'
import { Card } from '../ui/Card'
import { Chip } from '../ui/Chip'
import { PageHeader } from '../ui/PageHeader'
import { card, field, link, type Tone } from '../ui/styles'
import { Body, Line, Section } from './Analytics'
import { clock, FINDING, num, pct, POST_TYPES, postVerdict, tagName, tagValue, useLoad, VERDICT_TONE } from './load'

const PAGE = 20
const SORTS = [
  ['posted_at', 'Date de publication'], ['views', 'Vues'], ['reach', 'Portée'],
  ['engagement_index', 'Indice d’engagement'], ['watch_ratio', 'Taux de visionnage'], ['view_rate', 'Taux de vue'],
]
// [param, label, [value, option label][]]; '' = all
const FILTERS = [
  ['type', 'Type', [['', 'Tous les types'], ...['REELS', 'TRIAL', 'FEED', 'STORY'].map((t) => [t, POST_TYPES[t]])]],
  ['verdict', 'Verdict', [['', 'Tous les verdicts'], ...['winner', 'promising', 'average', 'weak', 'inconclusive',
    'no_signal', 'too_early', 'incomplete', 'no_baseline'].map((v) => [v, postVerdict(v)])]],
  ['tagged', 'Tags', [['', 'Avec ou sans tags'], ['true', 'Studio (avec tags)'], ['false', 'Sans tags']]],
] as const
type Filters = Record<(typeof FILTERS)[number][0], string>

const day = (iso: string | null) => (iso ? localDate(new Date(iso)) : '–')
const ratio = (n: number | null | undefined) => (n == null ? '–' : `${num(n)}×`)
const age = (h: number) => (h < 48 ? `${Math.round(h)} h` : `${Math.round(h / 24)} j`)
const CONFIDENCE: Record<string, string> = { low: 'faible', medium: 'moyenne', high: 'forte' }
const detailPath = (id: string) => `/analytics/posts/${encodeURIComponent(id)}`

function Verdict({ v }: { v: string }) {
  return <Chip tone={VERDICT_TONE[v]}>{postVerdict(v)}</Chip>
}

/** A trial Reel (shown to non-followers first): scored against other trials only. */
function Trial({ p }: { p: { group: string } }) {
  return p.group === 'TRIAL' ? <Chip tone="explore" title="Reel d’essai : montré d’abord aux non-abonnés, comparé seulement aux autres essais">essai</Chip> : null
}

const COLUMNS: [string, (p: AnalyticsPost) => string][] = [
  ['Vues', (p) => num(p.metrics.views)], ['Portée', (p) => num(p.metrics.reach)],
  ['Ind. engagement', (p) => ratio(p.engagement_index)], ['Visionnage', (p) => pct(p.watch_ratio)],
  ['Taux de vue', (p) => ratio(p.view_rate)],
]

// marker colours, written out so Tailwind sees them
const MARKER: Record<Tone, string> = {
  neutral: 'bg-fg', accent: 'bg-accent', success: 'bg-success', warn: 'bg-warn', danger: 'bg-danger', info: 'bg-info', explore: 'bg-explore', idea: 'bg-idea',
}

/** "Why viewers left": the description, the timeline bar with a marker per finding, the findings. */
function Retention({ p }: { p: PostDetail }) {
  const events = p.timeline ?? []
  // a cut timeline ends with a bare {e: "+N more"}: listed, not drawn
  const timed = events.flatMap((e) => (e.t == null ? [] : [{ ...e, t: e.t, d: e.d ?? 0 }]))
  const end = p.duration || Math.max(0, ...timed.map((e) => e.t + e.d))
  const at = (s: number) => `${Math.min(100, (s / end) * 100)}%`
  return (
    <Section title="Pourquoi les spectateurs sont partis">
      {p.description && <p className="mt-1 max-w-prose text-sm">{p.description}</p>}
      {timed.length > 0 && end > 0 && (
        <>
          {/* the bar is decorative: the list below says the same */}
          <div aria-hidden className="relative mt-3 h-8 overflow-hidden rounded-control bg-surface-2">
            {timed.map((e, i) => (
              <div key={i} title={e.e} className={`absolute inset-y-0 border-r border-surface ${i % 2 ? 'bg-line' : 'bg-line/50'}`}
                style={{ left: at(e.t), width: at(e.d) }} />
            ))}
            {p.retention.filter((f) => f.at_s != null).map((f, i) => (
              <div key={i} title={`${FINDING[f.kind][1]} à ${clock(f.at_s!)}`}
                className={`absolute inset-y-0 w-1 -translate-x-1/2 ${MARKER[FINDING[f.kind][0]]}`} style={{ left: at(f.at_s!) }} />
            ))}
          </div>
          <div className="mt-0.5 flex justify-between text-xs text-muted tabular-nums"><span>0:00</span><span>{clock(end)}</span></div>
          <ol aria-label="Moments de la vidéo" className="mt-2 space-y-0.5 text-xs text-muted">
            {events.map((e, i) => (
              <li key={i}>{e.t != null && <span className="tabular-nums">{clock(e.t)}–{clock(e.t + (e.d ?? 0))} </span>}{e.e}</li>
            ))}
          </ol>
        </>
      )}
      {p.retention.length === 0 ? <p className="mt-2 text-sm text-muted">Pas encore de constats : ils arrivent quand le Reel a mûri.</p> : (
        <ul aria-label="Constats" className="mt-3 space-y-2">
          {p.retention.map((f, i) => (
            <Card as="li" key={i} className="flex flex-wrap items-start gap-2 text-sm">
              <Chip tone={FINDING[f.kind][0]}>{FINDING[f.kind][1]}{f.at_s != null && ` · ${clock(f.at_s)}`}</Chip>
              <Chip>confiance {CONFIDENCE[f.confidence] ?? f.confidence}</Chip>
              <p className="w-full">{f.text}</p>
            </Card>
          ))}
        </ul>
      )}
    </Section>
  )
}

/** All posts: cards on a phone, a table from md up; sort, filters and "Load more". */
export default function Posts() {
  const [sortKey, setSortKey] = useState('posted_at')
  const [desc, setDesc] = useState(true)
  const [filters, setFilters] = useState<Filters>({ type: '', verdict: '', tagged: '' })
  const query = { sort: `${desc ? '-' : ''}${sortKey}`, ...filters }
  const key = JSON.stringify(query)
  const first = useLoad(() => listAnalyticsPosts({ ...query, offset: 0, limit: PAGE }), key)
  // pages fetched by "Load more" for the current query; a new query starts over
  const [more, setMore] = useState<{ key: string; posts: AnalyticsPost[]; busy?: boolean; error?: string }>({ key, posts: [] })
  const extra = more.key === key ? more : { key, posts: [] }
  const posts = [...(first.data?.posts ?? []), ...extra.posts]

  const loadMore = () => {
    setMore({ ...extra, busy: true, error: undefined })
    listAnalyticsPosts({ ...query, offset: posts.length, limit: PAGE }).then(
      // a post published meanwhile shifts the offsets: skip rows already shown
      (r) => setMore((m) => (m.key === key
        ? { key, posts: [...m.posts, ...r.posts.filter((p) => !posts.some((q) => q.media_id === p.media_id))] } : m)),
      (e: unknown) => setMore((m) => (m.key === key ? { ...m, busy: false, error: errorMessage(e) } : m)))
  }

  return (
    <section>
      <PageHeader title="Publications" back={{ to: '/analytics', label: 'Statistiques' }} />
      <div className="flex flex-wrap gap-2">
        <select aria-label="Trier par" className={field} value={sortKey} onChange={(e) => setSortKey(e.target.value)}>
          {SORTS.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
        </select>
        <Button onClick={() => setDesc(!desc)}>{desc ? 'Du plus haut au plus bas' : 'Du plus bas au plus haut'}</Button>
        {FILTERS.map(([param, label, options]) => (
          <select key={param} aria-label={label} className={field} value={filters[param]}
            onChange={(e) => setFilters({ ...filters, [param]: e.target.value })}>
            {options.map(([v, text]) => <option key={v} value={v}>{text}</option>)}
          </select>
        ))}
      </div>

      <Body s={first} empty={(d) => d.total === 0 && 'Aucune publication ne correspond.'}>
        {(d) => (
          <>
            <ul aria-label="Publications" className="mt-4 space-y-2 md:hidden">
              {posts.map((p) => (
                <Card as="li" key={p.media_id} className="flex gap-3 text-sm">
                  {p.thumbnail_url && <img src={p.thumbnail_url} alt="" className="h-20 w-11 shrink-0 rounded-lg object-cover" />}
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2"><Verdict v={p.verdict} /><Trial p={p} /><span className="text-muted">{day(p.posted_at)}</span></div>
                    <Link to={detailPath(p.media_id)} className={`mt-1 block min-h-11 truncate leading-[2.75rem] ${link}`}>{p.caption || 'Publication sans titre'}</Link>
                    <p className="text-xs text-muted">{COLUMNS.map(([k, v]) => `${k} ${v(p)}`).join(' · ')}</p>
                  </div>
                </Card>
              ))}
            </ul>
            <div className={`${card} mt-4 hidden overflow-hidden md:block`}>
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr className="bg-surface-2 text-left text-xs text-muted">
                  <th className="p-2">Publication</th><th className="p-2">Publiée le</th><th className="p-2">Verdict</th>
                  {COLUMNS.map(([k]) => <th key={k} className="p-2 text-right">{k}</th>)}
                </tr>
              </thead>
              <tbody>
                {posts.map((p) => (
                  <tr key={p.media_id} className="border-t border-line/60 hover:bg-surface-2/50">
                    <td className="max-w-xs p-2">
                      <Link to={detailPath(p.media_id)} className={`flex items-center gap-2 ${link}`}>
                        {p.thumbnail_url && <img src={p.thumbnail_url} alt="" className="h-10 w-6 shrink-0 rounded object-cover" />}
                        <span className="truncate">{p.caption || 'Publication sans titre'}</span>
                      </Link>
                    </td>
                    <td className="p-2 whitespace-nowrap">{day(p.posted_at)}</td>
                    <td className="p-2"><span className="flex flex-wrap gap-1"><Verdict v={p.verdict} /><Trial p={p} /></span></td>
                    {COLUMNS.map(([k, v]) => <td key={k} className="p-2 text-right tabular-nums">{v(p)}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
            <p className="mt-2 text-xs text-muted">{posts.length} sur {d.total}</p>
            {extra.error && <p role="alert" className="text-sm text-danger">Impossible de charger la suite : {extra.error}</p>}
            {posts.length < d.total && (
              <Button className="mt-2" loading={extra.busy} onClick={loadMore}>{extra.busy ? 'Chargement…' : 'Charger plus'}</Button>
            )}
          </>
        )}
      </Body>
    </section>
  )
}

/** One post: growth curve, tags and hypothesis, the owner's feedback and the video. */
export function PostPage() {
  const { id = '' } = useParams()
  const s = useLoad(() => getAnalyticsPost(id).catch((e: unknown) => {
    if (e instanceof ApiError && e.status === 404) return null
    throw e
  }), id)
  return (
    <section>
      <PageHeader title="Publication" back={{ to: '/analytics/posts', label: 'Publications' }} />
      <Body s={s} empty={(p) => p === null && 'Publication introuvable.'}>{(p) => p && <Detail p={p} />}</Body>
    </section>
  )
}

function Detail({ p }: { p: PostDetail }) {
  const href = safeUrl(p.permalink)
  const tags = Object.entries(p.tags ?? {}).filter(([, v]) => v)
  return (
    <>
      <p className="text-sm text-muted">
        {day(p.posted_at)} · {POST_TYPES[p.group === 'TRIAL' ? 'REELS' : p.group] ?? p.group}{p.deleted && ' · supprimée d’Instagram'} <Trial p={p} />
      </p>
      {p.caption && <p className="mt-1 whitespace-pre-line text-sm">{p.caption}</p>}

      <Section title="Vidéo">
        {p.preview_url ? (
          <>
            <video src={p.preview_url} poster={p.thumbnail_url ?? undefined} controls playsInline preload="metadata"
              aria-label="Vidéo du studio" className="mt-2 max-h-[70vh] w-full max-w-xs rounded-card bg-black shadow-card" />
            {p.asset_id !== null && <Link to={`/assets/${p.asset_id}`} className={`inline-flex min-h-11 items-center ${link}`}>Ouvrir dans le studio</Link>}
          </>
        ) : href ? (
          <a href={href} target="_blank" rel="noopener noreferrer" className={`inline-flex min-h-11 items-center ${link}`}>Ouvrir sur Instagram</a>
        ) : <p className="mt-2 text-sm text-muted">Pas de lien vers la vidéo.</p>}
      </Section>

      <Retention p={p} />

      <Section title="Croissance selon l’âge">
        <div className="mt-2 grid gap-3 sm:grid-cols-2">
          <Line label="Vues" values={p.series.map((x) => x.metrics.views ?? null)} />
          <Line label="Portée" values={p.series.map((x) => x.metrics.reach ?? null)} />
        </div>
        <table aria-label="Relevés" className={`${card} mt-3 w-full overflow-hidden text-sm`}>
          <thead><tr className="bg-surface-2 text-left text-xs text-muted"><th className="p-2">Âge</th><th className="p-2 text-right">Vues</th><th className="p-2 text-right">Portée</th></tr></thead>
          <tbody>
            {p.series.map((x) => (
              <tr key={x.captured_at} className="border-t border-line/60">
                <td className="p-2">{age(x.age_hours)}</td>
                <td className="p-2 text-right tabular-nums">{num(x.metrics.views)}</td>
                <td className="p-2 text-right tabular-nums">{num(x.metrics.reach)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>

      <Section title="Tags et hypothèse">
        {tags.length === 0 ? <p className="mt-1 text-sm text-muted">Pas de tags : faite hors du studio.</p> : (
          <ul aria-label="Tags" className="mt-1 flex flex-wrap gap-2">
            {tags.map(([k, v]) => <li key={k}><Chip>{tagName(k)} : {tagValue(k, v!)}</Chip></li>)}
          </ul>
        )}
        {p.hypothesis && <p className="mt-1 text-sm">Hypothèse : {p.hypothesis}</p>}
      </Section>

      <Section title="Tes retours">
        {p.feedback.length === 0 ? <p className="mt-1 text-sm text-muted">Pas de retours.</p> : (
          <ul className="mt-1 space-y-1 text-sm">
            {p.feedback.map((f) => (
              <li key={f.id}>
                <span className="text-muted">{day(f.created_at)}</span>{' '}
                {f.text ?? f.reason_codes.join(', ')}
              </li>
            ))}
          </ul>
        )}
      </Section>
    </>
  )
}
