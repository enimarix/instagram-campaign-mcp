import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { ApiError, editWorkOrder, errorMessage, listStyleCatalog, listWorkOrders, type CatalogStyle, type WorkMode, type WorkOrder } from '../api/client'
import { safeUrl } from '../inbox/ui'
import { StylePicker } from '../launch/StylePicker'
import { styleLabel, useStyles } from '../launch/useStyles'
import { DmPicksList } from '../pages/DmPicks'
import { Button } from '../ui/Button'
import { Card, EmptyState, Skeleton } from '../ui/Card'
import { Chip } from '../ui/Chip'
import { field, link } from '../ui/styles'
import { useToast } from '../ui/useToast'
import { ago, embedSrc, modeLabel, MODES, orderStatus } from './format'
import { Embed, ModePicker } from './shared'

/** The owner's instruction for a DM'd Reel: written here when the DM had none, or changed
 * while the order is still scheduled (136: 409 once the AI started), with its style (138). */
function InstructionForm({ order, onSaved, onCancel }: { order: WorkOrder; onSaved: () => void; onCancel?: () => void }) {
  const [mode, setMode] = useState<WorkMode>(order.mode)
  const [style, setStyle] = useState<string | null>(order.style)
  const [text, setText] = useState(order.instruction ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const toast = useToast()

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await editWorkOrder(order.id, { instruction: text.trim(), mode, style })
      onSaved()
    } catch (err) {
      setBusy(false)
      if (err instanceof ApiError && err.status === 409) {
        toast({ message: "Trop tard : l'IA a déjà commencé ce Reel, la consigne n'a pas changé." })
        onSaved() // reload: the card shows where it is now
      } else setError(errorMessage(err))
    }
  }

  return (
    <form aria-label="Consigne" onSubmit={(e) => void submit(e)} className="space-y-2">
      <label className="block font-medium">Que doit faire l'IA ?
        <textarea required value={text} maxLength={500} rows={4} onChange={(e) => setText(e.target.value)}
          placeholder="Ex. : ça a bien marché, analyse-la. Change ça, garde ça… (tu peux dicter)"
          className={`${field} mt-1 block w-full py-2 text-base`} />
      </label>
      {order.source === 'dm' && <ModePicker modes={MODES} value={mode} onChange={setMode} />}
      <StylePicker value={style} onChange={setStyle} />
      {error && <p role="alert" className="text-danger">{error}</p>}
      <div className="flex gap-2">
        <Button type="submit" variant="primary" loading={busy}>Envoyer</Button>
        {onCancel && <Button variant="ghost" onClick={onCancel}>Annuler</Button>}
      </div>
    </form>
  )
}

/** Where the order came from, in one line. */
function origin(o: WorkOrder) {
  if (o.source === 'create') return `créé dans l'app, ${ago(o.created_at)}`
  if (o.source === 'change') return `autre style de la vidéo ${o.from_asset_id}, ${ago(o.created_at)}`
  return `envoyé par @${o.sender_username ?? '?'}, ${ago(o.received_at ?? o.created_at)}`
}

function OrderCard({ order: o, styleName, onChanged }: { order: WorkOrder; styleName: string; onChanged: () => void }) {
  const [editing, setEditing] = useState(false)
  const [label, tone] = orderStatus(o)
  const href = safeUrl(o.permalink)
  const sender = `@${o.sender_username ?? '?'}`
  const embed = embedSrc(o.embed_url)
  const showForm = o.status === 'needs_instruction' || (editing && o.status === 'scheduled')
  return (
    <Card as="li" aria-label={`Envoi ${o.id}`} className="space-y-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <Chip tone={tone}>{label}</Chip>
        {o.own_reel && <Chip tone="accent">Ton Reel</Chip>}
        <Chip>{styleName}</Chip>
        <span className="text-muted">{origin(o)}</span>
      </div>
      {o.blocked_reason && label === 'Bloqué' && <p className="text-danger">Bloqué : {o.blocked_reason}</p>}
      {o.status === 'skipped' && o.skip_reason && <p className="text-muted">Ignoré : {o.skip_reason}</p>}
      {o.analysis && <p className="rounded-control bg-surface-2 p-3 break-words">Analyse de l'IA : {o.analysis}</p>}
      {showForm ? (
        <InstructionForm order={o} onSaved={() => { setEditing(false); onChanged() }}
          onCancel={o.status === 'scheduled' ? () => setEditing(false) : undefined} />
      ) : (
        o.instruction && (
          <div className="rounded-control bg-surface-2 p-3">
            <p className="text-xs text-muted">Ta consigne{o.source === 'dm' && o.mode && ` · ${modeLabel(o.mode)}`}</p>
            <q className="block break-words">{o.instruction}</q>
          </div>
        )
      )}
      {embed && (
        // closed: the iframe loads only when opened (the owner sent the Reel, he knows it)
        <details>
          <summary className="cursor-pointer py-3 font-medium">Voir le Reel</summary>
          <Embed src={embed} title={`Reel envoyé par ${sender}`} />
        </details>
      )}
      <div className="flex flex-wrap items-center gap-2">
        {o.status === 'scheduled' && !editing && <Button size="sm" onClick={() => setEditing(true)}>Modifier la consigne</Button>}
        {o.source === 'change' && o.from_asset_id != null && (
          <Link to={`/assets/${o.from_asset_id}`} className={`inline-flex min-h-11 items-center ${link}`}>Vidéo d'origine</Link>
        )}
        {o.status === 'in_feed' && o.asset_id != null && (
          <Link to={`/assets/${o.asset_id}`} className={`inline-flex min-h-11 items-center ${link}`}>Voir dans ton feed</Link>
        )}
        {href && (
          <a href={href} target="_blank" rel="noopener noreferrer" className={`ml-auto inline-flex min-h-11 items-center ${link}`}>
            Instagram
          </a>
        )}
      </div>
    </Card>
  )
}

/** Mes envois: what the owner sent the AI himself, newest first: the Reels he DMs to the
 * brand account, the videos he asked for (« Créer une vidéo ») and the restyles (« même
 * vidéo, autre style »), with their instruction, style and where the work stands. */
export default function MesEnvois() {
  const [orders, setOrders] = useState<WorkOrder[]>()
  const [error, setError] = useState<string | null>(null)
  const { styles } = useStyles()
  const [lemo, setLemo] = useState<CatalogStyle[]>() // Lemo names, fetched only when an order has one
  const wantsLemo = !!orders?.some((o) => o.style?.startsWith('lemo:'))

  const reload = useCallback(() => listWorkOrders('mine').then((o) => {
    setOrders(o)
    setError(null)
  }, (e: unknown) => setError(errorMessage(e))), [])
  useEffect(() => { void reload() }, [reload])
  useEffect(() => {
    if (!wantsLemo || lemo) return
    let live = true
    listStyleCatalog({ family: 'lemo' }).then((s) => live && setLemo(s), () => live && setLemo([])) // failed: the id stays
    return () => { live = false }
  }, [wantsLemo, lemo])
  const styleName = (id: string | null) => lemo?.find((s) => s.id === id)?.label ?? styleLabel(styles, id)

  return (
    <>
      {error && <p role="alert" className="text-sm text-danger">{error}</p>}
      {orders === undefined ? (
        !error && <Skeleton className="h-64" />
      ) : orders.length === 0 ? (
        <EmptyState title="Aucun envoi pour l'instant">
          Envoie un Reel en DM à @macrobody.fr depuis ton compte, avec ou sans description.
          Une description dans le DM vaut consigne : le travail commence tout de suite.
          Ou touche « Créer une vidéo » pour un sujet à toi.
        </EmptyState>
      ) : (
        <ul aria-label="Mes envois" className="grid items-start gap-4 md:grid-cols-2 xl:grid-cols-3">
          {orders.map((o) => <OrderCard key={o.id} order={o} styleName={styleName(o.style)} onChanged={() => void reload()} />)}
        </ul>
      )}
      <details className="mt-8 rounded-card border border-line/60 bg-surface p-4 shadow-card">
        <summary className="cursor-pointer font-medium">Historique des picks DM</summary>
        <DmPicksList />
      </details>
    </>
  )
}
