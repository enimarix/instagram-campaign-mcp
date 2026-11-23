import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router'
import {
  editIdea, errorMessage, getPlanning, holdItem, listVoices, moveItem, releaseIdea, removeIdea, removeItem,
  setStudioPaused, setTimer, startNow,
  type ClaudeIdea, type IdeaEdit, type LineKind, type PlanningItem, type PlanningWait, type Voice,
} from '../api/client'
import { Button } from '../ui/Button'
import { Card, EmptyState, Skeleton } from '../ui/Card'
import { Chip } from '../ui/Chip'
import { PageHeader } from '../ui/PageHeader'
import { Sheet } from '../ui/Sheet'
import { field, link } from '../ui/styles'
import { useToast } from '../ui/useToast'

const POLL_MS = 10_000 // a live page, like Créer and Agent
const UNDO_MS = 5000 // the Toast's own lifetime

const SECTIONS: [PlanningItem['section'], string][] = [
  ['ideas', 'Idées de Claude — à valider'], ['running', 'En cours'], ['next', 'Ensuite'], ['planned', "Runs prévus de l'IA"],
]
const KIND: Record<PlanningItem['kind'], string> = {
  render: 'Rendu', film: 'Film Lemo', order_run: 'Run léger', check_run: 'Vérification', agent_run: "Run de l'IA",
  work_order: 'Commande', change_request: 'Changement', claude_idea: 'Idée de Claude',
}
const WAIT: Record<PlanningWait, string> = {
  gpu_busy: 'attend le GPU', agent_running: 'attend la fin du run', timer: 'attend son minuteur', held: 'En pause', order_grace: 'délai après ton envoi',
  check_grace: 'délai après le dernier rendu',
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

type Removal = { kind: LineKind | 'order' | 'idea'; id: number }

/** What « Retirer » takes out: a waiting render (its job), a film or an owner order / change
 * request still waiting for the light run (its order), Claude's planned idea (its video);
 * else null. */
function removal(i: PlanningItem): Removal | null {
  if (i.kind === 'claude_idea') return i.ids.asset_id === undefined ? null : { kind: 'idea', id: i.ids.asset_id }
  if (i.section !== 'next') return null
  if (i.kind === 'render') return i.ids.job_id === undefined ? null : { kind: 'render', id: i.ids.job_id }
  if (i.ids.order_id === undefined || i.waits_on === 'needs_instruction') return null
  if (i.kind === 'film') return { kind: 'film', id: i.ids.order_id }
  return i.kind === 'work_order' || i.kind === 'change_request' ? { kind: 'order', id: i.ids.order_id } : null
}
const keyOf = (r: Removal) => `${r.kind}:${r.id}`

/** A call with a toast, then onDone; `busy` while it runs. Resolves true when it went through. */
function useAct(onDone: () => void) {
  const toast = useToast()
  const [busy, setBusy] = useState(false)
  const act = async (fn: () => Promise<unknown>, done: string) => {
    setBusy(true)
    try {
      await fn()
      toast({ message: done })
      onDone()
      return true
    } catch (e) {
      toast({ message: `Pas fait : ${errorMessage(e)}` })
      return false
    } finally {
      setBusy(false)
    }
  }
  return { busy, act }
}

/** « Minuteur »: a local date and time (sent as UTC ISO). */
function TimerField({ when, setWhen }: { when: string; setWhen: (v: string) => void }) {
  return (
    <label className="text-xs font-medium">
      Minuteur
      <input type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)}
        className={`${field} mt-1 block px-2 font-normal`} />
    </label>
  )
}

/** On a waiting render or film (the heavy line): « Lancer maintenant », move up / down, hold,
 * « Minuteur » (186-187); « Retirer » on those and on the owner's waiting orders. */
function LineControls({ item: i, onDone, onRemove }: { item: PlanningItem } & Actions) {
  const [when, setWhen] = useState('')
  const { busy, act } = useAct(onDone)
  const out = removal(i)
  if (!out || out.kind === 'idea') return null
  const retirer = <Button size="sm" variant="danger" disabled={busy} onClick={() => onRemove(out)}>Retirer</Button>
  if (out.kind === 'order') return <div className="flex flex-wrap items-end gap-2 pt-1">{retirer}</div>
  const kind = out.kind // narrowed to the line's render | film
  const id = out.id
  const held = i.waits_on === 'held'
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
      <TimerField when={when} setWhen={setWhen} />
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

const PREVIEW_LINES = 3

/** A video Claude planned (188b), in its own colour: nothing renders or is voiced before
 * « Valider » (« Lancer maintenant » and the timer release it too); « Modifier » opens the
 * edit sheet; « Retirer » archives it after the 5 s undo. */
function IdeaCard({ item: i, onDone, onRemove }: { item: PlanningItem } & Actions) {
  const [when, setWhen] = useState('')
  const [editing, setEditing] = useState(false)
  const { busy, act } = useAct(onDone)
  const idea = i.idea
  if (!idea) return null
  const id = idea.asset_id
  const look = [idea.style && `style ${idea.style}`, idea.template ?? 'remix', idea.voice && `voix ${idea.voice}`,
    idea.music && `musique ${idea.music}`].filter(Boolean)
  const timer = () => {
    const iso = new Date(when).toISOString() // the owner's local time, sent as UTC
    return act(() => releaseIdea(id, { at: iso }), `Validée : son rendu attend jusqu'à ${at(iso)}.`)
  }
  return (
    <Card as="article" className="space-y-1.5 border-l-4 border-l-idea text-sm">
      <Chip tone="idea">Idée de Claude</Chip>
      <h3 className="font-semibold break-words">{i.title}</h3>
      <p className="text-muted">{look.join(' · ')}</p>
      {idea.script.length > 0 && (
        <ol aria-label="Ce qui est dit" className="list-decimal space-y-0.5 pl-5">
          {idea.script.slice(0, PREVIEW_LINES).map((l, n) => <li key={n}>{l.text}</li>)}
          {idea.script.length > PREVIEW_LINES && (
            <li className="list-none text-muted">… {idea.script.length - PREVIEW_LINES} ligne(s) de plus</li>
          )}
        </ol>
      )}
      {idea.caption && <p className="break-words whitespace-pre-line"><span className="text-muted">Légende : </span>{idea.caption}</p>}
      {idea.description && <p className="text-muted">{idea.description}</p>}
      {idea.sources.length > 0 && (
        <p className="text-muted">
          Sources :{' '}
          {idea.sources.map((src, n) => (
            <span key={src.url}>{n > 0 && ' · '}<a href={src.url} target="_blank" rel="noreferrer" className={link}>{src.title || src.url}</a></span>
          ))}
        </p>
      )}
      <p className="text-muted">{i.why_here}</p>
      <div className="flex flex-wrap items-end gap-2 pt-1">
        <Button size="sm" variant="primary" disabled={busy}
          onClick={() => void act(() => releaseIdea(id, {}), 'Validée : son rendu entre dans la file.')}>Valider</Button>
        <Button size="sm" disabled={busy}
          onClick={() => void act(() => releaseIdea(id, { now: true }), 'Validée : elle passe en tête de la file.')}>Lancer maintenant</Button>
        <TimerField when={when} setWhen={setWhen} />
        <Button size="sm" disabled={busy || !when} onClick={() => void timer()}>Régler</Button>
        <Button size="sm" disabled={busy} onClick={() => setEditing(true)}>Modifier</Button>
        <Button size="sm" variant="danger" disabled={busy} onClick={() => onRemove({ kind: 'idea', id })}>Retirer</Button>
      </div>
      {editing && <IdeaSheet idea={idea} onClose={() => setEditing(false)} onDone={onDone} />}
    </Card>
  )
}

const TRACK = /^\d+$/ // an Instagram track's audio_id, not one of our beds

/** « Modifier » a planned idea: voice (the voices on), music (a bed, none, or for a motion
 * video an Instagram track's audio_id), the spoken lines, caption, description. Only what
 * changed is sent; the server checks it all again and refuses with the reason. */
function IdeaSheet({ idea, onClose, onDone }: { idea: ClaudeIdea; onClose: () => void; onDone: () => void }) {
  const [voices, setVoices] = useState<Voice[]>([])
  const [voice, setVoice] = useState(idea.voice ?? '')
  const [music, setMusic] = useState(idea.music ?? '')
  const [lines, setLines] = useState(idea.script.map((l) => l.text))
  const [caption, setCaption] = useState(idea.caption ?? '')
  const [description, setDescription] = useState(idea.description ?? '')
  const { busy, act } = useAct(onDone)
  useEffect(() => {
    listVoices().then((v) => setVoices(v.filter((x) => x.enabled)), () => setVoices([]))
  }, [])
  const save = async () => {
    const body: IdeaEdit = {}
    if (voice && voice !== (idea.voice ?? '')) body.voice = voice
    if (music.trim() && music.trim() !== (idea.music ?? '')) body.music = music.trim()
    if (lines.some((l, n) => l !== idea.script[n].text)) body.lines = lines
    if (caption !== (idea.caption ?? '')) body.caption = caption
    if (description !== (idea.description ?? '')) body.description = description
    if (await act(() => editIdea(idea.asset_id, body), 'Idée modifiée.')) onClose()
  }
  return (
    <Sheet title="Modifier l'idée" onClose={onClose} wide>
      <div className="mt-3 space-y-3 text-sm">
        <label className="block font-medium">
          Voix
          <select value={voice} onChange={(e) => setVoice(e.target.value)} className={`${field} mt-1 block w-full`}>
            {!voices.some((v) => v.id === voice) && <option value={voice}>{voice || '—'}</option>}
            {voices.map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}
          </select>
        </label>
        <label className="block font-medium">
          Musique
          <select value={TRACK.test(music) ? '' : music} onChange={(e) => setMusic(e.target.value)}
            className={`${field} mt-1 block w-full`}>
            {(TRACK.test(music) || !idea.music_options.includes(music)) && <option value="">{TRACK.test(music) ? 'son Instagram' : music || '—'}</option>}
            {idea.music_options.map((b) => <option key={b} value={b}>{b === 'none' ? 'aucune' : b}</option>)}
          </select>
        </label>
        {idea.kind === 'motion' && (
          <label className="block font-medium">
            Ou un son Instagram (son audio_id, déjà récupéré par l'IA)
            <input inputMode="numeric" value={TRACK.test(music) ? music : ''} onChange={(e) => setMusic(e.target.value)}
              className={`${field} mt-1 block w-full`} />
          </label>
        )}
        <fieldset className="space-y-2">
          <legend className="font-medium">Ce qui est dit</legend>
          {lines.map((l, n) => (
            <textarea key={n} aria-label={`Ligne ${n + 1}`} value={l} rows={2} disabled={!idea.script[n].editable}
              title={idea.script[n].editable ? undefined : 'Cette ligne réunit plusieurs textes du modèle : elle ne se modifie pas ici.'}
              onChange={(e) => setLines(lines.map((x, k) => (k === n ? e.target.value : x)))}
              className={`${field} block w-full py-2`} />
          ))}
        </fieldset>
        <label className="block font-medium">
          Légende
          <textarea value={caption} rows={3} onChange={(e) => setCaption(e.target.value)} className={`${field} mt-1 block w-full py-2`} />
        </label>
        <label className="block font-medium">
          Description
          <textarea value={description} rows={2} maxLength={400} onChange={(e) => setDescription(e.target.value)}
            className={`${field} mt-1 block w-full py-2`} />
        </label>
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>Annuler</Button>
          <Button variant="primary" disabled={busy} onClick={() => void save()}>Enregistrer</Button>
        </div>
      </div>
    </Sheet>
  )
}

/** The cards of one section, joined by a line (the chain). */
function Chain({ items, ...actions }: { items: PlanningItem[] } & Actions) {
  return (
    <ol>
      {items.map((item, n) => (
        <li key={`${item.kind}-${item.ids.asset_id ?? item.ids.order_id ?? item.ids.run_id ?? item.title}-${n}`}>
          {n > 0 && <div aria-hidden className="ml-6 h-4 w-px bg-line" />}
          {item.kind === 'claude_idea' ? <IdeaCard item={item} {...actions} /> : <ItemCard item={item} {...actions} />}
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
    setPaused(p.paused ?? null)
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
      const call = r.kind === 'idea' ? removeIdea(r.id) : removeItem(r.kind, r.id)
      call.then(() => load(), (e: unknown) => {
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
