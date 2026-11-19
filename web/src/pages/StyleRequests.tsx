import { useEffect, useState } from 'react'
import { Link } from 'react-router'
import {
  decideStyleRequest, errorMessage, listStyleRequests, type StyleRequest, type StyleRequestStatus,
} from '../api/client'
import { Button } from '../ui/Button'
import { Card, Skeleton } from '../ui/Card'
import { Chip } from '../ui/Chip'
import { field, link, type Tone } from '../ui/styles'

const STATUS: Record<StyleRequestStatus, [string, Tone]> = {
  proposed: ['à décider', 'warn'], accepted: ['à construire', 'success'], declined: ['refusé', 'neutral'],
  building: ['en construction', 'info'], live: ['en ligne', 'success'],
}
const CONCEPT: [keyof StyleRequest['concept'], string][] = [
  ['look', 'Look'], ['palette', 'Palette'], ['motion', 'Mouvement'], ['typography', 'Typo'], ['sound', 'Son'],
  ['reference', 'Référence'],
]

function RequestCard({ request: r, onDecided }: { request: StyleRequest; onDecided: (r: StyleRequest) => void }) {
  const [note, setNote] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [label, tone] = STATUS[r.status]
  const open = r.status === 'proposed'

  async function decide(decision: 'accepted' | 'declined') {
    setBusy(true)
    setError(null)
    try {
      onDecided(await decideStyleRequest(r.id, { decision, ...(note.trim() && { note: note.trim() }) }))
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card as="li" className="text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold">{r.name}</span>
        <Chip tone={r.kind === 'invented' ? 'explore' : 'accent'}>{r.kind === 'invented' ? 'inventé' : "d'après une référence"}</Chip>
        <Chip tone={tone}>{label}</Chip>
      </div>
      <p className="mt-1">{r.concept.why}</p>
      <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
        {CONCEPT.filter(([k]) => r.concept[k]).map(([k, name]) => (
          <div key={k} className="contents">
            <dt className="text-muted">{name}</dt>
            <dd className="break-words">{r.concept[k]}</dd>
          </div>
        ))}
      </dl>
      <ol className="mt-2 list-decimal space-y-0.5 pl-5">
        {r.concept.scenes.map((s, i) => <li key={i}>{s}</li>)}
      </ol>
      {r.unblocks.asset_ids.length > 0 && (
        <p className="mt-2 text-muted">
          Débloque :{' '}
          {r.unblocks.asset_ids.map((id, i) => (
            <span key={id}>{i > 0 && ', '}<Link to={`/assets/${id}`} className={link}>vidéo {id}</Link></span>
          ))}
        </p>
      )}
      {r.owner_note && <p className="mt-1 text-muted">Ta note : « {r.owner_note} »</p>}
      {open && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <input aria-label={`Note pour ${r.name}`} placeholder="Une note (facultatif)" maxLength={300}
            value={note} onChange={(e) => setNote(e.target.value)} className={`${field} min-w-0 flex-1`} />
          <Button variant="primary" disabled={busy} onClick={() => void decide('accepted')}>Construire</Button>
          <Button disabled={busy} onClick={() => void decide('declined')}>Non</Button>
        </div>
      )}
      {error && <p role="alert" className="mt-2 text-danger">{error}</p>}
    </Card>
  )
}

/** The styles the AI asks for (156): the owner says « Construire » or « Non »; the
 * accepted ones are built by the developers. */
export default function StyleRequests() {
  const [requests, setRequests] = useState<StyleRequest[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    listStyleRequests().then(setRequests, (e: unknown) => setError(errorMessage(e)))
  }, [])

  const replace = (r: StyleRequest) => setRequests((rs) => rs && rs.map((x) => (x.id === r.id ? r : x)))

  return (
    <section aria-label="Style requests" className="mt-8">
      <h2 className="text-lg font-semibold">Nouveaux styles demandés</h2>
      {error ? (
        <p role="alert" className="mt-2 text-sm text-danger">{error}</p>
      ) : requests === null ? (
        <Skeleton className="mt-3 h-24" />
      ) : requests.length === 0 ? (
        <p className="mt-2 text-sm text-muted">Aucune demande pour l'instant</p>
      ) : (
        <ul className="mt-3 space-y-2">
          {requests.map((r) => <RequestCard key={r.id} request={r} onDecided={replace} />)}
        </ul>
      )}
    </section>
  )
}
