// The daily report (step 085): what the nightly analysis (083) found about a day, with the
// day's numbers (082) and the archive. Every post it names links to its analytics page.
import { Link, useParams } from 'react-router'
import { ApiError, getReport, listReports, type DailyReport, type ReportPick } from '../api/client'
import { safeUrl } from '../inbox/ui'
import { Card, EmptyState, Stat } from '../ui/Card'
import { Chip } from '../ui/Chip'
import { Markdown } from '../ui/Markdown'
import { PageHeader } from '../ui/PageHeader'
import { link } from '../ui/styles'
import { Body, Section } from './Analytics'
import { clock, FINDING, num, useLoad } from './load'

const NO_REPORT = 'No report yet: the nightly analysis runs at 02:00.'
const QUIET = 'Quiet day: nothing was published and no post was old enough to judge.'
const PENDING = 'Not analysed yet: the nightly analysis writes this day at 02:00.'
const reportPath = (date: string) => `/reports/${date}`
const postPath = (id: string) => `/analytics/posts/${encodeURIComponent(id)}`
/** "2026-11-16" → "lundi 16 novembre" (an owner-local day, shown as is). */
const longDay = (d: string) =>
  new Date(`${d}T12:00`).toLocaleDateString('fr-FR', { weekday: 'long', month: 'long', day: 'numeric' })
/** Markdown as one line of plain text, for the Analytics card. */
const plain = (md: string) => md.replace(/^\s*([#>]+|[-*+]|\d+[.)])\s+/gm, '').replace(/[*`]/g, '').replace(/\s+/g, ' ').trim()
/** The report of `date` (default: the newest with a summary); null when there is none. */
const loadReport = (date?: string) => getReport(date).catch((e: unknown) => {
  if (e instanceof ApiError && e.status === 404) return null
  throw e
})

/** The summary's first line as a title, then the start of the rest. */
function Teaser({ md }: { md: string }) {
  const [head, ...rest] = md.trim().split('\n')
  return (
    <>
      <p className="mt-1 font-medium">{plain(head)}</p>
      <p className="line-clamp-2">{plain(rest.join('\n'))}</p>
    </>
  )
}

/** The "Today's report" card at the top of Analytics. */
export function TodayReport() {
  const s = useLoad(() => loadReport(), 'latest')
  return (
    <Section title="Today's report">
      <Body s={s} empty={(r) => r === null && NO_REPORT}>
        {(r) => r && (
          <Card className="mt-2 text-sm">
            <p className="text-muted">{longDay(r.report_date)}</p>
            {r.summary && <Teaser md={r.summary} />}
            <p className="mt-1 text-xs text-muted">
              {r.analysis.best?.length ?? 0} best · {r.analysis.worst?.length ?? 0} worst · {r.analysis.experiments?.length ?? 0} ideas to try
            </p>
            <Link to={reportPath(r.report_date)} className={`inline-flex min-h-11 items-center ${link}`}>Read the report</Link>
          </Card>
        )}
      </Body>
    </Section>
  )
}

function Pick({ pick, report }: { pick: ReportPick; report: DailyReport }) {
  const post = report.posts[pick.media_id]
  return (
    <Card as="li" className="flex gap-3 text-sm">
      {post?.thumbnail_url && <img src={post.thumbnail_url} alt="" className="h-24 w-14 shrink-0 rounded-lg object-cover" />}
      <div className="min-w-0 flex-1">
        <Link to={postPath(pick.media_id)} className={`block min-h-11 truncate leading-[2.75rem] font-medium ${link}`}>
          {post?.title || 'Untitled post'}
        </Link>
        <p>{pick.why}</p>
        {(post?.retention ?? []).length > 0 && (
          <ul aria-label="Why viewers left" className="mt-2 space-y-1">
            {post.retention.map((f, i) => (
              <li key={i} className="text-xs text-muted">
                <Chip tone={FINDING[f.kind][0]}>{FINDING[f.kind][1]}{f.at_s != null && ` · ${clock(f.at_s)}`}</Chip> {f.text}
              </li>
            ))}
          </ul>
        )}
      </div>
    </Card>
  )
}

function Picks({ title, picks, report }: { title: string; picks?: ReportPick[]; report: DailyReport }) {
  if (!picks?.length) return null
  return (
    <Section title={title}>
      <ul className="mt-2 space-y-2">{picks.map((p) => <Pick key={p.media_id} pick={p} report={report} />)}</ul>
    </Section>
  )
}

function Report({ r }: { r: DailyReport }) {
  const y = r.facts.yesterday ?? {}
  const f = y.funnel
  const tiles: [string, string][] = [
    ['Published', num(y.published?.count)], ['Old enough to judge', num(y.matured?.count)],
    ...(f ? [['Videos made', num(f.produced)], ['You liked', num(f.liked)], ['Approved', num(f.approved)]] as [string, string][] : []),
  ]
  const comments = (r.facts.audience_comments?.posts ?? []).flatMap((p) => p.comments.map((c) => ({ ...c, post: p })))
  const experiments = r.analysis.experiments ?? []
  const quiet = !y.published?.count && !y.matured?.count
  return (
    <>
      {r.summary ? <Markdown text={r.summary} /> : <p className="text-sm text-muted">{quiet ? QUIET : PENDING}</p>}
      <Picks title="Best" picks={r.analysis.best} report={r} />
      <Picks title="Worst" picks={r.analysis.worst} report={r} />
      {experiments.length > 0 && (
        <Section title="Ideas to try next">
          <ul className="mt-2 space-y-2">
            {experiments.map((e, i) => (
              <Card as="li" key={i} className="text-sm">
                <p>{e.hypothesis}</p>
                <p className="mt-1 flex flex-wrap items-center gap-1 text-xs text-muted">
                  Change {e.variable.replace(/_/g, ' ')}: {e.variants.map((v) => <Chip key={v}>{v}</Chip>)}
                </p>
              </Card>
            ))}
          </ul>
        </Section>
      )}
      <Section title="The day's numbers">
        <dl className="mt-2 grid grid-cols-2 gap-3 sm:grid-cols-3">
          {tiles.map(([label, value]) => <Stat key={label} label={label} value={value} />)}
        </dl>
      </Section>
      {comments.length > 0 && (
        <Section title="From viewers">
          <p className="text-xs text-muted">Top comments on this week's posts, in the viewers' own words.</p>
          <ul className="mt-2 space-y-2">
            {comments.map((c, i) => {
              const href = safeUrl(c.post.permalink)
              return (
                <li key={i}>
                  <figure className="border-l-2 border-accent/50 pl-3 text-sm">
                    <blockquote className="whitespace-pre-line">“{c.quote}”</blockquote>
                    <figcaption className="text-xs text-muted">
                      from viewers · {num(c.likes)} likes
                      {href && <> · <a href={href} target="_blank" rel="noopener noreferrer" className={link}>the post</a></>}
                    </figcaption>
                  </figure>
                </li>
              )
            })}
          </ul>
        </Section>
      )}
    </>
  )
}

/** /reports/:date? — one day's report (default the newest), prev/next and the archive. */
export default function ReportPage() {
  const { date } = useParams()
  const s = useLoad(() => loadReport(date), date)
  const archive = useLoad(() => listReports(), 'archive')
  const days = archive.data ?? []
  const shown = date ?? s.data?.report_date
  const i = days.findIndex((d) => d.report_date === shown)
  const [newer, older] = i < 0 ? [undefined, days[0]] : [days[i - 1], days[i + 1]]
  return (
    <section>
      <PageHeader title="Daily report" back={{ to: '/analytics', label: 'Analytics' }}>{shown && longDay(shown)}</PageHeader>
      <nav aria-label="Other days" className="-mt-3 mb-4 flex justify-between gap-4 text-sm">
        {older ? <Link to={reportPath(older.report_date)} className={`inline-flex min-h-11 items-center ${link}`}>← Older</Link> : <span />}
        {newer && <Link to={reportPath(newer.report_date)} className={`inline-flex min-h-11 items-center ${link}`}>Newer →</Link>}
      </nav>
      <Body s={s} empty={(r) => r === null && (date ? 'No report for this day.' : '')}>
        {(r) => (r ? <Report r={r} /> : <EmptyState title="No report yet">The nightly analysis runs at 02:00.</EmptyState>)}
      </Body>
      {days.length > 0 && (
        <Section title="All reports">
          <ul className="mt-2 space-y-1 text-sm">
            {days.map((d) => (
              <li key={d.report_date}>
                <Link to={reportPath(d.report_date)} aria-current={d.report_date === shown ? 'page' : undefined}
                  className={`flex min-h-11 flex-wrap items-center gap-x-2 ${d.report_date === shown ? 'font-semibold' : link}`}>
                  <span className="tabular-nums">{d.report_date}</span>
                  <span className="min-w-0 flex-1 truncate text-muted">{d.first_line ?? (d.published || d.matured ? 'Not analysed yet' : 'Quiet day')}</span>
                </Link>
              </li>
            ))}
          </ul>
        </Section>
      )}
    </section>
  )
}
