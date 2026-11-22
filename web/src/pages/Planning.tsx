import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router'
import { errorMessage, getPlanning, type PlanningItem, type PlanningWait } from '../api/client'
import { Card, EmptyState, Skeleton } from '../ui/Card'
import { Chip } from '../ui/Chip'
import { PageHeader } from '../ui/PageHeader'
import { link } from '../ui/styles'

const POLL_MS = 10_000 // a live page, like Créer and Agent

const SECTIONS: [PlanningItem['section'], string][] = [
  ['running', 'En cours'], ['next', 'Ensuite'], ['planned', "Runs prévus de l'IA"],
]
const KIND: Record<PlanningItem['kind'], string> = {
  render: 'Rendu', film: 'Film Lemo', order_run: 'Run léger', agent_run: "Run de l'IA",
  work_order: 'Commande', change_request: 'Changement',
}
const WAIT: Record<PlanningWait, string> = {
  gpu_busy: 'attend le GPU', agent_running: 'attend la fin du run', order_grace: 'délai après ton envoi',
  daily_cap: 'quota du jour atteint', preflight: "l'IA ne peut pas démarrer", next_ai_run: 'attend le prochain run',
  needs_instruction: 'attend ta consigne',
}
const SOURCE: Record<string, string> = {
  dm: 'envoyé en DM', trend: 'depuis Trending', create: "créé dans l'app", change: 'demande de changement',
  agent: "l'IA", schedule: 'planning des runs',
}

/** "14:05", or "demain 03:00" / "lun. 03:00" past today. */
function at(iso: string) {
  const d = new Date(iso)
  const time = d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })
  const days = Math.round((new Date(d).setHours(0, 0, 0, 0) - new Date().setHours(0, 0, 0, 0)) / 86_400_000)
  if (days === 0) return time
  return `${days === 1 ? 'demain' : d.toLocaleDateString('fr-FR', { weekday: 'short' })} ${time}`
}

function duration(s: number) {
  if (s < 60) return '< 1 min'
  const m = Math.round(s / 60)
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, '0')}`
}

/** Where the item comes from, linked to its page when it has one. */
function Origin({ item: i }: { item: PlanningItem }) {
  const what = SOURCE[i.source ?? ''] ?? i.source
  const to = i.ids.asset_id ? `/assets/${i.ids.asset_id}` : i.ids.order_id ? '/create' : i.ids.run_id ? '/agent' : null
  const label = i.ids.asset_id ? `vidéo ${i.ids.asset_id}` : i.ids.order_id ? `commande ${i.ids.order_id}` : i.ids.run_id ? `run ${i.ids.run_id}` : null
  if (!what && !to) return null
  return (
    <p className="text-muted">
      {what}{what && to && ' · '}{to && <Link to={to} className={link}>{label}</Link>}
    </p>
  )
}

function ItemCard({ item: i }: { item: PlanningItem }) {
  const look = [i.style && `style ${i.style}`, i.engine && `moteur ${i.engine}`, i.voice && `voix ${i.voice}`].filter(Boolean)
  return (
    <Card as="article" className="space-y-1.5 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <Chip tone={i.section === 'running' ? 'explore' : 'info'}>{KIND[i.kind]}</Chip>
        {i.waits_on && <Chip tone="warn">{WAIT[i.waits_on] ?? i.waits_on}</Chip>}
      </div>
      <h3 className="font-semibold break-words">{i.title}</h3>
      <Origin item={i} />
      {look.length > 0 && <p className="text-muted">{look.join(' · ')}</p>}
      {i.est_start && i.est_ready && i.est_duration_s !== null ? (
        <p className="tabular-nums">
          Début ~{at(i.est_start)} · {duration(i.est_duration_s)} · prête ~{at(i.est_ready)}
        </p>
      ) : <p className="text-muted">Pas d'heure : rien ne part sans toi.</p>}
      {i.progress !== null && (
        <div role="progressbar" aria-label={i.stage ?? 'Progression'} aria-valuenow={Math.round(i.progress * 100)}
          aria-valuemin={0} aria-valuemax={100} className="h-1.5 overflow-hidden rounded-full bg-surface-2">
          <div className="h-full bg-explore" style={{ width: `${Math.round(i.progress * 100)}%` }} />
        </div>
      )}
      {i.picks_up && (
        <p>
          Reprend d'abord : {i.picks_up.orders} commande(s), {i.picks_up.change_requests} changement(s),{' '}
          {i.picks_up.dm_picks} DM · <strong>{i.picks_up.ideas_left}</strong> place(s) pour les idées de Claude
        </p>
      )}
      <p className="text-muted">{i.why_here}</p>
      <p className="text-muted">
        → <Link to="/inbox" className={link}>Inbox</Link> → <Link to="/calendar" className={link}>créneau</Link>
      </p>
    </Card>
  )
}

/** The cards of one section, joined by a line (the chain). */
function Chain({ items }: { items: PlanningItem[] }) {
  return (
    <ol>
      {items.map((item, n) => (
        <li key={`${item.kind}-${item.ids.asset_id ?? item.ids.order_id ?? item.ids.run_id ?? item.title}-${n}`}>
          {n > 0 && <div aria-hidden className="ml-6 h-4 w-px bg-line" />}
          <ItemCard item={item} />
        </li>
      ))}
    </ol>
  )
}

/** Planning (185): what renders next and when, read-only, in the worker's real order. */
export default function Planning() {
  const [items, setItems] = useState<PlanningItem[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const load = useCallback(() => getPlanning().then((p) => {
    setItems(p.items)
    setError(null)
  }, (e: unknown) => setError(errorMessage(e))), [])
  useEffect(() => {
    void load()
    const t = setInterval(() => void load(), POLL_MS) // a failed load does not stop it
    return () => clearInterval(t)
  }, [load])

  return (
    <section>
      <PageHeader title="Planning">Ce que le studio fait ensuite et quand. Toutes les heures sont estimées.</PageHeader>
      {error && <p role="alert" className="mb-3 text-sm text-danger">{error}</p>}
      {items === null ? (!error && <Skeleton className="h-32" />) : items.length === 0 ? (
        <EmptyState title="Rien de prévu">Aucun rendu en file, aucune commande en attente, aucun run de l'IA dans les 24 h.</EmptyState>
      ) : (
        <div className="space-y-6">
          {SECTIONS.map(([id, title]) => {
            const mine = items.filter((i) => i.section === id)
            return mine.length > 0 && (
              <section key={id} aria-label={title}>
                <h2 className="mb-2 font-semibold">{title}</h2>
                <Chain items={mine} />
              </section>
            )
          })}
        </div>
      )}
    </section>
  )
}
