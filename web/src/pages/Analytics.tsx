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
import { num, pct, postVerdict, useLoad, VERDICT_TONE, type Load } from './load'
import { TodayReport } from './Report'

// The definitions of src/learning/funnel.py's docstring, behind the ⓘ toggles.
const HELP = {
  trends: 'Valeurs quotidiennes du compte, enregistrées par le Worker. Les tuiles Portée et Vues sur 7 j additionnent les valeurs de chaque jour : une personne touchée deux jours compte deux fois.',
  streak: 'Publications de la semaine : publiées ces 7 derniers jours. Série : jours d’affilée (dans ton fuseau horaire) avec au moins une publication, jusqu’à aujourd’hui ou hier.',
  funnel: 'Vidéos dont le jour de lot est dans les 30 derniers jours. Produites : rendues et vérifiées. Revues : tu les as gardées, refusées, commentées, approuvées ou renvoyées (un archivage seul ne compte pas). Gardées : ton verdict. Approuvées : autorisées à la publication. Publiées : sur Instagram. Gagnantes : la publication est jugée « gagnante » face aux autres publications du compte.',
  likeRate: 'Taux de like = gardées / revues par jour de lot : la mesure de ton goût. La valeur sur 7 jours additionne le jour et les 6 précédents. Le taux d’approbation est plafonné par la limite de publications par jour : il parle plus de cette limite que de ton goût.',
  waste: 'Vidéos gardées puis archivées sans jamais être approuvées, après leur date limite, et les minutes de rendu passées dessus. Raisons : combien de fois chaque raison de retour a été donnée sur les vidéos des 30 derniers jours.',
}
const RANGES = [7, 30, 90]
const STAGES = ['produced', 'reviewed', 'liked', 'approved', 'published', 'winner'] as const
const STAGE: Record<(typeof STAGES)[number], string> = {
  produced: 'Produites', reviewed: 'Revues', liked: 'Gardées', approved: 'Approuvées', published: 'Publiées', winner: 'Gagnantes',
}

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
  if (s.error) return <p role="alert" className="mt-2 text-sm text-danger">Impossible de charger : {s.error}</p>
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
          <IconButton variant="ghost" label={`Aide : ${title}`} aria-expanded={open} icon={<InfoIcon className="size-4" />}
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
  if (pts.length === 0) return <p className="text-sm text-muted">{label} : pas encore de données</p>
  const ys = pts.map(([, v]) => v)
  const [min, max, last] = [Math.min(...ys), Math.max(...ys), ys[ys.length - 1]]
  const change = `${signed(last - ys[0], format)} sur la période`
  const points = pts.map(([i, v]) =>
    `${(i / Math.max(values.length - 1, 1)) * 100},${28 - ((v - min) / (max - min || 1)) * 26}`).join(' ')
  return (
    <figure className={`${card} p-4`}>
      <figcaption className="flex justify-between gap-2 text-sm">
        <span className="text-muted">{label}</span><span className="font-semibold tabular-nums">{format(last)}</span>
      </figcaption>
      <svg role="img" aria-label={`${label} : ${format(last)}, ${change}`} viewBox="0 0 100 30"
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
      <ol aria-label="Entonnoir" className="mt-2 space-y-1">
        {STAGES.map((s) => (
          <li key={s} className="grid grid-cols-[5.5rem_1fr_3rem] items-center gap-2 text-sm">
            <span>{STAGE[s]}</span>
            <span className="h-3 rounded-full bg-surface-2">
              <span className="block h-3 rounded-full bg-accent transition-[width]" style={{ width: `${(totals[s] / top) * 100}%` }} />
            </span>
            <span className="text-right tabular-nums">{totals[s]}</span>
          </li>
        ))}
      </ol>
      <p className="mt-2 text-xs text-muted">
        Taux de like {pct(totals.like_rate)} · taux d’approbation {pct(totals.approval_rate)} ({note})
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
          <Chip tone={VERDICT_TONE[post.verdict]}>{postVerdict(post.verdict)}</Chip>
          <span className="text-muted">{postDay(post)}</span>
          {post.deleted && <Chip>supprimée</Chip>}
        </div>
        {post.caption && <p className="mt-1 truncate">{post.caption}</p>}
        <p className="text-xs text-muted">{num(post.metrics.views)} vues · {num(post.metrics.likes)} likes</p>
        <div className="flex flex-wrap gap-x-4">
          <Link to={`/analytics/posts/${encodeURIComponent(post.media_id)}`}
            className={`inline-flex min-h-11 items-center ${link}`}>Détails</Link>
          {!thumb && href && (
            <a href={href} target="_blank" rel="noopener noreferrer"
              className={`inline-flex min-h-11 items-center ${link}`}>Ouvrir sur Instagram</a>
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
    ['Abonnés', num(followers), followersDelta === null ? undefined : `${signed(followersDelta, num)} en 7 j`],
    ['Portée 7 j', num(sum(lastWeek.map((d) => d.reach)))],
    ['Vues 7 j', num(sum(lastWeek.map((d) => d.views)))],
    ['Taux de like 7 j', pct(taste.data?.like_rate.at(-1)?.rolling_7d)],
    ['Publications de la semaine', posts.data ? String(week.length) : '–', posts.data && `${winners} gagnante${winners > 1 ? 's' : ''}`],
    ['Série', posts.data ? `${streak(posts.data.posts)} j` : '–'],
  ]

  return (
    <section>
      <PageHeader title="Statistiques">
        <nav aria-label="Plus de statistiques" className="flex flex-wrap gap-x-5">
          <Link to="/trends" className={`inline-flex min-h-11 items-center ${link}`}>
            Tendances : ce qui marche pour les comptes et hashtags suivis
          </Link>
          <Link to="/analytics/breakdowns" className={`inline-flex min-h-11 items-center ${link}`}>
            Ce qui marche pour tes publications : tags et tests A/B
          </Link>
        </nav>
      </PageHeader>

      <TodayReport />

      <Section title="Cette semaine" help={HELP.streak}>
        <dl className="mt-2 grid grid-cols-2 gap-3 sm:grid-cols-3">
          {tiles.map(([label, value, sub]) => <Stat key={label} label={label} value={value} sub={sub} />)}
        </dl>
      </Section>

      <Section title="Évolution du compte" help={HELP.trends}>
        <div role="group" aria-label="Période" className="mt-2 flex gap-2">
          {RANGES.map((r) => (
            <Chip key={r} pressed={range === r} onClick={() => setRange(r)}>{r} j</Chip>
          ))}
        </div>
        <Body s={account} empty={(a) => a.days.length === 0 && 'Pas encore de données du compte : le Worker enregistre une ligne par jour une fois Instagram connecté.'}>
          {(a) => (
            <div className="mt-3 grid gap-3 sm:grid-cols-3">
              <Line label="Abonnés" values={a.days.map((d) => d.followers)} />
              <Line label="Portée" values={a.days.map((d) => d.reach)} />
              <Line label="Vues" values={a.days.map((d) => d.views)} />
            </div>
          )}
        </Body>
      </Section>

      <Section title="Publications de la semaine">
        <Link to="/analytics/posts" className={`inline-flex min-h-11 items-center ${link}`}>Toutes les publications</Link>
        <Body s={posts} empty={() => week.length === 0 && 'Aucune publication ces 7 derniers jours.'}>
          {() => <ul className="mt-2 space-y-2">{week.map((p) => <PostCard key={p.media_id} post={p} />)}</ul>}
        </Body>
      </Section>

      <Section title="Entonnoir du studio" help={HELP.funnel}>
        <Body s={funnel} empty={(f) => STAGES.every((s) => f.totals[s] === 0) && 'Pas encore de vidéos ces 30 derniers jours.'}>
          {(f) => <Funnel totals={f.totals} note={f.approval_rate_note} />}
        </Body>
      </Section>

      <Section title="Taux de like" help={HELP.likeRate}>
        <Body s={taste} empty={(t) => t.like_rate.every((d) => d.rolling_7d === null) && 'Rien de revu ces 30 derniers jours.'}>
          {(t) => <Line label="Taux de like sur 7 jours" values={t.like_rate.map((d) => d.rolling_7d)} format={pct} />}
        </Body>
      </Section>

      <Section title="Gâchis et retours" help={HELP.waste}>
        <Body s={taste} empty={() => false}>
          {({ waste, reasons }) => (
            <>
              <p className="mt-1 text-sm">
                {waste.count > 1 ? `${waste.count} vidéos gardées expirées` : `${waste.count} vidéo gardée expirée`} sans
                approbation · {num(waste.render_minutes)} minutes de rendu
              </p>
              {reasons.length === 0 ? (
                <p className="mt-1 text-sm text-muted">Pas encore de raisons de retour.</p>
              ) : (
                <ul aria-label="Principales raisons de retour" className="mt-1 flex flex-wrap gap-2">
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
