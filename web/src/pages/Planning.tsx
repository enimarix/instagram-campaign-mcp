import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router'
import {
  errorMessage, getPlanning, holdItem, moveItem, removeItem, setStudioPaused, setTimer, startNow,
  type LineKind, type PlanningItem, type PlanningWait,
} from '../api/client'
import { Button } from '../ui/Button'
import { Card, EmptyState, Skeleton } from '../ui/Card'
import { Chip } from '../ui/Chip'
import { PageHeader } from '../ui/PageHeader'
import { field, link } from '../ui/styles'
import { useToast } from '../ui/useToast'

const POLL_MS = 10_000 // a live page, like Créer and Agent
const UNDO_MS = 5000 // the Toast's own lifetime

const SECTIONS: [PlanningItem['section'], string][] = [
  ['running', 'En cours'], ['next', 'Ensuite'], ['planned', "Runs prévus de l'IA"],
]
const KIND: Record<PlanningItem['kind'], string> = {
  render: 'Rendu', film: 'Film Lemo', order_run: 'Run léger', agent_run: "Run de l'IA",
  work_order: 'Commande', change_request: 'Changement',
}
const WAIT: Record<PlanningWait, string> = {
  gpu_busy: 'attend le GPU', agent_running: 'attend la fin du run', timer: 'attend son minuteur', held: 'En pause', order_grace: 'délai après ton envoi',
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

type Removal = { kind: LineKind | 'order'; id: number }

/** What « Retirer » takes out: a waiting render (its job), a film or an owner order / change
 * request still waiting for the light run (its order); else null. */
function removal(i: PlanningItem): Removal | null {
  if (i.section !== 'next') return null
  if (i.kind === 'render') return i.ids.job_id === undefined ? null : { kind: 'render', id: i.ids.job_id }
  if (i.ids.order_id === undefined || i.waits_on === 'needs_instruction') return null
  if (i.kind === 'film') return { kind: 'film', id: i.ids.order_id }
  return i.kind === 'work_order' || i.kind === 'change_request' ? { kind: 'order', id: i.ids.order_id } : null
}
const keyOf = (r: Removal) => `${r.kind}:${r.id}`

/** On a waiting render or film (the heavy line): « Lancer maintenant », move up / down, hold,
 * « Minuteur » (186-187); « Retirer » on those and on the owner's waiting orders. */
function LineControls({ item: i, onDone, onRemove }: { item: PlanningItem } & Actions) {
  const toast = useToast()
  const [when, setWhen] = useState('')
  const [busy, setBusy] = useState(false)
  const out = removal(i)
  if (!out) return null
  const retirer = <Button size="sm" variant="danger" disabled={busy} onClick={() => onRemove(out)}>Retirer</Button>
  if (out.kind === 'order') return <div className="flex flex-wrap items-end gap-2 pt-1">{retirer}</div>
  const kind = out.kind // narrowed to the line's render | film
  const id = out.id
  const held = i.waits_on === 'held'
  const act = async (fn: () => Promise<unknown>, done: string) => {
    setBusy(true)
    try {
      await fn()
      toast({ message: done })
      onDone()
    } catch (e) {
      toast({ message: `Pas fait : ${errorMessage(e)}` })
    } finally {
      setBusy(false)
    }
  }
  const timer = () => {
    const iso = new Date(when).toISOString() // the owner's local time, sent as UTC
    return act(() => setTimer(kind, id, iso), `Minuteur réglé : pas avant ${at(iso)}.`)
  }
  return (
    <div className="flex flex-wrap items-end gap-2 pt-1">
      <Button size="sm" variant="primary" disabled={busy}
        onClick={() => void act(() => startNow(kind, id), 'Passe en tête de la file.')}>Lancer maintenant</Button>
      <Button size="sm" disabled={busy} onClick={() => void act(() => moveItem(kind, id, -1), 'Monté d’une place.')}>Monter</Button>
      <Button size="sm" disabled={busy} onClick={() => void act(() => moveItem(kind, id, 1), 'Descendu d’une place.')}>Descendre</Button>
      <Button size="sm" disabled={busy}
        onClick={() => void act(() => holdItem(kind, id, !held), held ? 'Repris : il retrouve sa place.' : 'En pause : il ne bloque pas la file.')}>
        {held ? 'Reprendre' : 'Mettre en pause'}
      </Button>
      <label className="text-xs font-medium">
        Minuteur
        <input type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)}
          className={`${field} mt-1 block px-2 font-normal`} />
      </label>
      <Button size="sm" disabled={busy || !when} onClick={() => void timer()}>Régler</Button>
      {i.not_before && (
        <Button size="sm" variant="ghost" disabled={busy}
          onClick={() => void act(() => setTimer(kind, id, null), 'Minuteur retiré.')}>Retirer le minuteur</Button>
      )}
      {retirer}
    </div>
  )
}

type Actions = { onDone: () => void; onRemove: (r: Removal) => void }

function ItemCard({ item: i, ...actions }: { item: PlanningItem } & Actions) {
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
      {i.not_before && <p className="tabular-nums">Minuteur : pas avant {at(i.not_before)}</p>}
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
      <LineControls item={i} {...actions} />
    </Card>
  )
}

/** The cards of one section, joined by a line (the chain). */
function Chain({ items, ...actions }: { items: PlanningItem[] } & Actions) {
  return (
    <ol>
      {items.map((item, n) => (
        <li key={`${item.kind}-${item.ids.asset_id ?? item.ids.order_id ?? item.ids.run_id ?? item.title}-${n}`}>
          {n > 0 && <div aria-hidden className="ml-6 h-4 w-px bg-line" />}
          <ItemCard item={item} {...actions} />
        </li>
      ))}
    </ol>
  )
}

/** « Tout mettre en pause » (187): nothing heavy starts while it is on; what runs finishes. */
function PauseSwitch({ paused, onChanged }: { paused: string | null; onChanged: (since: string | null) => void }) {
  const toast = useToast()
  const [busy, setBusy] = useState(false)
  const flip = async (on: boolean) => {
    setBusy(true)
    try {
      onChanged((await setStudioPaused(on)).paused)
      toast({ message: on ? 'Studio en pause : rien ne démarre, ce qui tourne finit.' : 'Studio repris : la file repart.' })
    } catch (e) {
      toast({ message: `Pas fait : ${errorMessage(e)}` })
    } finally {
      setBusy(false)
    }
  }
  return (
    <label className="flex min-h-11 items-center gap-2 text-sm font-medium">
      <input type="checkbox" role="switch" className="size-5 accent-accent" checked={paused !== null} disabled={busy}
        onChange={(e) => void flip(e.target.checked)} />
      Tout mettre en pause
    </label>
  )
}

/** Planning (185): what renders next and when, in the worker's real order; a waiting render
 * or film can start now, wait for a timer (186), move, be held or removed, and the whole
 * studio can pause (187). Remove follows the Inbox rule: the card leaves at once and the call
 * fires when the 5 s undo closes, or at once when the page is hidden or left. */
export default function Planning() {
  const [items, setItems] = useState<PlanningItem[] | null>(null)
  const [paused, setPaused] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [gone, setGone] = useState<ReadonlySet<string>>(new Set())
  const pending = useRef(new Map<string, { timer: ReturnType<typeof setTimeout>; run: () => void }>())
  const toast = useToast()
  const load = useCallback(() => getPlanning().then((p) => {
    setItems(p.items)
    setPaused(p.paused)
    setError(null)
  }, (e: unknown) => setError(errorMessage(e))), [])
  useEffect(() => {
    void load()
    const t = setInterval(() => void load(), POLL_MS) // a failed load does not stop it
    return () => clearInterval(t)
  }, [load])
  useEffect(() => {
    const flush = () => pending.current.forEach((p) => p.run())
    const hidden = () => document.visibilityState === 'hidden' && flush()
    document.addEventListener('visibilitychange', hidden)
    window.addEventListener('pagehide', flush)
    return () => {
      document.removeEventListener('visibilitychange', hidden)
      window.removeEventListener('pagehide', flush)
      flush() // leaving the page commits what is still waiting
    }
  }, [])

  const show = (key: string, on: boolean) => setGone((g) => {
    const next = new Set(g)
    if (on) next.delete(key)
    else next.add(key)
    return next
  })
  function remove(r: Removal) {
    const key = keyOf(r)
    if (pending.current.has(key)) return
    show(key, false)
    const run = () => {
      clearTimeout(timer)
      pending.current.delete(key)
      removeItem(r.kind, r.id).then(() => load(), (e: unknown) => {
        show(key, true)
        toast({ message: `Pas retiré : ${errorMessage(e)}` })
      })
    }
    const timer = setTimeout(run, UNDO_MS)
    pending.current.set(key, { timer, run })
    toast({
      message: 'Retiré du planning.',
      action: {
        label: 'Annuler',
        onClick: () => {
          clearTimeout(timer)
          pending.current.delete(key)
          show(key, true)
        },
      },
    })
  }
  const visible = items?.filter((i) => {
    const r = removal(i)
    return !r || !gone.has(keyOf(r))
  })

  return (
    <section>
      <PageHeader title="Planning" actions={<PauseSwitch paused={paused} onChanged={setPaused} />}>
        Ce que le studio fait ensuite et quand. Toutes les heures sont estimées.
      </PageHeader>
      {paused && (
        <p role="status" className="mb-3 rounded-card border border-line bg-surface-2 p-3 text-sm">
          Studio en pause depuis {at(paused)} : rien ne démarre (rendus, films, runs de l'IA). Ce qui tournait finit.
        </p>
      )}
      {error && <p role="alert" className="mb-3 text-sm text-danger">{error}</p>}
      {visible === undefined ? (!error && <Skeleton className="h-32" />) : visible.length === 0 ? (
        <EmptyState title="Rien de prévu">Aucun rendu en file, aucune commande en attente, aucun run de l'IA dans les 24 h.</EmptyState>
      ) : (
        <div className="space-y-6">
          {SECTIONS.map(([id, title]) => {
            const mine = visible.filter((i) => i.section === id)
            return mine.length > 0 && (
              <section key={id} aria-label={title}>
                <h2 className="mb-2 font-semibold">{title}</h2>
                <Chain items={mine} onDone={() => void load()} onRemove={remove} />
              </section>
            )
          })}
        </div>
      )}
    </section>
  )
}
