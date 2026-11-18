import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import {
  addWatch, ApiError, cancelWorkOrder, createWorkOrders, errorMessage, getResearchFeed, getSuggestedTopics,
  listWatchlist, refreshResearch, removeWatch, setFeedReaction,
  type FeedItem, type RefreshResult, type SuggestedTopics, type Watch, type WorkMode,
} from '../api/client'
import { safeUrl } from '../inbox/ui'
import { Button, IconButton } from '../ui/Button'
import { Card, EmptyState, Skeleton } from '../ui/Card'
import { Chip } from '../ui/Chip'
import { CloseIcon, PlayIcon, SoundOffIcon, SoundOnIcon, ThumbDownIcon, ThumbUpIcon } from '../ui/icons'
import { Sheet } from '../ui/Sheet'
import { field, link, verdictButton } from '../ui/styles'
import { useToast } from '../ui/useToast'
import { ago, compact, embedSrc, FEED_ORDER, modeLabel } from './format'
import { Embed, ModePicker } from './shared'

const watchLabel = (w: Pick<Watch, 'kind' | 'value'>) => (w.kind === 'hashtag' ? '#' : '@') + w.value
const firstLine = (s: string | null) => s?.split('\n').map((l) => l.trim()).find(Boolean) ?? null

/** What a refresh found, in one toast line. */
function refreshMessage(r: RefreshResult) {
  const parts = [`Trouvé : ${r.stored} nouveau${r.stored > 1 ? 'x' : ''} Reel${r.stored > 1 ? 's' : ''}, ${r.updated} mis à jour.`]
  if (r.hashtags_skipped_budget.length)
    parts.push(`${r.hashtags_skipped_budget.length} hashtag(s) en attente : limite de la semaine atteinte.`)
  const errors = Object.keys(r.errors).length
  if (errors) parts.push(`${errors} sujet(s) en erreur.`)
  if (r.stopped) parts.push('Arrêté avant la fin : limite de requêtes Instagram.')
  return parts.join(' ')
}

/** A Reel plays inline (muted, tap for sound); without media, Instagram's embed. Pauses off screen. */
function InlineVideo({ src, poster }: { src: string; poster?: string }) {
  const ref = useRef<HTMLVideoElement>(null)
  const [playing, setPlaying] = useState(false)
  const [muted, setMuted] = useState(true)

  useEffect(() => {
    const v = ref.current
    if (!v || typeof IntersectionObserver === 'undefined') return
    const io = new IntersectionObserver(([e]) => { if (!e.isIntersecting) v.pause() })
    io.observe(v)
    return () => io.disconnect()
  }, [])

  const play = () => { void ref.current?.play()?.catch(() => {}) }
  return (
    <div data-theme="dark" className="relative overflow-hidden rounded-control bg-black">
      <video ref={ref} src={src} poster={poster} muted={muted} playsInline loop preload="none"
        onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)}
        onClick={() => (ref.current?.paused ? play() : setMuted((m) => !m))}
        className="aspect-[9/16] max-h-[75dvh] w-full object-contain" />
      {!playing && (
        <button type="button" aria-label="Lire le Reel" onClick={play} className="absolute inset-0 grid place-items-center">
          <span className="grid size-14 place-items-center rounded-full bg-black/55 text-white backdrop-blur"><PlayIcon /></span>
        </button>
      )}
      <IconButton label={muted ? 'Activer le son' : 'Couper le son'} icon={muted ? <SoundOffIcon /> : <SoundOnIcon />}
        onClick={() => setMuted((m) => !m)}
        className="absolute top-2 right-2 rounded-full bg-black/55! text-white! backdrop-blur" />
    </div>
  )
}

function ReelMedia({ item }: { item: FeedItem }) {
  const media = safeUrl(item.media_url)
  const poster = safeUrl(item.thumbnail_url) ?? undefined
  if (media && item.media_type === 'VIDEO') return <InlineVideo src={media} poster={poster} />
  const picture = (item.media_type === 'IMAGE' && media) || poster
  if (picture) return <img src={picture} alt="" loading="lazy" className="max-h-[75dvh] w-full rounded-control bg-surface-2 object-contain" />
  const embed = embedSrc(item.embed_url)
  return embed ? <Embed src={embed} title={`Reel ${item.topic ?? item.id}`} /> : null
}

type CardProps = {
  item: FeedItem
  selecting: boolean
  selected: boolean
  onSelect: () => void
  onReact: (r: 'like' | 'dislike' | 'none') => void
  onInstruct: () => void
  onCancel: () => void
}

// Captions are other accounts' words: a quote, never HTML.
function FeedCard({ item, selecting, selected, onSelect, onReact, onInstruct, onCancel }: CardProps) {
  const href = safeUrl(item.permalink)
  const order = item.work_order
  const caption = firstLine(item.caption_quote)
  const stats = [
    item.views != null && `${compact(item.views)} vues`,
    item.likes != null && `${compact(item.likes)} j'aime`,
    item.comments != null && `${compact(item.comments)} commentaires`,
  ].filter(Boolean).join(' · ')
  const topic = item.topic && (item.topic_kind === 'account' ? '@' : '#') + item.topic
  const liked = item.reaction === 'like'
  const disliked = item.reaction === 'dislike'
  return (
    <Card as="li" aria-label={`Reel ${item.id}`} className={`space-y-3 text-sm ${selected ? 'ring-2 ring-accent' : ''}`}>
      <div className="flex flex-wrap items-center gap-2">
        {selecting && (
          <input type="checkbox" aria-label="Choisir ce Reel" checked={selected} disabled={!!order} onChange={onSelect}
            className="size-6 accent-(--color-accent)" />
        )}
        {topic && <span className="font-semibold break-all">{topic}</span>}
        {item.outlier != null && (
          <Chip tone="accent" title="Ce Reel face à la médiane de son compte ou hashtag">
            ×{item.outlier} {item.outlier_metric === 'views' ? 'vues' : "j'aime"}
          </Chip>
        )}
        {item.posted_at && <span className="ml-auto text-xs text-muted">{ago(item.posted_at)}</span>}
      </div>
      <ReelMedia item={item} />
      {stats && <p className="text-muted tabular-nums">{stats}</p>}
      {caption && <q className="line-clamp-2 block break-words">{caption}</q>}
      {order && (
        <div className="flex flex-wrap items-center gap-2 rounded-control bg-surface-2 p-3">
          <Chip tone={FEED_ORDER[order.status][1]}>{FEED_ORDER[order.status][0]}</Chip>
          <span className="text-muted">{modeLabel(order.mode)}</span>
          {order.status === 'new' && <Button size="sm" variant="ghost" className="ml-auto" onClick={onCancel}>Annuler</Button>}
          {order.instruction && <q className="w-full break-words">{order.instruction}</q>}
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <IconButton label="J'aime" aria-pressed={liked} icon={<ThumbUpIcon />}
          className={verdictButton('success', liked)} onClick={() => onReact(liked ? 'none' : 'like')} />
        <IconButton label="Je n'aime pas" aria-pressed={disliked} icon={<ThumbDownIcon />}
          className={verdictButton('danger', disliked)} onClick={() => onReact(disliked ? 'none' : 'dislike')} />
        {!order && !selecting && <Button size="sm" variant="primary" onClick={onInstruct}>Dire à l'IA quoi faire</Button>}
        {href && (
          <a href={href} target="_blank" rel="noopener noreferrer" className={`ml-auto inline-flex min-h-11 items-center ${link}`}>
            Instagram
          </a>
        )}
      </div>
    </Card>
  )
}

/** One Reel, the owner's exact words: one work order. */
function InstructionSheet({ item, onClose, onSent }: { item: FeedItem; onClose: () => void; onSent: () => void }) {
  const [mode, setMode] = useState<WorkMode>('inspired')
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await createWorkOrders([{ source_id: item.id, mode, instruction: text.trim() }])
      onSent()
    } catch (err) {
      setError(errorMessage(err))
      setBusy(false)
    }
  }

  return (
    <Sheet title="Dire à l'IA quoi faire" onClose={onClose}>
      <form lang="fr" onSubmit={(e) => void submit(e)} className="mt-3 space-y-3">
        <ModePicker value={mode} onChange={setMode} />
        <label className="block text-sm font-medium">Ta consigne
          <textarea required value={text} maxLength={500} rows={6} onChange={(e) => setText(e.target.value)}
            placeholder="Ex. : garde le format, fais-en une version sans sucre (tu peux dicter)"
            className={`${field} mt-1 block w-full py-2 text-base`} />
        </label>
        <p className="text-right text-xs text-muted tabular-nums">{text.length}/500</p>
        {error && <p role="alert" className="text-sm text-danger">{error}</p>}
        <Button type="submit" variant="primary" size="lg" loading={busy} className="w-full">Envoyer à l'IA</Button>
      </form>
    </Sheet>
  )
}

/** The watched topics (the watchlist): add, remove, and the one-tap starter hashtags. */
function TopicsEditor({ watch, suggested, onChanged }: { watch: Watch[]; suggested?: SuggestedTopics; onChanged: () => Promise<void> }) {
  const [kind, setKind] = useState<Watch['kind']>('hashtag')
  const [value, setValue] = useState('')
  const [error, setError] = useState<string | null>(null)

  async function act(fn: () => Promise<unknown>) {
    setError(null)
    try {
      await fn()
      await onChanged()
      return true
    } catch (e) {
      setError(errorMessage(e))
      return false
    }
  }
  async function submit(e: FormEvent) {
    e.preventDefault()
    if (value.trim() && await act(() => addWatch(kind, value.trim()))) setValue('')
  }

  const budget = suggested?.hashtag_budget
  const starters = suggested?.topics.filter((t) => !t.watched) ?? []
  return (
    <div className="mt-3 space-y-3 text-sm">
      {watch.length === 0 ? (
        <p className="text-muted">Aucun sujet pour l'instant : choisis-en un ci-dessous.</p>
      ) : (
        <ul aria-label="Sujets suivis" className="flex flex-wrap gap-2">
          {watch.map((w) => (
            <li key={w.id} className="flex items-center rounded-full bg-surface-2 pl-4">
              <span className="break-all">{watchLabel(w)}</span>
              <IconButton variant="ghost" label={`Retirer ${watchLabel(w)}`} icon={<CloseIcon className="size-4" />}
                className="rounded-full text-muted" onClick={() => void act(() => removeWatch(w.id))} />
            </li>
          ))}
        </ul>
      )}
      <form aria-label="Ajouter un sujet" onSubmit={(e) => void submit(e)} className="flex flex-wrap gap-2">
        <select aria-label="Type" value={kind} onChange={(e) => setKind(e.target.value as Watch['kind'])} className={field}>
          <option value="hashtag">Hashtag</option>
          <option value="account">Compte</option>
        </select>
        <input aria-label="Hashtag ou compte" value={value} onChange={(e) => setValue(e.target.value)}
          placeholder={kind === 'hashtag' ? '#fitness' : '@compte'} className={`${field} min-w-0 flex-1`} />
        <Button type="submit" variant="primary">Ajouter</Button>
      </form>
      {error && <p role="alert" className="text-danger">{error}</p>}
      {starters.length > 0 && (
        <div>
          <p className="font-medium">Suggestions</p>
          <div role="group" aria-label="Suggestions" className="mt-1 flex flex-wrap gap-2">
            {starters.map((t) => (
              <Chip key={t.tag} pressed={false} onClick={() => void act(() => addWatch('hashtag', t.tag))}>+ #{t.tag}</Chip>
            ))}
          </div>
        </div>
      )}
      {budget && (
        <p className="text-xs text-muted">
          Chaque nouveau hashtag utilise 1 des {budget.limit} recherches que Meta autorise par 7 jours
          (il en reste {budget.left}) ; le même hashtag relu dans la semaine est gratuit. Ajoute-les un par un.
        </p>
      )}
    </div>
  )
}

/** Tendances: trending Reels of the watched topics; refresh, react, send to work. */
export default function Tendances() {
  const toast = useToast()
  const [topic, setTopic] = useState<string | null>(null)
  const [feed, setFeed] = useState<FeedItem[]>()
  const [feedError, setFeedError] = useState<string | null>(null)
  const [feedKey, setFeedKey] = useState(0) // bumped to reload the feed
  const [watch, setWatch] = useState<Watch[]>()
  const [suggested, setSuggested] = useState<SuggestedTopics>()
  const [refreshing, setRefreshing] = useState(false)
  const [selecting, setSelecting] = useState(false)
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [bulkMode, setBulkMode] = useState<WorkMode>('inspired')
  const [sending, setSending] = useState(false)
  const [instructFor, setInstructFor] = useState<FeedItem | null>(null)

  useEffect(() => {
    let live = true
    getResearchFeed(topic).then((f) => {
      if (!live) return
      setFeed(f)
      setFeedError(null)
    }, (e: unknown) => live && setFeedError(errorMessage(e)))
    return () => { live = false }
  }, [topic, feedKey])
  const reloadFeed = () => setFeedKey((k) => k + 1)

  const loadTopics = useCallback(() => Promise.all([listWatchlist(), getSuggestedTopics()]).then(([w, s]) => {
    setWatch(w)
    setSuggested(s)
    setTopic((t) => (t && !w.some((x) => x.value === t) ? null : t)) // a removed topic stops filtering
  }, (e: unknown) => setFeedError(errorMessage(e))), [])
  useEffect(() => { void loadTopics() }, [loadTopics])

  async function refresh() {
    setRefreshing(true)
    try {
      const r = await refreshResearch()
      setSuggested((s) => s && { ...s, hashtag_budget: r.hashtag_budget })
      toast({ message: refreshMessage(r), duration: 8000 })
      reloadFeed()
    } catch (e) {
      const status = e instanceof ApiError ? e.status : 0
      toast({
        message: status === 409 ? 'Une actualisation est déjà en cours : réessaie dans un instant.'
          : status === 503 ? "Instagram n'est pas encore connecté : rien à actualiser."
            : `Actualisation impossible : ${errorMessage(e)}`,
      })
    } finally {
      setRefreshing(false)
    }
  }

  async function react(item: FeedItem, reaction: 'like' | 'dislike' | 'none') {
    const before = item.reaction
    const set = (r: FeedItem['reaction']) => setFeed((f) => f?.map((x) => (x.id === item.id ? { ...x, reaction: r } : x)))
    set(reaction === 'none' ? null : reaction)
    try {
      await setFeedReaction(item.id, reaction)
    } catch (e) {
      set(before)
      toast({ message: `Non enregistré : ${errorMessage(e)}` })
    }
  }

  async function sendSelected() {
    setSending(true)
    try {
      await createWorkOrders([...selected].map((id) => ({ source_id: id, mode: bulkMode })))
      toast({ message: `${selected.size} Reel${selected.size > 1 ? 's' : ''} envoyé${selected.size > 1 ? 's' : ''} au travail.` })
      setSelected(new Set())
      setSelecting(false)
      reloadFeed()
    } catch (e) {
      toast({ message: `Non envoyé : ${errorMessage(e)}` })
    } finally {
      setSending(false)
    }
  }

  async function cancel(item: FeedItem) {
    try {
      await cancelWorkOrder(item.work_order!.id)
      reloadFeed()
    } catch (e) {
      toast({ message: `Non annulé : ${errorMessage(e)}` })
    }
  }

  function toggle(id: number) {
    setSelected((s) => {
      const next = new Set(s)
      if (!next.delete(id)) next.add(id)
      return next
    })
  }

  const budget = suggested?.hashtag_budget
  return (
    <div className={selecting ? 'pb-36 lg:pb-24' : ''}>
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="primary" size="lg" loading={refreshing} onClick={() => void refresh()}>Actualiser</Button>
        {budget && <p className="text-sm text-muted">{budget.left}/{budget.limit} hashtags restants cette semaine</p>}
        <Button className="ml-auto" variant={selecting ? 'secondary' : 'ghost'} aria-pressed={selecting}
          onClick={() => { setSelecting((s) => !s); setSelected(new Set()) }}>
          {selecting ? 'Terminer' : 'Sélectionner'}
        </Button>
      </div>

      {watch && (
        <div role="group" aria-label="Filtrer par sujet" className="-mx-4 mt-4 flex gap-2 overflow-x-auto px-4 pb-1 lg:mx-0 lg:flex-wrap lg:px-0">
          <Chip pressed={topic === null} onClick={() => setTopic(null)}>Tous</Chip>
          {watch.map((w) => (
            <Chip key={w.id} pressed={topic === w.value} onClick={() => setTopic(w.value)} className="shrink-0">{watchLabel(w)}</Chip>
          ))}
        </div>
      )}
      {watch && (
        <details open={watch.length === 0} className="mt-3 rounded-card border border-line/60 bg-surface p-4 shadow-card">
          <summary className="min-h-6 cursor-pointer font-medium">Gérer les sujets</summary>
          <TopicsEditor watch={watch} suggested={suggested} onChanged={loadTopics} />
        </details>
      )}

      {feedError && <p role="alert" className="mt-4 text-sm text-danger">{feedError}</p>}
      {feed === undefined ? (
        !feedError && <Skeleton className="mt-4 h-96" />
      ) : feed.length === 0 ? (
        <div className="mt-4">
          <EmptyState title="Aucune tendance pour l'instant">
            Ajoute des sujets, puis touche Actualiser : les Reels trouvés arrivent ici.
          </EmptyState>
        </div>
      ) : (
        <ul aria-label="Tendances" className="mt-4 grid items-start gap-4 md:grid-cols-2 xl:grid-cols-3">
          {feed.map((item) => (
            <FeedCard key={item.id} item={item} selecting={selecting} selected={selected.has(item.id)}
              onSelect={() => toggle(item.id)} onReact={(r) => void react(item, r)}
              onInstruct={() => setInstructFor(item)} onCancel={() => void cancel(item)} />
          ))}
        </ul>
      )}

      {selecting && (
        <div role="region" aria-label="Envoyer la sélection"
          className="fixed inset-x-0 bottom-[calc(3.5rem+env(safe-area-inset-bottom))] z-30 border-t border-line bg-surface/95 px-4 py-3 shadow-overlay backdrop-blur-md lg:bottom-0 lg:left-60">
          <div className="mx-auto flex max-w-6xl flex-wrap items-start gap-3">
            <div className="min-w-0 flex-1"><ModePicker value={bulkMode} onChange={setBulkMode} /></div>
            <Button variant="primary" size="lg" disabled={selected.size === 0} loading={sending} onClick={() => void sendSelected()}>
              Envoyer au travail ({selected.size})
            </Button>
          </div>
        </div>
      )}

      {instructFor && (
        <InstructionSheet item={instructFor} onClose={() => setInstructFor(null)} onSent={() => {
          setInstructFor(null)
          toast({ message: "Envoyé à l'IA avec ta consigne." })
          reloadFeed()
        }} />
      )}
    </div>
  )
}
