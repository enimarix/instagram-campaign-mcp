import { useCallback, useEffect, useId, useState, type FormEvent } from 'react'
import {
  addInboxClip, errorMessage, listClips, listInbox, type AudioRights, type Clip, type InboxFile,
  type RightsBasis,
} from '../api/client'
import { Button } from '../ui/Button'
import { Card, Skeleton } from '../ui/Card'
import { field as fieldClass } from '../ui/styles'

// GOAL.md §5.1; `unknown` is never offered: a clip without rights is never stored.
const BASES: { id: RightsBasis; label: string }[] = [
  { id: 'own', label: 'Own: I made it' },
  { id: 'licensed', label: 'Licensed: stock or library' },
  { id: 'public_domain', label: 'Public domain or CC0' },
  { id: 'cc', label: 'Creative Commons BY or BY-SA' },
  { id: 'permission', label: 'Permission from the creator' },
  { id: 'commentary', label: "Commentary: reacting to another creator's Reel" },
]
const NEEDS_AUTHOR: RightsBasis[] = ['cc', 'permission', 'commentary']
const SOUND: { id: AudioRights; label: string }[] = [
  { id: 'covered', label: 'Yes, the sound is covered' },
  { id: 'not_covered', label: 'No (the original sound will be muted)' },
  { id: 'no_audio', label: 'The clip has no sound' },
]
const field = `${fieldClass} mt-1 block w-full`
const SHOWN = 5 // clips listed before "Show all": keeps Settings short on a phone

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
    <form aria-label={`Add ${file.name}`} onSubmit={(e) => void submit(e)}
      className="mt-3 grid gap-3 rounded-control border border-line bg-surface-2/40 p-4 text-sm">
      <p className="font-medium break-all">{file.name}</p>
      <label htmlFor={`${id}-basis`}>Rights basis
        <select id={`${id}-basis`} value={basis} onChange={(e) => setBasis(e.target.value as RightsBasis)}
          className={field}>
          {BASES.map((b) => <option key={b.id} value={b.id}>{b.label}</option>)}
        </select>
      </label>
      <label>Rights note
        <textarea name="note" required className={`${field} py-1`}
          placeholder="Where it comes from and why we may use it (licence, date, proof)" />
      </label>
      <label>Author{NEEDS_AUTHOR.includes(basis) ? ' (credited)' : ''}
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
        <legend>Is the sound covered?</legend>
        {SOUND.map((s) => (
          <label key={s.id} className="flex min-h-11 items-center gap-2">
            <input type="radio" name="sound" value={s.id} required /> {s.label}
          </label>
        ))}
      </fieldset>
      {error && <p role="alert" className="text-danger">{error}</p>}
      <Button type="submit" variant="primary" loading={busy} className="md:w-auto md:justify-self-start">
        Add clip
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
    <Card as="section" aria-label="Clips">
      <h2 className="font-semibold">Clips</h2>
      {error !== undefined ? (
        <p role="alert" className="mt-2 text-sm text-danger">{errorMessage(error)}</p>
      ) : !inbox || !clips ? (
        <Skeleton className="mt-3 h-12" />
      ) : (
        <>
          <p className="mt-1 text-sm text-muted">
            Drop videos into the inbox folder; each one needs its rights before the studio can use it.
          </p>
          {inbox.length === 0 && <p className="mt-2 text-sm">No files waiting.</p>}
          {inbox.map((f) => <IntakeForm key={f.name} file={f} onAdded={reload} />)}
          <ul className="mt-3 divide-y divide-line/60 text-sm">
            {(all ? clips : clips.slice(0, SHOWN)).map((c) => (
              <li key={c.id} className="py-2 break-words">
                <span className="font-medium">#{c.id} {c.stats.original_name ?? c.provider}</span>
                {' · '}{BASES.find((b) => b.id === c.rights_basis)?.label ?? c.rights_basis}
                {' · '}{c.attribution ?? 'no credit needed'}
              </li>
            ))}
          </ul>
          {!all && clips.length > SHOWN && (
            <Button className="mt-2 md:w-auto" onClick={() => setAll(true)}>Show all {clips.length} clips</Button>
          )}
        </>
      )}
    </Card>
  )
}
