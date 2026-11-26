import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { cancelWorkOrder, confirmWorkOrder, errorMessage, listStyleCatalog, listWorkOrders, type CatalogStyle, type OrderMethod, type WorkOrder, type WorkOrderStatus } from '../api/client'
import { stage } from '../create/prompt'
import { safeUrl } from '../inbox/ui'
import { StylePicker } from '../launch/StylePicker'
import { REA_FILM, styleLabel, useStyles } from '../launch/useStyles'
import { ago, embedSrc } from '../trending/format'
import { Embed } from '../trending/shared'
import { Button } from '../ui/Button'
import { Card, EmptyState, Skeleton } from '../ui/Card'
import { Chip } from '../ui/Chip'
import { PageHeader } from '../ui/PageHeader'
import { field, link } from '../ui/styles'
import { useToast } from '../ui/useToast'

const CANCELLED = 'annulée par le propriétaire' // work_orders.CANCELLED: « Retirer »

const ROUTES: { id: OrderMethod; label: string; hint: string }[] = [
  { id: 'style', label: 'Même vidéo, style existant', hint: "L'IA refait la même vidéo (idée, rythme, fin) dans le style choisi, sans rien reprendre du Reel." },
  { id: 'new_style', label: 'Nouveau style', hint: "L'IA décrit le style de ce Reel, il est construit pour cette vidéo, puis elle la fait dedans." },
  { id: 'rea', label: 'rea-video', hint: "Le Reel est décomposé plan par plan (rea-video : durée, cadrage, textes, son). Sur Auto, il est recopié plan par plan en code, avec macroBody, sans attendre de style ; un style choisi : refait dans ce style." },
]

/** Each card stays where it is, its chip following it, until its video is in the Inbox. */
const SHOWN: WorkOrderStatus[] = ['received', 'confirmed', 'scheduled', 'in_production', 'skipped']
// before « Lancer » the words of this page; after, the stage « Créer » shows (create/prompt.ts)
const chip = (o: WorkOrder): [string, 'warn' | 'info' | ReturnType<typeof stage>[1]] =>
  o.status === 'received' ? ['À confirmer', 'warn'] : o.status === 'confirmed' ? ['Dans le Planning', 'info']
    : o.waits_for_style ? ['Attend son nouveau style', 'warn'] : stage(o)

/** What a launched order is being made with (read only). lemo: the Lemo catalog, for names. */
function Made({ order: o, lemo }: { order: WorkOrder; lemo?: CatalogStyle[] }) {
  const { styles } = useStyles()
  const rows: [string, string | null][] = [
    ['Route', ROUTES.find((r) => r.id === o.method)?.label ?? null],
    ['Style', o.method === 'new_style' && !o.style ? 'nouveau style, en construction'
      : lemo?.find((s) => s.id === o.style)?.label ?? styleLabel(styles, o.style)],
    ['Consigne', o.instruction],
    ["Idée de l'IA", o.idea_hook],
  ]
  return (
    <div className="space-y-1">
      {o.waits_for_style && (
        <p role="status" className="text-warn">
          Aucun style actuel ne sait faire cette vidéo : l'IA a demandé le style « {o.waits_for_style} ».
          Elle la fera dès que ce style sera construit.
        </p>
      )}
      <dl className="space-y-1">
        {rows.filter(([, v]) => v).map(([k, v]) => (
          <div key={k}><dt className="inline font-medium">{k} : </dt><dd className="inline">{v}</dd></div>
        ))}
      </dl>
      <Link to="/planning" className={`inline-flex min-h-11 items-center ${link}`}>Voir le Planning</Link>
    </div>
  )
}

/** One DM'd Reel: watch it, pick the route, the style and the instruction, then « Confirmer »
 * (to the Planning page, where nothing starts before « Lancer ») or « Écarter ». Once
 * launched: what it is being made with; failed: why, then « Relancer » or « Retirer ». */
function ReceivedCard({ order: o, lemo, onChanged }: { order: WorkOrder; lemo?: CatalogStyle[]; onChanged: () => void }) {
  const confirmed = o.status === 'confirmed'
  const failed = o.status === 'skipped'
  const launched = o.status === 'scheduled' || o.status === 'in_production'
  const [method, setMethod] = useState<OrderMethod>(o.method ?? 'style')
  const [style, setStyle] = useState<string | null>(o.style === REA_FILM ? null : o.style) // its Auto
  const [text, setText] = useState(o.instruction ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const toast = useToast()
  const embed = embedSrc(o.embed_url)
  const href = safeUrl(o.permalink)
  const who = `@${o.sender_username ?? '?'}`

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await confirmWorkOrder(o.id, { method, style: method === 'new_style' ? null : style, instruction: text.trim() || undefined })
      toast({ message: confirmed ? 'Choix mis à jour.' : 'Envoyé au Planning : lance-le quand tu veux.' })
      onChanged()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  async function discard() {
    if (!window.confirm(failed ? `Retirer ce Reel de ${who} de la page ?` : `Écarter ce Reel de ${who} ? L'IA ne le fera pas.`)) return
    try {
      await cancelWorkOrder(o.id)
    } catch (err) {
      toast({ message: `Pas écarté : ${errorMessage(err)}` })
    }
    onChanged()
  }

  return (
    <Card as="li" aria-label={`Reel reçu ${o.id}`} className="space-y-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <Chip tone={chip(o)[1]}>{chip(o)[0]}</Chip>
        {o.own_reel && <Chip tone="accent">Ton Reel</Chip>}
        <span className="text-muted">{who}, {ago(o.received_at ?? o.created_at)}</span>
        {href && <a href={href} target="_blank" rel="noopener noreferrer" className={`ml-auto ${link}`}>Instagram</a>}
      </div>
      {embed && <Embed src={embed} title={`Reel envoyé par ${who}`} />}
      {failed && o.skip_reason && <p role="status" className="text-danger">{o.skip_reason}</p>}
      {launched ? <Made order={o} lemo={lemo} /> : (
        <form aria-label="Comment le faire" onSubmit={(e) => void submit(e)} className="space-y-3">
          <div>
            <p className="font-medium">Comment le faire ?</p>
            <div role="group" aria-label="Route" className="mt-1 flex flex-wrap gap-2">
              {ROUTES.map((r) => <Chip key={r.id} pressed={method === r.id} onClick={() => setMethod(r.id)}>{r.label}</Chip>)}
            </div>
            <p className="mt-1 text-xs text-muted">{ROUTES.find((r) => r.id === method)?.hint}</p>
          </div>
          {/* all: the whole catalog, Lemo-Opuscar films too (the film gets the Reel) */}
          {method !== 'new_style' && <StylePicker value={style} onChange={setStyle} all />}
          <label className="block font-medium">Ta consigne <span className="font-normal text-muted">(facultatif)</span>
            <textarea value={text} maxLength={500} rows={3} onChange={(e) => setText(e.target.value)}
              placeholder="Ex. : garde la chute, change le sujet pour les macros du petit-déj…"
              className={`${field} mt-1 block w-full py-2 text-base`} />
          </label>
          {error && <p role="alert" className="text-danger">{error}</p>}
          <div className="flex flex-wrap items-center gap-2">
            <Button type="submit" variant="primary" loading={busy}>
              {confirmed ? 'Mettre à jour' : failed ? 'Relancer → Planning' : 'Confirmer → Planning'}
            </Button>
            <Button variant="ghost" onClick={() => void discard()}>{failed ? 'Retirer' : 'Écarter'}</Button>
            {confirmed && <Link to="/planning" className={`ml-auto inline-flex min-h-11 items-center ${link}`}>Le lancer depuis le Planning</Link>}
          </div>
        </form>
      )}
    </Card>
  )
}

/** Reçus (owner 2026-11-25): the Reels the brand account received by DM, with their note.
 * Nothing starts from a DM alone: the owner picks how to make each one and confirms it to
 * the Planning page, then launches it there (or not). A card stays, in the order the Reels
 * came, until its video is in the Inbox (owner 2026-11-26). */
export default function Received() {
  const [orders, setOrders] = useState<WorkOrder[]>()
  const [error, setError] = useState<string | null>(null)
  const [lemo, setLemo] = useState<CatalogStyle[]>()
  useEffect(() => { listStyleCatalog({ family: 'lemo' }).then(setLemo, () => setLemo([])) }, []) // failed: the id stays
  // by status: the newest 100 DM orders could leave an old waiting Reel out
  const reload = useCallback(() => Promise.all(SHOWN.map((s) => listWorkOrders('dm', s)))
    .then((lists) => {
      // a failed one only if it was confirmed here (method) and not taken off (« Retirer »)
      setOrders(lists.flat().filter((o) => o.status !== 'skipped' || (o.method && o.skip_reason !== CANCELLED))
        .sort((a, b) => a.id - b.id)) // the order they came: a card never jumps
      setError(null)
    }, (e: unknown) => setError(errorMessage(e))), [])
  useEffect(() => { void reload() }, [reload])

  return (
    <>
      <PageHeader title="Reçus">Les Reels reçus en DM. Choisis comment les faire, confirme-les vers le Planning, puis lance-les quand tu veux. Chacun reste ici jusqu'à ce que sa vidéo soit dans l'Inbox.</PageHeader>
      {error && <p role="alert" className="text-sm text-danger">{error}</p>}
      {orders === undefined ? (
        !error && <Skeleton className="h-64" />
      ) : orders.length === 0 ? (
        <EmptyState title="Rien à confirmer">
          Envoie un Reel en DM à @macrobody.fr depuis un compte épinglé (Réglages), avec ou sans consigne : il arrive ici.
        </EmptyState>
      ) : (
        <ul aria-label="Reels reçus" className="grid items-start gap-4 md:grid-cols-2 xl:grid-cols-3">
          {orders.map((o) => <ReceivedCard key={o.id} order={o} lemo={lemo} onChanged={() => void reload()} />)}
        </ul>
      )}
    </>
  )
}
