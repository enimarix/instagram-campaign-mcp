import { useState } from 'react'
import { Link, useParams } from 'react-router'
import {
  ApiError, errorMessage, getAnalyticsPost, listAnalyticsPosts, type AnalyticsPost, type PostDetail,
} from '../api/client'
import { button, chip, localDate, safeUrl } from '../inbox/ui'
import { Body, Line, Section } from './Analytics'
import { num, pct, useLoad, VERDICT_STYLE } from './load'

const PAGE = 20
const SORTS = [
  ['posted_at', 'Posted date'], ['views', 'Views'], ['reach', 'Reach'],
  ['engagement_index', 'Engagement index'], ['watch_ratio', 'Watch ratio'], ['view_rate', 'View rate'],
]
// [param, label, [value, option label][]]; '' = all
const FILTERS = [
  ['type', 'Type', [['', 'All types'], ['REELS', 'Reels'], ['FEED', 'Feed'], ['STORY', 'Stories']]],
  ['verdict', 'Verdict', [['', 'All verdicts'], ...['winner', 'promising', 'average', 'weak', 'inconclusive',
    'no_signal', 'too_early', 'incomplete', 'no_baseline'].map((v) => [v, v.replace('_', ' ')])]],
  ['tagged', 'Tags', [['', 'Tagged or not'], ['true', 'Studio (tagged)'], ['false', 'Untagged']]],
] as const
type Filters = Record<(typeof FILTERS)[number][0], string>

const select = 'min-h-11 rounded-lg border border-gray-300 bg-white px-2 text-sm'
const link = 'text-blue-600 underline'
const day = (iso: string | null) => (iso ? localDate(new Date(iso)) : '–')
const ratio = (n: number | null | undefined) => (n == null ? '–' : `${num(n)}×`)
const age = (h: number) => (h < 48 ? `${Math.round(h)} h` : `${Math.round(h / 24)} d`)
const detailPath = (id: string) => `/analytics/posts/${encodeURIComponent(id)}`

function Verdict({ v }: { v: string }) {
  return <span className={`${chip} ${VERDICT_STYLE[v] ?? 'bg-gray-100 text-gray-700'}`}>{v.replace('_', ' ')}</span>
}

const COLUMNS: [string, (p: AnalyticsPost) => string][] = [
  ['Views', (p) => num(p.metrics.views)], ['Reach', (p) => num(p.metrics.reach)],
  ['Eng. index', (p) => ratio(p.engagement_index)], ['Watch ratio', (p) => pct(p.watch_ratio)],
  ['View rate', (p) => ratio(p.view_rate)],
]

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
      (r) => setMore((m) => (m.key === key ? { key, posts: [...m.posts, ...r.posts] } : m)),
      (e: unknown) => setMore((m) => (m.key === key ? { ...m, busy: false, error: errorMessage(e) } : m)))
  }

  return (
    <section>
      <Link to="/analytics" className={`inline-flex min-h-11 items-center ${link}`}>← Analytics</Link>
      <h2 className="text-2xl font-semibold">Posts</h2>
      <div className="mt-2 flex flex-wrap gap-2">
        <select aria-label="Sort by" className={select} value={sortKey} onChange={(e) => setSortKey(e.target.value)}>
          {SORTS.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
        </select>
        <button type="button" className={`${button} border border-gray-300 bg-white`} onClick={() => setDesc(!desc)}>
          {desc ? 'High to low' : 'Low to high'}
        </button>
        {FILTERS.map(([param, label, options]) => (
          <select key={param} aria-label={label} className={select} value={filters[param]}
            onChange={(e) => setFilters({ ...filters, [param]: e.target.value })}>
            {options.map(([v, text]) => <option key={v} value={v}>{text}</option>)}
          </select>
        ))}
      </div>

      <Body s={first} empty={(d) => d.total === 0 && 'No posts match.'}>
        {(d) => (
          <>
            <ul aria-label="Posts" className="mt-3 space-y-2 md:hidden">
              {posts.map((p) => (
                <li key={p.media_id} className="flex gap-3 rounded-lg border border-gray-200 bg-white p-3 text-sm">
                  {p.thumbnail_url && <img src={p.thumbnail_url} alt="" className="h-16 w-9 shrink-0 rounded object-cover" />}
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2"><Verdict v={p.verdict} /><span className="text-gray-500">{day(p.posted_at)}</span></div>
                    <Link to={detailPath(p.media_id)} className={`mt-1 block min-h-11 truncate ${link}`}>{p.caption || 'Untitled post'}</Link>
                    <p className="text-xs text-gray-500">{COLUMNS.map(([k, v]) => `${k} ${v(p)}`).join(' · ')}</p>
                  </div>
                </li>
              ))}
            </ul>
            <table className="mt-3 hidden w-full border-collapse text-sm md:table">
              <thead>
                <tr className="text-left text-xs text-gray-500">
                  <th className="p-2">Post</th><th className="p-2">Posted</th><th className="p-2">Verdict</th>
                  {COLUMNS.map(([k]) => <th key={k} className="p-2 text-right">{k}</th>)}
                </tr>
              </thead>
              <tbody>
                {posts.map((p) => (
                  <tr key={p.media_id} className="border-t border-gray-200 bg-white">
                    <td className="max-w-xs p-2">
                      <Link to={detailPath(p.media_id)} className={`flex items-center gap-2 ${link}`}>
                        {p.thumbnail_url && <img src={p.thumbnail_url} alt="" className="h-10 w-6 shrink-0 rounded object-cover" />}
                        <span className="truncate">{p.caption || 'Untitled post'}</span>
                      </Link>
                    </td>
                    <td className="p-2 whitespace-nowrap">{day(p.posted_at)}</td>
                    <td className="p-2"><Verdict v={p.verdict} /></td>
                    {COLUMNS.map(([k, v]) => <td key={k} className="p-2 text-right tabular-nums">{v(p)}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="mt-2 text-xs text-gray-500">{posts.length} of {d.total}</p>
            {extra.error && <p role="alert" className="text-sm text-red-700">Couldn't load more: {extra.error}</p>}
            {posts.length < d.total && (
              <button type="button" disabled={extra.busy} onClick={loadMore}
                className={`${button} mt-2 border border-gray-300 bg-white`}>{extra.busy ? 'Loading…' : 'Load more'}</button>
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
      <Link to="/analytics/posts" className={`inline-flex min-h-11 items-center ${link}`}>← Posts</Link>
      <h2 className="text-2xl font-semibold">Post</h2>
      <Body s={s} empty={(p) => p === null && 'Post not found.'}>{(p) => p && <Detail p={p} />}</Body>
    </section>
  )
}

function Detail({ p }: { p: PostDetail }) {
  const href = safeUrl(p.permalink)
  const tags = Object.entries(p.tags ?? {}).filter(([, v]) => v)
  return (
    <>
      <p className="text-sm text-gray-500">
        {day(p.posted_at)} · {p.group}{p.deleted && ' · deleted on Instagram'}
      </p>
      {p.caption && <p className="mt-1 whitespace-pre-line text-sm">{p.caption}</p>}

      <Section title="Video">
        {p.preview_url ? (
          <>
            <video src={p.preview_url} poster={p.thumbnail_url ?? undefined} controls playsInline preload="metadata"
              aria-label="Studio video" className="mt-2 max-h-[70vh] w-full max-w-xs rounded-lg bg-black" />
            {p.asset_id !== null && <Link to={`/assets/${p.asset_id}`} className={`inline-flex min-h-11 items-center ${link}`}>Studio asset</Link>}
          </>
        ) : href ? (
          <a href={href} target="_blank" rel="noopener noreferrer" className={`inline-flex min-h-11 items-center ${link}`}>Open on Instagram</a>
        ) : <p className="mt-2 text-sm text-gray-500">No video link.</p>}
      </Section>

      <Section title="Growth by post age">
        <div className="mt-2 grid gap-2 sm:grid-cols-2">
          <Line label="Views" values={p.series.map((x) => x.metrics.views ?? null)} />
          <Line label="Reach" values={p.series.map((x) => x.metrics.reach ?? null)} />
        </div>
        <table aria-label="Snapshots" className="mt-2 w-full text-sm">
          <thead><tr className="text-left text-xs text-gray-500"><th>Age</th><th className="text-right">Views</th><th className="text-right">Reach</th></tr></thead>
          <tbody>
            {p.series.map((x) => (
              <tr key={x.captured_at} className="border-t border-gray-200">
                <td>{age(x.age_hours)}</td>
                <td className="text-right tabular-nums">{num(x.metrics.views)}</td>
                <td className="text-right tabular-nums">{num(x.metrics.reach)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>

      <Section title="Tags and hypothesis">
        {tags.length === 0 ? <p className="mt-1 text-sm text-gray-500">No tags: made outside the studio.</p> : (
          <ul aria-label="Tags" className="mt-1 flex flex-wrap gap-2">
            {tags.map(([k, v]) => <li key={k} className={`${chip} bg-gray-100 text-gray-700`}>{k}: {v}</li>)}
          </ul>
        )}
        {p.hypothesis && <p className="mt-1 text-sm">Hypothesis: {p.hypothesis}</p>}
      </Section>

      <Section title="Your feedback">
        {p.feedback.length === 0 ? <p className="mt-1 text-sm text-gray-500">No feedback.</p> : (
          <ul className="mt-1 space-y-1 text-sm">
            {p.feedback.map((f) => (
              <li key={f.id}>
                <span className="text-gray-500">{day(f.created_at)}</span>{' '}
                {f.text ?? f.reason_codes.join(', ')}
              </li>
            ))}
          </ul>
        )}
      </Section>
    </>
  )
}
