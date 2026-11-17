import { useState } from 'react'
import { Link } from 'react-router'
import { getAb, getBreakdown, getCampaigns, type BreakdownGroup } from '../api/client'
import { button } from '../inbox/ui'
import { Body, Section } from './Analytics'
import { num, pct, useLoad } from './load'

// The definitions of src/learning/breakdowns.py and scoring.compare_variants, behind the ⓘ toggles.
const HELP = {
  works: 'Matured posts only (judged 48 h after posting, Stories 20 h) of one post type at a time, published in the last 90 days. The bar is the median, the thin line the middle half of the posts (p25 to p75). Engagement index: 1.0 = a typical post of that type on this account. "untagged" = posts made outside the studio (length "unknown" too); the hour is your local time. Groups with fewer than 3 posts are greyed: too few to trust.',
  ab: 'Posts labelled with a campaign and variant (label_post, or when scheduling), compared by mean engagement index of their matured posts. A leader is named only with at least 3 matured posts per variant and a lead of at least 20 %.',
}
const TAGS = [
  ['track', 'Track'], ['pillar', 'Pillar'], ['hook_type', 'Hook type'], ['template', 'Template'],
  ['strategy', 'Explore / exploit'], ['hour', 'Hour posted'], ['duration', 'Length'],
]
const TYPES = [['REELS', 'Reels'], ['FEED', 'Feed'], ['STORY', 'Stories']]
type Metric = 'engagement_index' | 'reach' | 'views' | 'watch_ratio'
const ratio = (n: number | null | undefined) => (n == null ? '–' : `${num(n)}×`)
const METRICS: [Metric, string, (n: number | null | undefined) => string][] = [
  ['engagement_index', 'Engagement index', ratio], ['reach', 'Reach', num], ['views', 'Views', num],
  ['watch_ratio', 'Watch ratio', pct],
]

const select = 'min-h-11 rounded-lg border border-gray-300 bg-white px-2 text-sm'
const toggle = (on: boolean) => `${button} ${on ? 'bg-blue-600 text-white' : 'border border-gray-300 bg-white text-gray-700'}`
const value = (g: BreakdownGroup, m: Metric) => (m === 'engagement_index' ? g.engagement_index?.median : g[m]?.median) ?? null
const label = (tag: string, v: string | number) => (tag === 'hour' ? `${v}:00` : String(v))

function Bars({ tag, groups, metric }: { tag: string; groups: BreakdownGroup[]; metric: Metric }) {
  const format = METRICS.find(([m]) => m === metric)![2]
  const top = Math.max(...groups.map((g) => (metric === 'engagement_index' ? g.engagement_index?.p75 : value(g, metric)) ?? 0)) || 1
  const width = (n: number) => `${(n / top) * 100}%`
  return (
    <ol aria-label="Groups" className="mt-2 space-y-3">
      {groups.map((g) => {
        const v = value(g, metric)
        const range = metric === 'engagement_index' ? g.engagement_index : null
        return (
          <li key={String(g.tag_value)} className={`text-sm ${g.small_sample ? 'text-gray-500' : ''}`}>
            <div className="flex justify-between gap-2">
              <span className="truncate">{label(tag, g.tag_value)}</span>
              <span className="font-semibold tabular-nums">{format(v)}</span>
            </div>
            <div className="relative h-3 rounded bg-gray-100">
              {v !== null && (
                <span className={`absolute inset-y-0 left-0 rounded ${g.small_sample ? 'bg-gray-300' : 'bg-blue-600'}`}
                  style={{ width: width(v) }} />
              )}
              {range && (
                <span aria-hidden className="absolute top-1/2 h-0.5 -translate-y-1/2 bg-gray-900"
                  style={{ left: width(range.p25), width: width(range.p75 - range.p25) }} />
              )}
            </div>
            <p className="text-xs text-gray-500">
              n = {g.n}{g.small_sample && ', too few to trust'}
              {range && ` · middle half ${ratio(range.p25)}–${ratio(range.p75)}`}
            </p>
          </li>
        )
      })}
    </ol>
  )
}

function WhatWorks() {
  const [tag, setTag] = useState('hook_type')
  const [type, setType] = useState('REELS')
  const [chosen, setChosen] = useState<Metric>('engagement_index')
  const data = useLoad(() => getBreakdown(tag, type), `${tag}|${type}`)
  const groups = data.data?.groups ?? []
  const metrics = METRICS.filter(([m]) => m !== 'watch_ratio' || groups.some((g) => g.watch_ratio))
  const metric = metrics.some(([m]) => m === chosen) ? chosen : 'engagement_index'
  return (
    <Section title="What works" help={HELP.works}>
      <div className="mt-2 flex flex-wrap gap-2">
        <select aria-label="Tag" className={select} value={tag} onChange={(e) => setTag(e.target.value)}>
          {TAGS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        <select aria-label="Post type" className={select} value={type} onChange={(e) => setType(e.target.value)}>
          {TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
      </div>
      <div role="group" aria-label="Metric" className="mt-2 flex flex-wrap gap-1">
        {metrics.map(([m, l]) => (
          <button key={m} type="button" aria-pressed={metric === m} className={toggle(metric === m)} onClick={() => setChosen(m)}>
            {l}
          </button>
        ))}
      </div>
      <Body s={data} empty={(b) => b.groups.length === 0 && 'No matured posts of this type in the last 90 days yet.'}>
        {(b) => <Bars tag={b.tag} groups={b.groups} metric={metric} />}
      </Body>
    </Section>
  )
}

function AbView({ campaign }: { campaign: string }) {
  const ab = useLoad(() => getAb(campaign), campaign)
  return (
    <Body s={ab} empty={(r) => r.variants.length === 0 && 'No matured posts in this campaign yet.'}>
      {({ variants, leader, note }) => {
        const [first, second] = variants
        return (
        <>
          {second && (
            <p className="mt-2 text-sm">
              Variant <strong>{first.variant}</strong> is ahead
              {second.avg_engagement_index > 0 && <> by <strong>{pct(first.avg_engagement_index / second.avg_engagement_index - 1)}</strong></>}
              {leader ? ': a clear lead.' : ', not yet a result.'}
            </p>
          )}
          {note && <p className="mt-1 text-sm text-amber-800">{note}</p>}
          <ul aria-label="Variants" className="mt-2 space-y-2">
            {variants.map((v) => (
              <li key={v.variant} className="rounded-lg border border-gray-200 bg-white p-3 text-sm">
                <p className="font-semibold">Variant {v.variant}{v.variant === leader && ' · leader'}</p>
                <p className="text-gray-600">
                  {v.posts} post{v.posts === 1 ? '' : 's'} · engagement {ratio(v.avg_engagement_index)} · reach {num(v.avg_reach)} · {v.winners} winner{v.winners === 1 ? '' : 's'}
                </p>
                {v.hypothesis && <p className="text-xs text-gray-500">Hypothesis: {v.hypothesis}</p>}
              </li>
            ))}
          </ul>
        </>
        )
      }}
    </Body>
  )
}

function Ab() {
  const campaigns = useLoad(getCampaigns, 'campaigns')
  const [picked, setPicked] = useState<string>()
  return (
    <Section title="A/B tests" help={HELP.ab}>
      <Body s={campaigns} empty={(c) => c.length === 0 && 'No campaigns yet: label posts with a campaign and variant.'}>
        {(c) => {
          const campaign = picked && c.includes(picked) ? picked : c[0]
          return (
            <>
              <select aria-label="Campaign" className={`${select} mt-2`} value={campaign} onChange={(e) => setPicked(e.target.value)}>
                {c.map((name) => <option key={name} value={name}>{name}</option>)}
              </select>
              <AbView campaign={campaign} />
            </>
          )
        }}
      </Body>
    </Section>
  )
}

export default function Breakdowns() {
  return (
    <section>
      <Link to="/analytics" className="inline-flex min-h-11 items-center text-blue-600 underline">← Analytics</Link>
      <h2 className="text-2xl font-semibold">What works</h2>
      <WhatWorks />
      <Ab />
    </section>
  )
}
