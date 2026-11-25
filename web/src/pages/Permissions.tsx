import { useCallback, useEffect, useState, type FormEvent } from 'react'
import {
  answerPermission, askPermission, attachPermissionFile, errorMessage, getPermissionDraft, listPermissions,
  type AudioRights, type PermissionChannel, type PermissionRequest, type PermissionTarget,
} from '../api/client'
import { safeUrl } from '../inbox/ui'
import { Button } from '../ui/Button'
import { Card, Skeleton } from '../ui/Card'
import { Chip } from '../ui/Chip'
import { Sheet } from '../ui/Sheet'
import { buttonClass, field, link, type Tone } from '../ui/styles'
import { useToast } from '../ui/useToast'
import { dateTime } from './load'

// Step 065. The studio never sends anything: the owner copies the draft and sends it.
const CHANGED = 'permissions:changed' // the list reloads when a request is saved elsewhere
const CHANNELS: { id: PermissionChannel; label: string }[] = [
  { id: 'dm', label: 'Instagram DM' },
  { id: 'email', label: 'E-mail' },
  { id: 'other', label: 'Autre' },
]
const STATUS: Record<PermissionRequest['status'], [Tone, string]> = {
  requested: ['info', 'demandée'], granted: ['success', 'accordée'], denied: ['neutral', 'refusée'],
}
const ACCEPT = '.mp4,.mov,.m4v,.webm,.mkv' // VIDEO_EXTS in src/studio/sources.py

function AskSheet({ target, onClose }: { target: PermissionTarget; onClose: () => void }) {
  const toast = useToast()
  const [message, setMessage] = useState<string>()
  const [askName, setAskName] = useState(false) // the studio does not know the creator
  const [creator, setCreator] = useState('')
  const [edited, setEdited] = useState(false)
  const [channel, setChannel] = useState<PermissionChannel>('dm')
  const [note, setNote] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const [where] = useState(target) // fixed while the sheet is open: callers pass a new literal each render
  const load = useCallback((name?: string) => getPermissionDraft(where, name).then((d) => {
    setMessage(d.message)
    return d
  }, (e: unknown) => setError(errorMessage(e))), [where])
  useEffect(() => { void load().then((d) => d && setAskName(!d.creator)) }, [load])

  async function copy() {
    try {
      await navigator.clipboard.writeText(message ?? '')
      toast({ message: 'Copié : colle-le dans ton message au créateur' })
    } catch {
      toast({ message: 'Copie impossible : sélectionne le texte et copie-le' })
    }
  }

  async function save(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await askPermission({ ...where, channel, note: note.trim() || undefined, creator: creator.trim() || undefined })
      window.dispatchEvent(new Event(CHANGED))
      toast({ message: 'Enregistrée. Quand le créateur répond, note-le dans Réglages, Autorisations.' })
      onClose()
    } catch (err) {
      setError(errorMessage(err))
      setBusy(false)
    }
  }

  return (
    <Sheet title="Demander l’autorisation" onClose={onClose}>
      <form onSubmit={(e) => void save(e)} className="mt-3 grid gap-3 text-sm">
        <p className="text-muted">Modifie le message, copie-le et envoie-le toi-même. Le studio ne l’envoie jamais.</p>
        {askName && (
          <label>Créateur
            <input value={creator} required onChange={(e) => setCreator(e.target.value)}
              onBlur={() => { if (!edited && creator.trim()) void load(creator.trim()) }}
              placeholder="son nom Instagram" className={`${field} mt-1 block w-full`} />
          </label>
        )}
        {message === undefined ? !error && <Skeleton className="h-32" /> : (
          <label>Message
            <textarea value={message} rows={8} onChange={(e) => { setMessage(e.target.value); setEdited(true) }}
              className={`${field} mt-1 block w-full py-2`} />
          </label>
        )}
        <Button onClick={() => void copy()} disabled={!message} className="md:w-auto md:justify-self-start">Copier le message</Button>
        <label>Envoyé par
          <select value={channel} onChange={(e) => setChannel(e.target.value as PermissionChannel)}
            className={`${field} mt-1 block w-full`}>
            {CHANNELS.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
          </select>
        </label>
        <label>Note (facultatif)
          <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={1000}
            placeholder="envoyé le 18 nov. depuis le compte de la marque" className={`${field} mt-1 block w-full`} />
        </label>
        {error && <p role="alert" className="text-danger">{error}</p>}
        <Button type="submit" variant="primary" loading={busy} disabled={message === undefined}>Enregistrer la demande</Button>
      </form>
    </Sheet>
  )
}

/** « Demander l’autorisation » on a reference, an inspiration or a clip: opens the draft sheet. */
export function AskPermissionButton({ target }: { target: PermissionTarget }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <Button size="sm" variant="ghost" onClick={() => setOpen(true)}>Demander l’autorisation</Button>
      {open && <AskSheet target={target} onClose={() => setOpen(false)} />}
    </>
  )
}

function Row({ r, act }: { r: PermissionRequest; act: (fn: () => Promise<unknown>) => Promise<void> }) {
  const [granting, setGranting] = useState(false)
  const [proof, setProof] = useState('')
  const [ads, setAds] = useState(false)
  const [sound, setSound] = useState<AudioRights>('not_covered')
  const [uploading, setUploading] = useState(false)
  const href = safeUrl(r.url)
  const attached = r.rights_basis === 'permission' && r.has_file

  return (
    <li className="py-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium break-all">@{r.creator}</span>
        <Chip tone={STATUS[r.status][0]}>{STATUS[r.status][1]}</Chip>
        {r.ads_allowed && <Chip tone="accent">pubs autorisées</Chip>}
        <span className="text-muted">
          {CHANNELS.find((c) => c.id === r.channel)?.label} · demandée le {dateTime(r.requested_at)}
        </span>
        {href && <a href={href} target="_blank" rel="noopener noreferrer" className={link}>Ouvrir</a>}
      </div>
      {r.proof_note && <p className="mt-1 break-words text-muted">{r.proof_note}</p>}
      {r.status === 'requested' && !granting && (
        <div className="mt-2 flex flex-wrap gap-2">
          <Button size="sm" onClick={() => setGranting(true)}>C’est oui</Button>
          <Button size="sm" variant="ghost" onClick={() => void act(() => answerPermission(r.id, { status: 'denied' }))}>
            C’est non
          </Button>
        </div>
      )}
      {granting && r.status === 'requested' && (
        <form aria-label={`Oui de @${r.creator}`} className="mt-2 grid gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            void act(() => answerPermission(r.id, { status: 'granted', proof_note: proof.trim(), ads_allowed: ads }))
          }}>
          <label>Preuve
            <input value={proof} required onChange={(e) => setProof(e.target.value)}
              placeholder="où et quand il a répondu oui" className={`${field} mt-1 block w-full`} />
          </label>
          <label className="flex min-h-11 items-center gap-2">
            <input type="checkbox" checked={ads} onChange={(e) => setAds(e.target.checked)} />
            Accord écrit pour les pubs payantes
          </label>
          <Button type="submit" variant="primary" className="md:w-auto md:justify-self-start">Enregistrer la réponse</Button>
        </form>
      )}
      {r.status === 'granted' && !attached && (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <select aria-label="Le son est-il couvert ?" value={sound} onChange={(e) => setSound(e.target.value as AudioRights)}
            className={field}>
            <option value="covered">Le son est couvert</option>
            <option value="not_covered">Le son n’est pas couvert (coupé)</option>
            <option value="no_audio">Pas de son</option>
          </select>
          <label className={`${buttonClass('primary', 'sm')} cursor-pointer has-focus-visible:outline-2 has-focus-visible:outline-accent ${uploading ? 'opacity-60' : ''}`}>
            {uploading ? 'Ajout…' : 'Joindre le fichier'}
            <input type="file" accept={ACCEPT} className="sr-only" disabled={uploading}
              onChange={(e) => {
                const file = e.target.files?.[0]
                e.target.value = ''
                if (!file) return
                setUploading(true)
                void act(() => attachPermissionFile(r.id, file, sound)).finally(() => setUploading(false))
              }} />
          </label>
        </div>
      )}
      {attached && <p className="mt-1 text-success">Fichier joint : le clip n°{r.source_id} peut servir avec crédit.</p>}
      {r.status === 'denied' && <p className="mt-1 text-muted">Le clip reste utilisable en commentaire seulement.</p>}
    </li>
  )
}

/** Settings section: permission requests, their answers, and the creator's file once granted. */
export default function PermissionsSection() {
  const [items, setItems] = useState<PermissionRequest[]>()
  const [error, setError] = useState<string | null>(null)
  const load = useCallback(() => listPermissions().then(setItems, (e: unknown) => setError(errorMessage(e))), [])
  useEffect(() => {
    void load()
    const reload = () => void load()
    window.addEventListener(CHANGED, reload)
    return () => window.removeEventListener(CHANGED, reload)
  }, [load])

  async function act(fn: () => Promise<unknown>) {
    setError(null)
    try {
      await fn()
      await load()
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  return (
    <Card as="section" id="permissions" aria-label="Autorisations" className="scroll-mt-16 lg:scroll-mt-4">
      <h2 className="font-semibold">Autorisations</h2>
      <p className="mt-1 text-sm text-muted">
        Les créateurs à qui tu as demandé de reprendre un clip tel quel. Quand ils disent oui, joins leur fichier.
      </p>
      {error && <p role="alert" className="mt-2 text-sm text-danger">{error}</p>}
      {items === undefined ? !error && <Skeleton className="mt-3 h-12" /> : items.length === 0 ? (
        <p className="mt-2 text-sm">Pas encore de demande. Utilise « Demander l’autorisation » sur un clip, une tendance ou une inspiration.</p>
      ) : (
        <ul className="mt-2 divide-y divide-line/60">
          {items.map((r) => <Row key={r.id} r={r} act={act} />)}
        </ul>
      )}
    </Card>
  )
}
