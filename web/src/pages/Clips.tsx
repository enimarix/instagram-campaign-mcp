import { useCallback, useEffect, useId, useState, type FormEvent } from 'react'
import {
  addInboxClip, errorMessage, listClips, listInbox, type AudioRights, type Clip, type InboxFile,
  type RightsBasis,
} from '../api/client'
import { button } from '../inbox/ui'

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
const field = 'mt-1 block min-h-11 w-full rounded-lg border border-gray-300 px-2 text-sm'

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
      className="mt-2 grid gap-2 rounded-lg border border-gray-200 p-3 text-sm">
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
      {error && <p role="alert" className="text-red-700">{error}</p>}
      <button type="submit" disabled={busy} className={`${button} bg-blue-600 text-white md:w-auto`}>
        Add clip
      </button>
    </form>
  )
}

/** Settings section: inbox files waiting for their rights, then the clips with their credit. */
export default function ClipsSection() {
  const [inbox, setInbox] = useState<InboxFile[]>()
  const [clips, setClips] = useState<Clip[]>()
  const [error, setError] = useState<unknown>()
  const reload = useCallback(() => {
    Promise.all([listInbox(), listClips()]).then(([i, c]) => {
      setInbox(i)
      setClips(c)
    }, setError)
  }, [])
  useEffect(reload, [reload])

  return (
    <section aria-label="Clips" className="mt-4 rounded-lg border border-gray-200 bg-white p-4">
      <h3 className="font-semibold">Clips</h3>
      {error !== undefined ? (
        <p role="alert" className="mt-2 text-sm text-red-700">{errorMessage(error)}</p>
      ) : !inbox || !clips ? (
        <p className="mt-2 text-sm text-gray-500">Loading…</p>
      ) : (
        <>
          <p className="mt-2 text-sm text-gray-500">
            Drop videos into the inbox folder; each one needs its rights before the studio can use it.
          </p>
          {inbox.length === 0 && <p className="mt-2 text-sm">No files waiting.</p>}
          {inbox.map((f) => <IntakeForm key={f.name} file={f} onAdded={reload} />)}
          <ul className="mt-3 space-y-1 text-sm">
            {clips.map((c) => (
              <li key={c.id} className="break-words">
                <span className="font-medium">#{c.id} {c.stats.original_name ?? c.provider}</span>
                {' · '}{BASES.find((b) => b.id === c.rights_basis)?.label ?? c.rights_basis}
                {' · '}{c.attribution ?? 'no credit needed'}
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  )
}
