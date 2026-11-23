import { useState, type ReactNode } from 'react'
import { Link } from 'react-router'
import {
  getAccountSeries, getAnalyticsPosts, getFunnel, getTaste, type AnalyticsPost, type FunnelStats,
} from '../api/client'
import { localDate, safeUrl } from '../inbox/ui'
import { IconButton } from '../ui/Button'
import { Card, Skeleton, Stat } from '../ui/Card'
import { Chip } from '../ui/Chip'
import { InfoIcon } from '../ui/icons'
import { PageHeader } from '../ui/PageHeader'
import { card, link } from '../ui/styles'
import { num, pct, useLoad, VERDICT_TONE, type Load } from './load'
import { TodayReport } from './Report'

// The definitions of src/learning/funnel.py's docstring, behind the ⓘ toggles.
const HELP = {
  trends: 'Daily account values saved by the worker. The 7-day reach and views tiles add up the daily values, so someone reached on two days counts twice.',
  streak: 'Posts this week: published in the last 7 days. Streak: days in a row (your time zone) with at least one published post, up to today or yesterday.',
  funnel: 'Videos whose batch day is in the last 30 days. Produced: rendered and checked. Reviewed: you liked, disliked, commented, approved or sent it back (an archive alone does not count). Liked: your verdict. Approved: cleared for publishing. Published: on Instagram. Winner: the post scores "winner" against the account\'s other posts.',
  likeRate: 'Like-rate = liked / reviewed per batch day: the taste metric. The 7-day value adds up the day and the 6 before. Approval rate is capped by the posts-per-day limit, so it says more about the posting limit than about taste.',
  waste: 'Liked videos archived without ever being approved, after their best-before date, and the render minutes spent on them. Reasons: how often each feedback reason was given on the last 30 days\' videos.',
}
const RANGES = [7, 30, 90]
const STAGES = ['produced', 'reviewed', 'liked', 'approved', 'published', 'winner'] as const

const signed = (n: number, format: (n: number) => string) => `${n < 0 ? '−' : '+'}${format(Math.abs(n))}`
const sum = (xs: (number | null)[]) => (xs.some((x) => x !== null) ? xs.reduce<number>((a, x) => a + (x ?? 0), 0) : null)
const postDay = (p: AnalyticsPost) => (p.posted_at ? localDate(new Date(p.posted_at)) : null)
const daysAgo = (n: number) => {
  const d = new Date()
  d.setDate(d.getDate() - n)
  return d
}

/** Loading, error and empty states in one place: a friendly line, never a crash. */
export function Body<T>({ s, empty, children }: { s: Load<T>; empty: (d: T) => string | false; children: (d: T) => ReactNode }) {
  if (s.error) return <p role="alert" className="mt-2 text-sm text-danger">Couldn't load: {s.error}</p>
  if (s.data === undefined) return <Skeleton className="mt-2 h-20" />
  const message = empty(s.data)
  return message ? <p className="mt-2 text-sm text-muted">{message}</p> : <>{children(s.data)}</>
}

export function Section({ title, help, children }: { title: string; help?: string; children: ReactNode }) {
  const [open, setOpen] = useState(false)
  return (
    <section aria-label={title} className="mt-8 [header+&]:mt-0">
      <div className="flex items-center gap-1">
        <h2 className="text-lg font-semibold tracking-tight">{title}</h2>
        {help && (
          <IconButton variant="ghost" label={`About ${title}`} aria-expanded={open} icon={<InfoIcon className="size-4" />}
            className="text-muted" onClick={() => setOpen(!open)} />
        )}
      </div>
      {open && <p className="max-w-prose rounded-control bg-surface-2 p-3 text-xs text-muted">{help}</p>}
      {children}
    </section>
  )
}

/** A small inline SVG line; null values are skipped. The numbers are also shown as text. */
export function Line({ label, values, format = num }: { label: string; values: (number | null)[]; format?: (n: number) => string }) {
  const pts = values.flatMap((v, i) => (v === null ? [] : [[i, v] as const]))
  if (pts.length === 0) return <p className="text-sm text-muted">{label}: no data yet</p>
  const ys = pts.map(([, v]) => v)
  const [min, max, last] = [Math.min(...ys), Math.max(...ys), ys[ys.length - 1]]
  const change = `${signed(last - ys[0], format)} over the range`
  const points = pts.map(([i, v]) =>
    `${(i / Math.max(values.length - 1, 1)) * 100},${28 - ((v - min) / (max - min || 1)) * 26}`).join(' ')
  return (
    <figure className={`${card} p-4`}>
      <figcaption className="flex justify-between gap-2 text-sm">
        <span className="text-muted">{label}</span><span className="font-semibold tabular-nums">{format(last)}</span>
      </figcaption>
      <svg role="img" aria-label={`${label}: ${format(last)}, ${change}`} viewBox="0 0 100 30"
        preserveAspectRatio="none" className="mt-2 h-14 w-full text-accent">
        <polyline points={points} fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinejoin="round"
          vectorEffect="non-scaling-stroke" />
      </svg>
      <p className="mt-1 text-xs text-muted">{change}</p>
    </figure>
  )
}

function Funnel({ totals, note }: { totals: FunnelStats; note: string }) {
  const top = Math.max(1, ...STAGES.map((s) => totals[s]))
  return (
    <>
      <ol aria-label="Funnel" className="mt-2 space-y-1">
        {STAGES.map((s) => (
          <li key={s} className="grid grid-cols-[5.5rem_1fr_3rem] items-center gap-2 text-sm">
            <span className="capitalize">{s}</span>
            <span className="h-3 rounded-full bg-surface-2">
              <span className="block h-3 rounded-full bg-accent transition-[width]" style={{ width: `${(totals[s] / top) * 100}%` }} />
            </span>
            <span className="text-right tabular-nums">{totals[s]}</span>
          </li>
        ))}
      </ol>
      <p className="mt-2 text-xs text-muted">
        Like-rate {pct(totals.like_rate)} · approval rate {pct(totals.approval_rate)} ({note})
      </p>
    </>
  )
}

function PostCard({ post }: { post: AnalyticsPost }) {
  const thumb = post.thumbnail_url
  const href = safeUrl(post.permalink)
  return (
    <Card as="li" className="flex gap-3 text-sm">
      {thumb && <img src={thumb} alt="" className="h-20 w-11 shrink-0 rounded-lg object-cover" />}
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <Chip tone={VERDICT_TONE[post.verdict]}>{post.verdict.replace('_', ' ')}</Chip>
          <span className="text-muted">{postDay(post)}</span>
          {post.deleted && <Chip>deleted</Chip>}
        </div>
        {post.caption && <p className="mt-1 truncate">{post.caption}</p>}
        <p className="text-xs text-muted">{num(post.metrics.views)} views · {num(post.metrics.likes)} likes</p>
        <div className="flex flex-wrap gap-x-4">
          <Link to={`/analytics/posts/${encodeURIComponent(post.media_id)}`}
            className={`inline-flex min-h-11 items-center ${link}`}>Details</Link>
          {!thumb && href && (
            <a href={href} target="_blank" rel="noopener noreferrer"
              className={`inline-flex min-h-11 items-center ${link}`}>Open on Instagram</a>
          )}
        </div>
      </div>
    </Card>
  )
}

/** Days in a row with a post, ending today, or yesterday when today has none yet. */
function streak(posts: AnalyticsPost[]): number {
  const days = new Set(posts.map(postDay))
  let n = days.has(localDate(daysAgo(0))) ? 0 : 1
  const start = n
  while (days.has(localDate(daysAgo(n)))) n++
  return n - start
}

export default function Analytics() {
  const [range, setRange] = useState(30)
  const account = useLoad(() => getAccountSeries(range), range)
  // ponytail: the streak only sees the last 100 posts (≥ 33 days at 3 a day); page further if it ever matters
  const posts = useLoad(() => getAnalyticsPosts(100), 'posts')
  const funnel = useLoad(() => getFunnel(30), 'funnel')
  const taste = useLoad(() => getTaste(30), 'taste')

  const since = localDate(daysAgo(6))
  const days = account.data?.days ?? []
  const lastWeek = days.filter((d) => d.date >= since)
  const followers = days.findLast((d) => d.followers !== null)?.followers
  const followersDelta = sum(lastWeek.map((d) => d.deltas.followers))
  const week = posts.data?.posts.filter((p) => (postDay(p) ?? '') >= since) ?? []
  const winners = week.filter((p) => p.verdict === 'winner').length
  const tiles: [string, string, string?][] = [
    ['Followers', num(followers), followersDelta === null ? undefined : `${signed(followersDelta, num)} in 7 d`],
    ['Reach 7 d', num(sum(lastWeek.map((d) => d.reach)))],
    ['Views 7 d', num(sum(lastWeek.map((d) => d.views)))],
    ['Like-rate 7 d', pct(taste.data?.like_rate.at(-1)?.rolling_7d)],
    ['Posts this week', posts.data ? String(week.length) : '–', posts.data && `${winners} winner${winners === 1 ? '' : 's'}`],
    ['Streak', posts.data ? `${streak(posts.data.posts)} d` : '–'],
  ]

  return (
    <section>
      <PageHeader title="Analytics">
        <nav aria-label="More analytics" className="flex flex-wrap gap-x-5">
          <Link to="/trends" className={`inline-flex min-h-11 items-center ${link}`}>
            Trends: what works for watched accounts and hashtags
          </Link>
          <Link to="/analytics/breakdowns" className={`inline-flex min-h-11 items-center ${link}`}>
            What works for your posts: tags and A/B tests
          </Link>
        </nav>
      </PageHeader>

      <TodayReport />

      <Section title="This week" help={HELP.streak}>
        <dl className="mt-2 grid grid-cols-2 gap-3 sm:grid-cols-3">
          {tiles.map(([label, value, sub]) => <Stat key={label} label={label} value={value} sub={sub} />)}
        </dl>
      </Section>

      <Section title="Account trends" help={HELP.trends}>
        <div role="group" aria-label="Range" className="mt-2 flex gap-2">
          {RANGES.map((r) => (
            <Chip key={r} pressed={range === r} onClick={() => setRange(r)}>{r} d</Chip>
          ))}
        </div>
        <Body s={account} empty={(a) => a.days.length === 0 && 'No account data yet: the worker saves one row a day once Instagram is connected.'}>
          {(a) => (
            <div className="mt-3 grid gap-3 sm:grid-cols-3">
              <Line label="Followers" values={a.days.map((d) => d.followers)} />
              <Line label="Reach" values={a.days.map((d) => d.reach)} />
              <Line label="Views" values={a.days.map((d) => d.views)} />
            </div>
          )}
        </Body>
      </Section>

      <Section title="This week's posts">
        <Link to="/analytics/posts" className={`inline-flex min-h-11 items-center ${link}`}>All posts</Link>
        <Body s={posts} empty={() => week.length === 0 && 'No posts in the last 7 days.'}>
          {() => <ul className="mt-2 space-y-2">{week.map((p) => <PostCard key={p.media_id} post={p} />)}</ul>}
        </Body>
      </Section>

      <Section title="Studio funnel" help={HELP.funnel}>
        <Body s={funnel} empty={(f) => STAGES.every((s) => f.totals[s] === 0) && 'No videos in the last 30 days yet.'}>
          {(f) => <Funnel totals={f.totals} note={f.approval_rate_note} />}
        </Body>
      </Section>

      <Section title="Like-rate" help={HELP.likeRate}>
        <Body s={taste} empty={(t) => t.like_rate.every((d) => d.rolling_7d === null) && 'Nothing reviewed in the last 30 days yet.'}>
          {(t) => <Line label="Like-rate, 7-day" values={t.like_rate.map((d) => d.rolling_7d)} format={pct} />}
        </Body>
      </Section>

      <Section title="Waste and feedback" help={HELP.waste}>
        <Body s={taste} empty={() => false}>
          {({ waste, reasons }) => (
            <>
              <p className="mt-1 text-sm">
                {waste.count} liked video{waste.count === 1 ? '' : 's'} expired unapproved · {waste.render_minutes} render minutes
              </p>
              {reasons.length === 0 ? (
                <p className="mt-1 text-sm text-muted">No feedback reasons yet.</p>
              ) : (
                <ul aria-label="Top feedback reasons" className="mt-1 flex flex-wrap gap-2">
                  {reasons.slice(0, 5).map((r) => (
                    <li key={r.code}><Chip>{r.label} ×{r.count}</Chip></li>
                  ))}
                </ul>
              )}
            </>
          )}
        </Body>
      </Section>
    </section>
  )
}
