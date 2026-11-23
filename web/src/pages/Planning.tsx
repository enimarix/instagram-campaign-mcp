import { useCallback, useEffect, useRef, useState, type ReactNode, type PointerEvent as ReactPointerEvent } from 'react'
import { Link } from 'react-router'
import {
  editIdea, errorMessage, getPlanning, holdItem, launchItems, listVoices, moveItem, placeItem, previewLaunch, previewPlanning, releaseIdea,
  removeIdea, removeItem, rerenderAsset, setStudioPaused, setTimer, startNow,
  type ClaudeIdea, type IdeaEdit, type LaunchItem, type LaunchResult, type LineKind, type Planning as PlanningData, type PlanningHistory, type PlanningItem,
  type PlanningPreview, type PlanningStrip, type PlanningSupply, type PlanningWait, type Voice,
} from '../api/client'
import { Button } from '../ui/Button'
import { Card, EmptyState, Skeleton } from '../ui/Card'
import { Chip } from '../ui/Chip'
import { PageHeader } from '../ui/PageHeader'
import { Sheet } from '../ui/Sheet'
import { field, link, type Tone } from '../ui/styles'
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
  check_grace: 'délai après le dernier rendu', recheck: 'nouvelle vérification prévue',
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
const keyOf = (r: Removal | LaunchItem) => `${r.kind}:${r.id}`

/** What « Lancer » takes (196): a waiting render, film, Claude idea, owner order or change
 * request (by its order, else its video), an AI run not running (its playbook); not one
 * already launched, nor an order waiting for the owner's instruction; else null. */
function launchable(i: PlanningItem): LaunchItem | null {
  if (i.section === 'running' || i.launch_requested) return null
  const { job_id, order_id, asset_id } = i.ids
  switch (i.kind) {
    case 'render': return job_id === undefined ? null : { kind: 'render', id: job_id }
    case 'film': return order_id === undefined ? null : { kind: 'film', id: order_id }
    case 'claude_idea': return asset_id === undefined ? null : { kind: 'claude_idea', id: asset_id }
    case 'work_order':
    case 'change_request':
      if (i.waits_on === 'needs_instruction') return null
      if (order_id !== undefined) return { kind: 'work_order', id: order_id }
      return asset_id === undefined ? null : { kind: 'change_request', id: asset_id }
    default: return i.playbook ? { kind: 'agent_run', id: i.playbook } : null
  }
}
const TO_FRONT: LaunchItem['kind'][] = ['render', 'film', 'claude_idea'] // the rest waits for the machine

function summary(r: LaunchResult) {
  const n = (k: number, one: string, many: string) => `${k} ${k > 1 ? many : one}`
  const parts = [
    r.front.length > 0 && `${n(r.front.length, 'passe', 'passent')} en tête de la file`,
    r.requested.length > 0 && `${n(r.requested.length, 'lancement demandé', 'lancements demandés')} : ${
      r.busy ? 'démarre dès que la machine est libre' : 'démarre dans la minute'}`,
    r.refused.length > 0 && `${n(r.refused.length, 'refusé', 'refusés')} (${r.refused[0].message})`,
  ].filter(Boolean)
  const after = r.paused ? 'Studio en pause : rien ne démarre avant la reprise.' : 'La machine fait un seul travail lourd à la fois.'
  return `${parts.length ? parts.join(' · ') : 'Rien à lancer'}. ${after}`
}

/** « Lancer » one card or many (196): the delay warning first when renders, films or ideas go
 * to the front and push others back (190), then one toast summing it up. */
function useLaunch(onDone: () => void) {
  const toast = useToast()
  const [busy, setBusy] = useState(false)
  const [ask, setAsk] = useState<{ pushed: Pushed; go: () => void } | null>(null)
  const go = async (items: LaunchItem[]) => {
    setAsk(null)
    setBusy(true)
    try {
      toast({ message: summary(await launchItems(items)), duration: 8000 })
      onDone()
    } catch (e) {
      toast({ message: `Pas fait : ${errorMessage(e)}` })
    } finally {
      setBusy(false)
    }
  }
  const launch = async (items: LaunchItem[]) => {
    let pushed: Pushed = []
    if (items.some((l) => TO_FRONT.includes(l.kind))) {
      try {
        pushed = (await previewLaunch(items)).pushed ?? []
      } catch {
        // no preview: the launch says what it refuses
      }
    }
    if (pushed.length === 0) return void go(items)
    setAsk({ pushed, go: () => void go(items) })
  }
  const box = ask && <DelayWarning pushed={ask.pushed} onConfirm={ask.go} onCancel={() => setAsk(null)} />
  return { busy, launch, box }
}
type Launch = ReturnType<typeof useLaunch>['launch']

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
type Act = ReturnType<typeof useAct>['act']

type Pushed = Awaited<ReturnType<typeof previewPlanning>>['pushed']

/** The delay warning (190): before a move or « start now », what it pushes back and by how
 * much (a dry run on the server); confirm or cancel. Nothing pushed back: it goes at once. */
function useGuard(act: Act) {
  const [ask, setAsk] = useState<{ pushed: Pushed; go: () => void } | null>(null)
  const guard = async (p: PlanningPreview, fn: () => Promise<unknown>, done: string) => {
    let pushed: Pushed = []
    try {
      pushed = (await previewPlanning(p)).pushed ?? []
    } catch {
      // no preview: the real call says why it is refused
    }
    if (pushed.length === 0) return void act(fn, done)
    setAsk({ pushed, go: () => { setAsk(null); void act(fn, done) } })
  }
  const box = ask && <DelayWarning pushed={ask.pushed} onConfirm={ask.go} onCancel={() => setAsk(null)} />
  return { guard, box }
}

const PUSHED_SHOWN = 5

function DelayWarning({ pushed, onConfirm, onCancel }: { pushed: Pushed; onConfirm: () => void; onCancel: () => void }) {
  const n = pushed.length
  const what = `${n} ${pushed.every((p) => p.kind === 'render') ? 'rendu' : 'élément'}${n > 1 ? 's' : ''}`
  return (
    <div role="alertdialog" aria-label="Ce que ça repousse" className="mt-2 space-y-2 rounded-card border border-warn bg-warn/12 p-3">
      <p>Repousse {what} d'environ {duration(Math.max(...pushed.map((p) => p.by_s)))}.</p>
      <ul className="list-disc pl-5 text-muted">
        {pushed.slice(0, PUSHED_SHOWN).map((p, k) => <li key={k}>{p.title} · +{duration(p.by_s)}</li>)}
        {n > PUSHED_SHOWN && <li className="list-none">… {n - PUSHED_SHOWN} de plus</li>}
      </ul>
      <div className="flex gap-2">
        <Button size="sm" variant="primary" onClick={onConfirm}>Confirmer</Button>
        <Button size="sm" onClick={onCancel}>Annuler</Button>
      </div>
    </div>
  )
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
  const { guard, box } = useGuard(act)
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
    <div>
      <div className="flex flex-wrap items-end gap-2 pt-1">
        <Button size="sm" variant="primary" disabled={busy}
          onClick={() => void guard({ action: 'start_now', kind, id }, () => startNow(kind, id), 'Passe en tête de la file.')}>
          Lancer maintenant
        </Button>
        <Button size="sm" disabled={busy}
          onClick={() => void guard({ action: 'move', kind, id, by: -1 }, () => moveItem(kind, id, -1), 'Monté d’une place.')}>Monter</Button>
        <Button size="sm" disabled={busy}
          onClick={() => void guard({ action: 'move', kind, id, by: 1 }, () => moveItem(kind, id, 1), 'Descendu d’une place.')}>Descendre</Button>
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
      {box}
    </div>
  )
}

type Actions = {
  onDone: () => void
  onRemove: (r: Removal) => void
  picked: ReadonlySet<string> // keyOf the cards ticked for « Lancer la sélection » (196)
  onPick: (key: string, on: boolean) => void
  onLaunch: Launch
}

/** The card's tick box for « Lancer la sélection » (196), on what can be launched. */
function PickBox({ item: i, picked, onPick }: { item: PlanningItem } & Pick<Actions, 'picked' | 'onPick'>) {
  const l = launchable(i)
  if (!l) return null
  const key = keyOf(l)
  return (
    <label className="-my-2 grid size-11 place-items-center" title="Sélectionner pour « Lancer la sélection »">
      <input type="checkbox" aria-label={`Sélectionner : ${i.title}`} className="size-5 accent-accent"
        checked={picked.has(key)} onChange={(e) => onPick(key, e.target.checked)} />
    </label>
  )
}

const REQUESTED = 'Lancement demandé — démarre dès que la machine est libre'

const MAKES: PlanningItem['kind'][] = ['render', 'film', 'work_order', 'change_request'] // each ends as a video

/** The card's own generation slot in plain words (195): running since, the estimate, the
 * timer, held, or why it has no time. */
function Slot({ item: i }: { item: PlanningItem }) {
  const timed = i.est_start && i.est_ready && i.est_duration_s !== null
  const when = i.section === 'running' && i.est_start ? `En cours depuis ${at(i.est_start)}`
    : i.waits_on === 'held' ? 'En pause'
      : i.not_before ? `Minuteur : ${at(i.not_before)}`
        : timed ? `${MAKES.includes(i.kind) ? 'Génération prévue' : 'Prévu'} vers ${at(i.est_start!)}`
          : `Pas d'heure : ${i.waits_on ? WAIT[i.waits_on] ?? i.waits_on : 'rien ne part sans toi'}.`
  return (
    <p className={`tabular-nums ${i.late_s ? 'text-warn' : timed || i.waits_on === 'held' ? '' : 'text-muted'}`}>
      {when}{timed && ` · ${duration(i.est_duration_s!)} · prête ~${at(i.est_ready!)}`}
    </p>
  )
}

function ItemCard({ item: i, grip, ...actions }: { item: PlanningItem; grip?: ReactNode } & Actions) {
  const look = [i.style && `style ${i.style}`, i.engine && `moteur ${i.engine}`, i.voice && `voix ${i.voice}`].filter(Boolean)
  const l = launchable(i)
  return (
    <Card as="article" className="space-y-1.5 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <PickBox item={i} {...actions} />
        {grip}
        <Chip tone={i.section === 'running' ? 'explore' : 'info'}>{KIND[i.kind]}</Chip>
        {i.launch_requested && <Chip tone="success">{REQUESTED}</Chip>}
        {i.waits_on && i.waits_on !== 'held' && <Chip tone="warn">{WAIT[i.waits_on] ?? i.waits_on}</Chip>}
        {!!i.late_s && <Chip tone="warn">en retard de {Math.max(1, Math.round(i.late_s / 60))} min</Chip>}
      </div>
      <h3 className="font-semibold break-words">{i.title}</h3>
      <Origin item={i} />
      {look.length > 0 && <p className="text-muted">{look.join(' · ')}</p>}
      <Slot item={i} />
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
      {MAKES.includes(i.kind) && (
        <p className="text-muted">→ vérification par l'IA → <Link to="/inbox" className={link}>Inbox</Link></p>
      )}
      {l && !TO_FRONT.includes(l.kind) && ( // a render's or film's is in LineControls
        <div className="pt-1">
          <Button size="sm" variant="primary" onClick={() => actions.onLaunch([l])}>Lancer maintenant</Button>
        </div>
      )}
      <LineControls item={i} {...actions} />
    </Card>
  )
}

const PREVIEW_LINES = 3

/** A video Claude planned (188b), in its own colour: nothing renders or is voiced before
 * « Valider » (« Lancer maintenant » and the timer release it too); « Modifier » opens the
 * edit sheet; « Retirer » archives it after the 5 s undo. */
function IdeaCard({ item: i, onDone, onRemove, picked, onPick }: { item: PlanningItem } & Actions) {
  const [when, setWhen] = useState('')
  const [editing, setEditing] = useState(false)
  const { busy, act } = useAct(onDone)
  const { guard, box } = useGuard(act)
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
      <div className="flex flex-wrap items-center gap-2">
        <PickBox item={i} picked={picked} onPick={onPick} />
        <Chip tone="idea">Idée de Claude</Chip>
      </div>
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
          onClick={() => void guard({ action: 'release', kind: 'idea', id }, () => releaseIdea(id, { now: true }),
            'Validée : elle passe en tête de la file.')}>Lancer maintenant</Button>
        <TimerField when={when} setWhen={setWhen} />
        <Button size="sm" disabled={busy || !when} onClick={() => void timer()}>Régler</Button>
        <Button size="sm" disabled={busy} onClick={() => setEditing(true)}>Modifier</Button>
        <Button size="sm" variant="danger" disabled={busy} onClick={() => onRemove({ kind: 'idea', id })}>Retirer</Button>
      </div>
      {box}
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

const KEY_IDS = ['job_id', 'order_id', 'asset_id', 'run_id'] as const
/** A card's React key: its kind and its own id (no index: a card leaving above must not
 * remount the ones below, 194), the title for a run that has none. */
const itemKey = (i: PlanningItem) => {
  const id = KEY_IDS.find((k) => i.ids[k] !== undefined)
  return id ? `${i.kind}-${id}-${i.ids[id]}` : `${i.kind}-${i.title}`
}

/** `items` with the ones `order` names (by itemKey) in its order, in the places they hold. */
function arrange(items: PlanningItem[], order: string[] | null) {
  if (!order) return items
  const rank = new Map(order.map((k, n) => [k, n]))
  const ranked = items.filter((i) => rank.has(itemKey(i))).sort((a, b) => rank.get(itemKey(a))! - rank.get(itemKey(b))!)
  let n = 0
  return items.map((i) => (rank.has(itemKey(i)) ? ranked[n++] : i))
}

type Place = (item: PlanningItem, index: number) => Promise<unknown>
const EDGE_PX = 80 // a drag this close to the screen's top / bottom scrolls the page
const SCROLL_PX = 12 // per frame

/** Drag and drop (195): a waiting render or film (it has a line_index) is dragged by its grip
 * with the mouse or a finger (pointer events on the window; the grip's touch-none keeps the
 * page from scrolling); the cards reorder live as it crosses a neighbour's middle. The drop
 * sends the line index (line.place: among the others not held) of the card it lands before,
 * and the new order stays shown, through any poll, until the call and the reload answer. */
function useDrag(items: PlanningItem[], onPlace?: Place) {
  const list = useRef<HTMLOListElement>(null)
  const [order, setOrder] = useState<string[] | null>(null)
  const [dragging, setDragging] = useState<string | null>(null)
  const shown = arrange(items, order)
  const movable = shown.filter((i) => i.line_index != null)
  const grab = (e: ReactPointerEvent, me: PlanningItem) => {
    if (!onPlace || e.button !== 0 || dragging) return
    e.preventDefault()
    const key = itemKey(me)
    const start = movable.map(itemKey)
    const byKey = new Map(movable.map((i) => [itemKey(i), i]))
    let now = start
    setDragging(key)
    setOrder(start)
    const middle = (k: string) => {
      const r = list.current?.querySelector(`[data-drag="${k}"]`)?.getBoundingClientRect()
      return r ? r.top + r.height / 2 : 0
    }
    let y = e.clientY
    const reorder = () => {
      const rest = now.filter((k) => k !== key)
      const to = rest.filter((k) => middle(k) < y).length
      const next = [...rest.slice(0, to), key, ...rest.slice(to)]
      if (next.join() !== now.join()) setOrder((now = next))
    }
    const move = (ev: PointerEvent) => {
      y = ev.clientY
      reorder()
    }
    // Near the screen's top or bottom edge the page scrolls: a tall card's neighbour is often
    // off screen, on a phone above all.
    let frame = 0
    const roll = () => {
      const by = y < EDGE_PX ? -SCROLL_PX : y > window.innerHeight - EDGE_PX ? SCROLL_PX : 0
      const page = document.scrollingElement
      if (by && page) {
        page.scrollTop += by
        reorder()
      }
      frame = requestAnimationFrame(roll)
    }
    frame = requestAnimationFrame(roll)
    const end = (ev: PointerEvent) => {
      cancelAnimationFrame(frame)
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', end)
      window.removeEventListener('pointercancel', end)
      setDragging(null)
      if (ev.type === 'pointercancel' || now.join() === start.join()) return setOrder(null)
      // ponytail: "before the next card" in the line; a timer or a film's wait can show the
      // cards in another order than the line's, the drop then lands next to that card.
      const after = byKey.get(now[now.indexOf(key) + 1])
      const mine = me.line_index!
      const index = after ? after.line_index! - (after.line_index! > mine ? 1 : 0) : start.length - 1
      void onPlace(me, index).finally(() => setOrder(null))
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', end)
    window.addEventListener('pointercancel', end)
  }
  const grip = (i: PlanningItem) => i.line_index != null && onPlace && (
    <button type="button" tabIndex={-1} aria-label="Glisser pour déplacer" title="Glisser pour changer sa place (ou Monter / Descendre)"
      onPointerDown={(e) => grab(e, i)}
      className="-my-2 -ml-2 grid size-11 cursor-grab touch-none place-items-center rounded text-lg text-muted select-none active:cursor-grabbing">
      ⠿
    </button>
  )
  return { list, shown, dragging, grip }
}

/** The cards of one section, joined by a line (the chain); the waiting renders and films
 * move by drag and drop (useDrag). */
function Chain({ items, onPlace, ...actions }: { items: PlanningItem[]; onPlace?: Place } & Actions) {
  const { list, shown, dragging, grip } = useDrag(items, onPlace)
  return (
    <ol ref={list} className={dragging ? 'select-none' : undefined}>
      {shown.map((item, n) => {
        const key = itemKey(item)
        return (
          <li key={key} data-drag={item.line_index != null ? key : undefined}
            className={key === dragging ? 'rounded-card opacity-80 ring-2 ring-accent' : undefined}>
            {n > 0 && <div aria-hidden className="ml-6 h-4 w-px bg-line" />}
            {item.kind === 'claude_idea' ? <IdeaCard item={item} {...actions} /> : <ItemCard item={item} grip={grip(item)} {...actions} />}
          </li>
        )
      })}
    </ol>
  )
}

const LANES: [PlanningStrip['blocks'][number]['lane'], string, string][] = [
  ['render', 'Rendus', 'bg-explore'], ['film', 'Films Lemo', 'bg-info'], ['run', "Runs de l'IA", 'bg-accent'],
]
const HOUR = 3_600_000

/** The next 24 h (190): one lane each for renders, films and the AI's runs, from the chain's
 * ETAs (a late one in orange), the queued posts as ticks, now at the left edge. Scrolls
 * sideways on a phone. */
function Strip({ strip }: { strip: PlanningStrip }) {
  const t0 = Date.parse(strip.start)
  const span = Date.parse(strip.end) - t0
  const x = (iso: string) => ((Date.parse(iso) - t0) / span) * 100
  const hours: number[] = [] // every 3 h on the hour, owner-local (the browser's)
  for (let t = Math.ceil(t0 / HOUR) * HOUR; t < t0 + span; t += HOUR) if (new Date(t).getHours() % 3 === 0) hours.push(t)
  const label = (b: PlanningStrip['blocks'][number]) => `${KIND[b.kind]} : ${b.title}, ${at(b.start)} → ${at(b.end)}${b.late ? ', en retard' : ''}`
  return (
    <section aria-label="Les prochaines 24 h" className="mb-6">
      <h2 className="mb-2 font-semibold">Les prochaines 24 h</h2>
      <div className="overflow-x-auto rounded-card border border-line bg-surface p-2">
        <div className="relative min-w-[720px] pb-5">
          {hours.map((t) => (
            <div key={t} aria-hidden className="absolute inset-y-0 border-l border-line" style={{ left: `${x(new Date(t).toISOString())}%` }}>
              <span className="absolute bottom-0 -translate-x-1/2 text-xs tabular-nums text-muted">
                {new Date(t).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })}
              </span>
            </div>
          ))}
          <div aria-label="Maintenant" className="absolute inset-y-0 left-0 z-10 w-0.5 bg-danger" />
          {LANES.map(([lane, name, color]) => (
            <ul key={lane} aria-label={name} className="relative my-1 h-6">
              {strip.blocks.filter((b) => b.lane === lane).map((b, n) => (
                <li key={n} title={label(b)} aria-label={label(b)}
                  className={`absolute inset-y-0 rounded border border-surface ${b.late ? 'bg-warn' : color}`}
                  style={{ left: `${x(b.start)}%`, width: `${x(b.end) - x(b.start)}%`, minWidth: 3 }} />
              ))}
            </ul>
          ))}
          <ul aria-label="Publications" className="relative h-3">
            {strip.posts.map((p) => (
              <li key={p} title={`Publication ${at(p)}`} aria-label={`Publication ${at(p)}`}
                className="absolute inset-y-0 w-1 rounded bg-success" style={{ left: `${x(p)}%` }} />
            ))}
          </ul>
        </div>
      </div>
      <p className="mt-1 flex flex-wrap gap-3 text-xs text-muted">
        {LANES.map(([lane, name, color]) => <span key={lane}><span className={`mr-1 inline-block size-2.5 rounded-sm ${color}`} />{name}</span>)}
        <span><span className="mr-1 inline-block size-2.5 rounded-sm bg-success" />Publications</span>
        <span><span className="mr-1 inline-block size-2.5 rounded-sm bg-warn" />En retard</span>
      </p>
    </section>
  )
}

const WEEK_DAYS = 7 // the gauge's full bar

/** The supply gauge (190): approved + bench videos against posts per day, orange under a day,
 * and what the line and Claude's cards would add once done. */
function SupplyGauge({ supply: s }: { supply: PlanningSupply }) {
  const until = new Date(`${s.until}T12:00`).toLocaleDateString('fr-FR', { weekday: 'long' })
  const days = s.days < 1 ? 'moins d’un jour' : `${s.days.toLocaleString('fr-FR')} jour${s.days >= 2 ? 's' : ''}`
  const more = [s.making > 0 && `+ ${s.making} en fabrication`, s.ideas > 0 && `+ ${s.ideas} idée(s) de Claude`].filter(Boolean)
  return (
    <div className={`mb-6 space-y-1.5 rounded-card border bg-surface p-3 text-sm ${s.low ? 'border-warn' : 'border-line'}`}>
      <p className={s.low ? 'text-warn' : undefined}>
        <strong>Réserve : {days}</strong> (jusqu'à {until})
      </p>
      <div role="meter" aria-label="Réserve" aria-valuenow={s.days} aria-valuemin={0} aria-valuemax={WEEK_DAYS}
        aria-valuetext={`${days}`} className="h-1.5 overflow-hidden rounded-full bg-surface-2">
        <div className={`h-full ${s.low ? 'bg-warn' : 'bg-success'}`} style={{ width: `${Math.min(100, (s.days / WEEK_DAYS) * 100)}%` }} />
      </div>
      <p className="text-muted">
        {s.approved} approuvée(s) + {s.bench} sur le banc, {s.per_day} par jour{more.length > 0 && ` · une fois faites : ${more.join(', ')}`}
      </p>
    </div>
  )
}

const DONE: Record<PlanningHistory['kind'], [string, Tone]> = {
  done: ['Rendu fini', 'success'], failed: ['Rendu raté', 'danger'], removed: ['Retiré du planning', 'neutral'],
  dropped: ['Écartée par la vérification', 'warn'], run: ["Run de l'IA", 'info'],
}
const RUN_STATUS: Record<string, string> = { running: 'en cours', succeeded: 'réussi', failed: 'échoué', cancelled: 'annulé' }

/** Today's history (190), under the chain: finished renders (to the Inbox), failed videos
 * (one row each, 195: the newest failure's reason, how many tries) with « Relancer » (the
 * asset's re-render with its own recipe), removed, dropped by the check, and today's AI runs. */
function History({ rows, onDone }: { rows: PlanningHistory[]; onDone: () => void }) {
  const { busy, act } = useAct(onDone)
  if (rows.length === 0) return null
  return (
    <section aria-label="Aujourd'hui" className="mt-6">
      <h2 className="mb-2 font-semibold">Aujourd'hui</h2>
      <ul className="space-y-2 text-sm">
        {rows.map((r, n) => {
          const [what, tone] = DONE[r.kind]
          const { asset_id: id, recipe } = r
          return (
            <li key={n} className="flex flex-wrap items-center gap-2">
              <span className="tabular-nums text-muted">{at(r.at)}</span>
              <Chip tone={tone}>{what}</Chip>
              <span className="break-words">{r.title}</span>
              {r.reason && <span className="text-muted">: {r.reason}</span>}
              {!!r.tries && r.tries > 1 && <span className="text-muted">· {r.tries} essais</span>}
              {r.status && <span className="text-muted">{RUN_STATUS[r.status] ?? r.status}</span>}
              {r.kind === 'done' && <Link to="/inbox" className={link}>Inbox</Link>}
              {recipe && id !== null && (
                <Button size="sm" disabled={busy}
                  onClick={() => void act(() => rerenderAsset(id, recipe), 'Relancé : le rendu revient dans la file.')}>Relancer</Button>
              )}
            </li>
          )
        })}
      </ul>
    </section>
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
 * or film can start now, wait for a timer (186), move (by drag and drop too, 195), be held or
 * removed, and the whole studio can pause (187). Remove follows the Inbox rule: the card leaves at once and the call
 * fires when the 5 s undo closes, or at once when the page is hidden or left. */
export default function Planning() {
  const [items, setItems] = useState<PlanningItem[] | null>(null)
  const [paused, setPaused] = useState<string | null>(null)
  const [extras, setExtras] = useState<Partial<PlanningData>>({})
  const [error, setError] = useState<string | null>(null)
  const [gone, setGone] = useState<ReadonlySet<string>>(new Set())
  const [picked, setPicked] = useState<ReadonlySet<string>>(new Set())
  const pending = useRef(new Map<string, { timer: ReturnType<typeof setTimeout>; run: () => void }>())
  const toast = useToast()
  const seq = useRef(0)
  const load = useCallback(() => {
    const n = ++seq.current // only the newest load lands: a poll sent before a drop never undoes it
    return getPlanning().then((p) => {
      if (n !== seq.current) return
      setItems(p.items)
      setPaused(p.paused ?? null)
      setExtras(p)
      setError(null)
    }, (e: unknown) => {
      if (n === seq.current) setError(errorMessage(e))
    })
  }, [])
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
  const place: Place = (i, index) => {
    const r = removal(i)
    if (r?.kind !== 'render' && r?.kind !== 'film') return Promise.resolve()
    return placeItem(r.kind, r.id, index).then(() => {
      toast({ message: 'Déplacé dans la file.' })
      return load()
    }, (e: unknown) => toast({ message: `Pas fait : ${errorMessage(e)}` }))
  }
  const visible = items?.filter((i) => {
    const r = removal(i)
    return !r || !gone.has(keyOf(r))
  })
  const { busy: launching, launch, box } = useLaunch(() => {
    setPicked(new Set())
    void load()
  })
  const onPick = (key: string, on: boolean) => setPicked((p) => {
    const next = new Set(p)
    if (on) next.add(key)
    else next.delete(key)
    return next
  })
  // on-screen order (the sections' order): the selection keeps it at the front of the line
  const launchables = SECTIONS.flatMap(([id]) => (visible ?? []).filter((i) => i.section === id))
    .map(launchable).filter((l): l is LaunchItem => l !== null)
  const chosen = launchables.filter((l) => picked.has(keyOf(l)))
  const actions = { onDone: () => void load(), onRemove: remove, picked, onPick, onLaunch: launch }

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
      {extras.supply && <SupplyGauge supply={extras.supply} />}
      {extras.strip && <Strip strip={extras.strip} />}
      {visible === undefined ? (!error && <Skeleton className="h-32" />) : visible.length === 0 ? (
        <EmptyState title="Rien de prévu">Aucun rendu en file, aucune commande en attente, aucun run de l'IA dans les 24 h.</EmptyState>
      ) : (
        <div className="space-y-6">
          {SECTIONS.map(([id, title]) => {
            const mine = visible.filter((i) => i.section === id)
            return mine.length > 0 && (
              <section key={id} aria-label={title}>
                <h2 className="mb-2 font-semibold">{title}</h2>
                <Chain items={mine} {...actions} onPlace={id === 'next' ? place : undefined} />
              </section>
            )
          })}
        </div>
      )}
      {extras.history && <History rows={extras.history} onDone={() => void load()} />}
      {launchables.length > 0 && (
        <div role="region" aria-label="Lancer"
          className="sticky bottom-[calc(3.5rem+env(safe-area-inset-bottom))] z-20 mt-6 rounded-card border border-line bg-surface/95 p-3 text-sm shadow-overlay backdrop-blur-md lg:bottom-4">
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" variant="primary" disabled={launching || chosen.length === 0}
              onClick={() => void launch(chosen)}>Lancer la sélection ({chosen.length})</Button>
            <Button size="sm" disabled={launching} onClick={() => void launch(launchables)}>Tout lancer</Button>
            {chosen.length > 0 && <Button size="sm" variant="ghost" onClick={() => setPicked(new Set())}>Désélectionner</Button>}
            <span className="text-muted">Un seul travail lourd à la fois : le reste démarre dès que la machine est libre.</span>
          </div>
          {box}
        </div>
      )}
    </section>
  )
}
