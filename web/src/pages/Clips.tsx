import { useCallback, useEffect, useId, useState, type FormEvent } from 'react'
import {
  addInboxClip, errorMessage, listClips, listInbox, type AudioRights, type Clip, type InboxFile,
  type RightsBasis,
} from '../api/client'
import { Button } from '../ui/Button'
import { Card, Skeleton } from '../ui/Card'
import { field as fieldClass } from '../ui/styles'
import { AskPermissionButton } from './Permissions'
import StockClips from './StockClips'

// GOAL.md §5.1; `unknown` is never offered: a clip without rights is never stored.
const BASES: { id: RightsBasis; label: string }[] = [
  { id: 'own', label: 'À moi : je l’ai fait' },
  { id: 'licensed', label: 'Sous licence : banque d’images ou bibliothèque' },
  { id: 'public_domain', label: 'Domaine public ou CC0' },
  { id: 'cc', label: 'Creative Commons BY ou BY-SA' },
  { id: 'permission', label: 'Autorisation du créateur' },
  { id: 'commentary', label: 'Commentaire : réaction au Reel d’un autre créateur' },
]
const NEEDS_AUTHOR: RightsBasis[] = ['cc', 'permission', 'commentary']
const SOUND: { id: AudioRights; label: string }[] = [
  { id: 'covered', label: 'Oui, le son est couvert' },
  { id: 'not_covered', label: 'Non (le son d’origine sera coupé)' },
  { id: 'no_audio', label: 'Le clip n’a pas de son' },
]
const field = `${fieldClass} mt-1 block w-full`
const SHOWN = 5 // clips listed before "Voir les n clips": keeps Settings short on a phone

/** The Add-clip form of one inbox file: rights basis, note, author, URL, licence, sound. */
function IntakeForm({ file, onAdded }: { file: InboxFile; onAdded: () => void }) {
  const id = useId()
  const [basis, setBasis] = useState<RightsBasis>('own')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const f = new FormData(e.currentTarget)
    const text = (k: string) => String(f.get(k) ?? '').trim() || null
    setBusy(true)
    setError(null)
    try {
      await addInboxClip(file.name, {
        rights_basis: basis,
        rights_note: text('note') ?? '',
        audio_rights: f.get('sound') as AudioRights,
        author: text('author'),
        url: text('url'),
        licence: basis === 'cc' ? text('licence') : null,
      })
      onAdded()
    } catch (err) {
      setError(errorMessage(err))
      setBusy(false)
    }
  }

  return (
    <form aria-label={`Ajouter ${file.name}`} onSubmit={(e) => void submit(e)}
      className="mt-3 grid gap-3 rounded-control border border-line bg-surface-2/40 p-4 text-sm">
      <p className="font-medium break-all">{file.name}</p>
      <label htmlFor={`${id}-basis`}>Base des droits
        <select id={`${id}-basis`} value={basis} onChange={(e) => setBasis(e.target.value as RightsBasis)}
          className={field}>
          {BASES.map((b) => <option key={b.id} value={b.id}>{b.label}</option>)}
        </select>
      </label>
      <label>Note sur les droits
        <textarea name="note" required className={`${field} py-1`}
          placeholder="D’où il vient et pourquoi on peut l’utiliser (licence, date, preuve)" />
      </label>
      <label>Auteur{NEEDS_AUTHOR.includes(basis) ? ' (crédité)' : ''}
        <input name="author" required={NEEDS_AUTHOR.includes(basis)} className={field} />
      </label>
      <label>URL
        <input name="url" type="url" className={field} />
      </label>
      {basis === 'cc' && (
        <label>Licence
          <input name="licence" required placeholder="CC BY 4.0" className={field} />
        </label>
      )}
      <fieldset>
        <legend>Le son est-il couvert ?</legend>
        {SOUND.map((s) => (
          <label key={s.id} className="flex min-h-11 items-center gap-2">
            <input type="radio" name="sound" value={s.id} required /> {s.label}
          </label>
        ))}
      </fieldset>
      {error && <p role="alert" className="text-danger">{error}</p>}
      <Button type="submit" variant="primary" loading={busy} className="md:w-auto md:justify-self-start">
        Ajouter le clip
      </Button>
    </form>
  )
}

/** Settings section: inbox files waiting for their rights, then the clips with their credit. */
export default function ClipsSection() {
  const [inbox, setInbox] = useState<InboxFile[]>()
  const [clips, setClips] = useState<Clip[]>()
  const [error, setError] = useState<unknown>()
  const [all, setAll] = useState(false)
  const reload = useCallback(() => {
    Promise.all([listInbox(), listClips()]).then(([i, c]) => {
      setInbox(i)
      setClips(c)
    }, setError)
  }, [])
  useEffect(reload, [reload])

  return (
    <Card as="section" id="clips" aria-label="Clips" className="scroll-mt-16 lg:scroll-mt-4">
      <h2 className="font-semibold">Clips</h2>
      {error !== undefined ? (
        <p role="alert" className="mt-2 text-sm text-danger">{errorMessage(error)}</p>
      ) : !inbox || !clips ? (
        <Skeleton className="mt-3 h-12" />
      ) : (
        <>
          <p className="mt-1 text-sm text-muted">
            Dépose des vidéos dans le dossier inbox ; chacune a besoin de ses droits avant que le studio puisse s’en servir.
          </p>
          {inbox.length === 0 && <p className="mt-2 text-sm">Aucun fichier en attente.</p>}
          {inbox.map((f) => <IntakeForm key={f.name} file={f} onAdded={reload} />)}
          <ul className="mt-3 divide-y divide-line/60 text-sm">
            {(all ? clips : clips.slice(0, SHOWN)).map((c) => (
              <li key={c.id} className="py-2 break-words">
                <span className="font-medium">#{c.id} {c.stats.original_name ?? c.provider}</span>
                {' · '}{BASES.find((b) => b.id === c.rights_basis)?.label ?? c.rights_basis}
                {' · '}{c.attribution ?? 'pas de crédit nécessaire'}
                {c.rights_basis === 'commentary' && <> <AskPermissionButton target={{ source_id: c.id }} /></>}
              </li>
            ))}
          </ul>
          {!all && clips.length > SHOWN && (
            <Button className="mt-2 md:w-auto" onClick={() => setAll(true)}>Voir les {clips.length} clips</Button>
          )}
          <StockClips onAdded={reload} />
        </>
      )}
    </Card>
  )
}
