import { useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { ApiError, cancelWorkOrder, editWorkOrder, errorMessage, type CatalogStyle, type WorkOrder } from '../api/client'
import { ago } from '../trending/format'
import { Button } from '../ui/Button'
import { Card, EmptyState } from '../ui/Card'
import { Chip } from '../ui/Chip'
import { field, link } from '../ui/styles'
import { useToast } from '../ui/useToast'
import { INSTRUCTION_MAX, stage, styleName } from './prompt'

/** A follow-up note on a waiting order: added to its instruction (409 once the AI started). */
function NoteForm({ order, onDone }: { order: WorkOrder; onDone: (saved: boolean) => void }) {
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const toast = useToast()
  const text = order.instruction ? `${order.instruction}\nNote : ${note.trim()}` : note.trim()

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await editWorkOrder(order.id, { instruction: text })
      onDone(true)
    } catch (err) {
      setBusy(false)
      if (err instanceof ApiError && err.status === 409) {
        toast({ message: "Trop tard : l'IA a déjà commencé, la note n'a pas été ajoutée." })
        onDone(true) // reload: the card shows where it is now
      } else setError(errorMessage(err))
    }
  }

  return (
    <form aria-label="Note" onSubmit={(e) => void submit(e)} className="space-y-2">
      <label className="block font-medium">Ta note pour l'IA
        <textarea required value={note} rows={3} onChange={(e) => setNote(e.target.value)}
          placeholder="Ex. : garde un ton léger, cite une source"
          className={`${field} mt-1 block w-full py-2 text-base`} />
      </label>
      {text.length > INSTRUCTION_MAX && <p className="text-danger">Trop long : {text.length}/{INSTRUCTION_MAX} avec la demande.</p>}
      {error && <p role="alert" className="text-danger">{error}</p>}
      <div className="flex gap-2">
        <Button type="submit" variant="primary" loading={busy} disabled={!note.trim() || text.length > INSTRUCTION_MAX}>Ajouter</Button>
        <Button variant="ghost" onClick={() => onDone(false)}>Annuler</Button>
      </div>
    </form>
  )
}

function OrderCard({ order: o, catalog, onChanged }: { order: WorkOrder; catalog?: CatalogStyle[]; onChanged: () => void }) {
  const [noting, setNoting] = useState(false)
  const toast = useToast()
  const [label, tone] = stage(o)
  const waiting = o.status === 'scheduled'
  // the AI's own words: the idea it wrote (a Lemo film's starts as the instruction), why it waits or skipped
  const hook = o.idea_hook && !o.instruction?.startsWith(o.idea_hook) ? o.idea_hook : null

  async function cancel() {
    if (!window.confirm(`Annuler la vidéo ${o.id} ? Elle sort de la pile.`)) return
    try {
      await cancelWorkOrder(o.id)
    } catch (e) {
      toast({ message: `Pas annulée : ${errorMessage(e)}` })
    }
    onChanged()
  }

  return (
    <Card as="li" aria-label={`Commande ${o.id}`} className="space-y-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <Chip tone={tone}>{label}</Chip>
        <Chip>{styleName(catalog, o.style)}</Chip>
        <span className="text-muted" title="Dernier changement d'étape">{ago(o.updated_at)}</span>
      </div>
      {o.instruction && <q className="block whitespace-pre-line wrap-anywhere">{o.instruction}</q>}
      {hook && <p className="rounded-control bg-surface-2 p-3 wrap-anywhere">L'IA : {hook}</p>}
      {waiting && o.blocked_reason && <p className="text-warn">En attente : {o.blocked_reason}</p>}
      {o.status === 'skipped' && o.skip_reason && <p className="text-danger">{o.skip_reason}</p>}
      {noting ? <NoteForm order={o} onDone={(saved) => { setNoting(false); if (saved) onChanged() }} /> : (
        <div className="flex flex-wrap items-center gap-2">
          {waiting && <Button size="sm" onClick={() => setNoting(true)}>Ajouter une note</Button>}
          {waiting && <Button size="sm" variant="ghost" onClick={() => void cancel()}>Annuler</Button>}
          {o.status === 'in_feed' && o.asset_id != null && (
            <Link to={`/assets/${o.asset_id}`} className={`inline-flex min-h-11 items-center ${link}`}>Voir dans l'Inbox</Link>
          )}
          {o.from_asset_id != null && (
            <Link to={`/assets/${o.from_asset_id}`} className={`inline-flex min-h-11 items-center ${link}`}>Vidéo d'origine</Link>
          )}
        </div>
      )}
    </Card>
  )
}

/** La pile: the owner's orders, newest first, with their stage. */
export function Pile({ orders, catalog, onChanged }: { orders: WorkOrder[]; catalog?: CatalogStyle[]; onChanged: () => void }) {
  if (!orders.length) return <EmptyState title="La pile est vide">Écris une idée au-dessus et envoie-la.</EmptyState>
  return (
    <ul aria-label="La pile" className="grid items-start gap-4 md:grid-cols-2 xl:grid-cols-3">
      {orders.map((o) => <OrderCard key={o.id} order={o} catalog={catalog} onChanged={onChanged} />)}
    </ul>
  )
}
