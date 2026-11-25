import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { cancelWorkOrder, confirmWorkOrder, errorMessage, listWorkOrders, type OrderMethod, type WorkOrder } from '../api/client'
import { safeUrl } from '../inbox/ui'
import { StylePicker } from '../launch/StylePicker'
import { ago, embedSrc } from '../trending/format'
import { Embed } from '../trending/shared'
import { Button } from '../ui/Button'
import { Card, EmptyState, Skeleton } from '../ui/Card'
import { Chip } from '../ui/Chip'
import { PageHeader } from '../ui/PageHeader'
import { field, link } from '../ui/styles'
import { useToast } from '../ui/useToast'

const ROUTES: { id: OrderMethod; label: string; hint: string }[] = [
  { id: 'style', label: 'Même vidéo, style existant', hint: "L'IA refait la même vidéo (idée, rythme, fin) dans le style choisi, sans rien reprendre du Reel." },
  { id: 'new_style', label: 'Nouveau style', hint: "L'IA décrit le style de ce Reel, il est construit pour cette vidéo, puis elle la fait dedans." },
  { id: 'rea', label: 'rea-video', hint: "Le Reel est décomposé plan par plan (rea-video : durée, cadrage, textes, son), puis refait dans le style choisi." },
]

/** One DM'd Reel: watch it, pick the route, the style and the instruction, then « Confirmer »
 * (to the Planning page, where nothing starts before « Lancer ») or « Écarter ». */
function ReceivedCard({ order: o, onChanged }: { order: WorkOrder; onChanged: () => void }) {
  const confirmed = o.status === 'confirmed'
  const [method, setMethod] = useState<OrderMethod>(o.method ?? 'style')
  const [style, setStyle] = useState<string | null>(o.style)
  const [text, setText] = useState(o.instruction ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const toast = useToast()
  const embed = embedSrc(o.embed_url)
  const href = safeUrl(o.permalink)

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
    if (!window.confirm(`Écarter ce Reel de @${o.sender_username ?? '?'} ? L'IA ne le fera pas.`)) return
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
        <Chip tone={confirmed ? 'info' : 'warn'}>{confirmed ? 'Dans le Planning' : 'À confirmer'}</Chip>
        {o.own_reel && <Chip tone="accent">Ton Reel</Chip>}
        <span className="text-muted">@{o.sender_username ?? '?'}, {ago(o.received_at ?? o.created_at)}</span>
        {href && <a href={href} target="_blank" rel="noopener noreferrer" className={`ml-auto ${link}`}>Instagram</a>}
      </div>
      {embed && <Embed src={embed} title={`Reel envoyé par @${o.sender_username ?? '?'}`} />}
      <form aria-label="Comment le faire" onSubmit={(e) => void submit(e)} className="space-y-3">
        <div>
          <p className="font-medium">Comment le faire ?</p>
          <div role="group" aria-label="Route" className="mt-1 flex flex-wrap gap-2">
            {ROUTES.map((r) => <Chip key={r.id} pressed={method === r.id} onClick={() => setMethod(r.id)}>{r.label}</Chip>)}
          </div>
          <p className="mt-1 text-xs text-muted">{ROUTES.find((r) => r.id === method)?.hint}</p>
        </div>
        {/* our styles only: a Lemo film cannot watch the Reel (the server refuses it) */}
        {method !== 'new_style' && <StylePicker value={style} onChange={setStyle} />}
        <label className="block font-medium">Ta consigne <span className="font-normal text-muted">(facultatif)</span>
          <textarea value={text} maxLength={500} rows={3} onChange={(e) => setText(e.target.value)}
            placeholder="Ex. : garde la chute, change le sujet pour les macros du petit-déj…"
            className={`${field} mt-1 block w-full py-2 text-base`} />
        </label>
        {error && <p role="alert" className="text-danger">{error}</p>}
        <div className="flex flex-wrap items-center gap-2">
          <Button type="submit" variant="primary" loading={busy}>{confirmed ? 'Mettre à jour' : 'Confirmer → Planning'}</Button>
          <Button variant="ghost" onClick={() => void discard()}>Écarter</Button>
          {confirmed && <Link to="/planning" className={`ml-auto inline-flex min-h-11 items-center ${link}`}>Le lancer depuis le Planning</Link>}
        </div>
      </form>
    </Card>
  )
}

/** Reçus (owner 2026-11-25): the Reels the brand account received by DM, with their note.
 * Nothing starts from a DM alone: the owner picks how to make each one and confirms it to
 * the Planning page, then launches it there (or not). */
export default function Received() {
  const [orders, setOrders] = useState<WorkOrder[]>()
  const [error, setError] = useState<string | null>(null)
  // by status: the newest 100 DM orders could leave an old waiting Reel out
  const reload = useCallback(() => Promise.all([listWorkOrders('dm', 'received'), listWorkOrders('dm', 'confirmed')])
    .then(([received, confirmed]) => {
      setOrders([...received, ...confirmed].reverse()) // oldest first
      setError(null)
    }, (e: unknown) => setError(errorMessage(e))), [])
  useEffect(() => { void reload() }, [reload])
  const waiting = orders?.filter((o) => o.status === 'received') ?? []
  const planned = orders?.filter((o) => o.status === 'confirmed') ?? []

  return (
    <>
      <PageHeader title="Reçus">Les Reels reçus en DM. Choisis comment les faire, confirme-les vers le Planning, puis lance-les quand tu veux.</PageHeader>
      {error && <p role="alert" className="text-sm text-danger">{error}</p>}
      {orders === undefined ? (
        !error && <Skeleton className="h-64" />
      ) : orders.length === 0 ? (
        <EmptyState title="Rien à confirmer">
          Envoie un Reel en DM à @macrobody.fr depuis un compte épinglé (Réglages), avec ou sans consigne : il arrive ici.
        </EmptyState>
      ) : (
        <div className="space-y-8">
          {waiting.length > 0 && (
            <ul aria-label="À confirmer" className="grid items-start gap-4 md:grid-cols-2 xl:grid-cols-3">
              {waiting.map((o) => <ReceivedCard key={o.id} order={o} onChanged={() => void reload()} />)}
            </ul>
          )}
          {planned.length > 0 && (
            <section>
              <h2 className="mb-3 font-semibold">Confirmés, en attente de ton « Lancer »</h2>
              <ul aria-label="Confirmés" className="grid items-start gap-4 md:grid-cols-2 xl:grid-cols-3">
                {planned.map((o) => <ReceivedCard key={o.id} order={o} onChanged={() => void reload()} />)}
              </ul>
            </section>
          )}
        </div>
      )}
    </>
  )
}
