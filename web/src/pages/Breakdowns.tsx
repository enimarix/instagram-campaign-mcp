import { useState } from 'react'
import { getAb, getBreakdown, getCampaigns, type BreakdownGroup } from '../api/client'
import { Card } from '../ui/Card'
import { Chip } from '../ui/Chip'
import { PageHeader } from '../ui/PageHeader'
import { field } from '../ui/styles'
import { Body, Section } from './Analytics'
import { num, pct, POST_TYPES, TAGS, tagValue, useLoad } from './load'

// The definitions of src/learning/breakdowns.py and scoring.compare_variants, behind the ⓘ toggles.
const HELP = {
  works: 'Publications mûres seulement (jugées 48 h après la publication, Stories 20 h), d’un seul type à la fois, publiées ces 90 derniers jours. La barre est la médiane, le trait fin la moitié centrale des publications (p25 à p75). Indice d’engagement : 1,0 = une publication typique de ce type sur ce compte. « Sans tag » = publications faites hors du studio (durée « Inconnue » aussi) ; l’heure est ton heure locale. Les groupes de moins de 3 publications sont grisés : trop peu pour s’y fier.',
  ab: 'Publications marquées d’une campagne et d’une variante (label_post, ou à la programmation), comparées par l’indice d’engagement moyen de leurs publications mûres. Une variante n’est donnée en tête qu’avec au moins 3 publications mûres par variante et une avance d’au moins 20 %.',
}
const TYPES = ['REELS', 'FEED', 'STORY'].map((t) => [t, POST_TYPES[t]])
type Metric = 'engagement_index' | 'reach' | 'views' | 'watch_ratio'
const ratio = (n: number | null | undefined) => (n == null ? '–' : `${num(n)}×`)
const METRICS: [Metric, string, (n: number | null | undefined) => string][] = [
  ['engagement_index', 'Indice d’engagement', ratio], ['reach', 'Portée', num], ['views', 'Vues', num],
  ['watch_ratio', 'Taux de visionnage', pct],
]

const value = (g: BreakdownGroup, m: Metric) => (m === 'engagement_index' ? g.engagement_index?.median : g[m]?.median) ?? null

function Bars({ tag, groups, metric }: { tag: string; groups: BreakdownGroup[]; metric: Metric }) {
  const format = METRICS.find(([m]) => m === metric)![2]
  const top = Math.max(...groups.map((g) => (metric === 'engagement_index' ? g.engagement_index?.p75 : value(g, metric)) ?? 0)) || 1
  const width = (n: number) => `${(n / top) * 100}%`
  return (
    <ol aria-label="Groupes" className="mt-2 space-y-3">
      {groups.map((g) => {
        const v = value(g, metric)
        const range = metric === 'engagement_index' ? g.engagement_index : null
        return (
          <li key={String(g.tag_value)} className={`text-sm ${g.small_sample ? 'text-muted' : ''}`}>
            <div className="flex justify-between gap-2">
              <span className="truncate">{tagValue(tag, g.tag_value)}</span>
              <span className="font-semibold tabular-nums">{format(v)}</span>
            </div>
            <div className="relative mt-1 h-3 rounded-full bg-surface-2">
              {v !== null && (
                <span className={`absolute inset-y-0 left-0 rounded-full ${g.small_sample ? 'bg-line' : 'bg-accent'}`}
                  style={{ width: width(v) }} />
              )}
              {range && (
                <span aria-hidden className="absolute top-1/2 h-0.5 -translate-y-1/2 bg-fg"
                  style={{ left: width(range.p25), width: width(range.p75 - range.p25) }} />
              )}
            </div>
            <p className="mt-0.5 text-xs text-muted">
              n = {g.n}{g.small_sample && ', trop peu pour s’y fier'}
              {range && ` · moitié centrale ${ratio(range.p25)}–${ratio(range.p75)}`}
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
    <Section title="Par tag" help={HELP.works}>
      <div className="mt-2 flex flex-wrap gap-2">
        <select aria-label="Tag" className={field} value={tag} onChange={(e) => setTag(e.target.value)}>
          {TAGS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        <select aria-label="Type de publication" className={field} value={type} onChange={(e) => setType(e.target.value)}>
          {TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
      </div>
      <div role="group" aria-label="Mesure" className="mt-2 flex flex-wrap gap-2">
        {metrics.map(([m, l]) => (
          <Chip key={m} pressed={metric === m} onClick={() => setChosen(m)}>{l}</Chip>
        ))}
      </div>
      <Body s={data} empty={(b) => b.groups.length === 0 && 'Pas encore de publications mûres de ce type ces 90 derniers jours.'}>
        {(b) => <Bars tag={b.tag} groups={b.groups} metric={metric} />}
      </Body>
    </Section>
  )
}

function AbView({ campaign }: { campaign: string }) {
  const ab = useLoad(() => getAb(campaign), campaign)
  return (
    <Body s={ab} empty={(r) => r.variants.length === 0 && 'Pas encore de publications mûres dans cette campagne.'}>
      {({ variants, leader, note }) => {
        const [first, second] = variants
        return (
        <>
          {second && (
            <p className="mt-2 text-sm">
              La variante <strong>{first.variant}</strong> est devant
              {second.avg_engagement_index > 0 && <> de <strong>{pct(first.avg_engagement_index / second.avg_engagement_index - 1)}</strong></>}
              {leader ? ' : une avance nette.' : ', pas encore un résultat.'}
            </p>
          )}
          {note && <p className="mt-1 text-sm text-warn">{note}</p>}
          <ul aria-label="Variantes" className="mt-2 space-y-2">
            {variants.map((v) => (
              <Card as="li" key={v.variant} className="text-sm">
                <p className="font-semibold">Variante {v.variant}{v.variant === leader && ' · en tête'}</p>
                <p className="text-muted">
                  {v.posts} publication{v.posts > 1 ? 's' : ''} · engagement {ratio(v.avg_engagement_index)} · portée {num(v.avg_reach)} · {v.winners} gagnante{v.winners > 1 ? 's' : ''}
                </p>
                {v.hypothesis && <p className="text-xs text-muted">Hypothèse : {v.hypothesis}</p>}
              </Card>
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
    <Section title="Tests A/B" help={HELP.ab}>
      <Body s={campaigns} empty={(c) => c.length === 0 && 'Pas encore de campagnes : marque des publications avec une campagne et une variante.'}>
        {(c) => {
          const campaign = picked && c.includes(picked) ? picked : c[0]
          return (
            <>
              <select aria-label="Campagne" className={`${field} mt-2`} value={campaign} onChange={(e) => setPicked(e.target.value)}>
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
      <PageHeader title="Ce qui marche" back={{ to: '/analytics', label: 'Statistiques' }} />
      <WhatWorks />
      <Ab />
    </section>
  )
}
