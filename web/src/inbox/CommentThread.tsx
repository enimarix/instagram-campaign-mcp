import { useEffect, useState, type FormEvent } from 'react'
import {
  addFeedback,
  deleteFeedback,
  editFeedback,
  errorMessage,
  listFeedback,
  type Asset,
  type Comment,
  type Vocabulary,
} from '../api/client'
import { button } from './ui'

type Props = {
  assetId: number
  currentTime: () => number // the player's, for "pin to this moment"
  onSeek: (t: number) => void
  reasons: Vocabulary['values']
  onAsset: (a: Asset) => void
}

const clock = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`

// The owner's comments on one asset, oldest first, plus the form to add one.
export default function CommentThread({ assetId, currentTime, onSeek, reasons, onAsset }: Props) {
  const [comments, setComments] = useState<Comment[]>([])
  const [text, setText] = useState('')
  const [picked, setPicked] = useState<string[]>([])
  const [pin, setPin] = useState<number | null>(null)
  const [wantsChanges, setWantsChanges] = useState(false)
  const [note, setNote] = useState<string | null>(null)
  const [editing, setEditing] = useState<{ id: number; text: string } | null>(null)

  useEffect(() => {
    listFeedback(assetId).then(setComments, (e: unknown) =>
      setNote(`Could not load comments (${errorMessage(e)})`))
  }, [assetId])

  const label = (code: string) => reasons.find((r) => r.id === code)?.label ?? code
  const toggle = (id: string) =>
    setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]))

  async function add(e: FormEvent) {
    e.preventDefault()
    setNote(null)
    try {
      const r = await addFeedback(assetId, {
        ...(text.trim() && { text }),
        reason_codes: picked,
        ...(pin != null && { video_time_s: pin }),
        wants_changes: wantsChanges,
      })
      setComments((c) => [...c, r.feedback])
      onAsset(r.asset)
      setNote(r.moved ? 'Sent back for a new version.'
        : wantsChanges ? `Saved, but not sent back: ${r.reason}` : 'Saved.')
      setText('')
      setPicked([])
      setPin(null)
      setWantsChanges(false)
    } catch (err) {
      setNote(`Not saved: ${errorMessage(err)}`)
    }
  }

  async function saveEdit() {
    if (!editing) return
    try {
      const r = await editFeedback(editing.id, { text: editing.text })
      setComments((c) => c.map((x) => (x.id === r.feedback.id ? r.feedback : x)))
      setEditing(null)
    } catch (err) {
      setNote(`Not saved: ${errorMessage(err)}`)
    }
  }

  async function remove(id: number) {
    if (!window.confirm('Delete this comment?')) return
    try {
      await deleteFeedback(id)
      setComments((c) => c.filter((x) => x.id !== id))
    } catch (err) {
      setNote(`Not deleted: ${errorMessage(err)}`)
    }
  }

  return (
    <section aria-label="Comments" className="space-y-3 rounded-xl bg-white p-3 shadow-sm">
      <h2 className="font-semibold">Comments</h2>
      <ul className="space-y-2">
        {comments.map((c) => (
          <li key={c.id} className="border-b border-gray-100 pb-2 text-sm">
            {c.video_time_s != null && (
              <button type="button" onClick={() => onSeek(c.video_time_s!)}
                aria-label={`Play from ${clock(c.video_time_s)}`}
                className="mr-2 rounded bg-gray-100 px-1 font-mono text-xs">
                {clock(c.video_time_s)}
              </button>
            )}
            {c.reason_codes.map(label).join(', ')}
            {c.wants_changes ? ' · asked for changes' : ''}
            {editing?.id === c.id ? (
              <div className="mt-1 flex gap-2">
                <textarea aria-label="Edit comment" value={editing.text}
                  onChange={(e) => setEditing({ id: c.id, text: e.target.value })}
                  className="flex-1 rounded border border-gray-300 p-1" />
                <button type="button" onClick={saveEdit} className={`${button} bg-blue-600 text-white`}>Save</button>
                <button type="button" onClick={() => setEditing(null)} className={`${button} bg-gray-100`}>Cancel</button>
              </div>
            ) : (
              <>
                {c.text && <p>{c.text}</p>}
                <button type="button" onClick={() => setEditing({ id: c.id, text: c.text ?? '' })}
                  className="mr-3 text-xs text-blue-700 underline">Edit</button>
                <button type="button" onClick={() => remove(c.id)}
                  className="text-xs text-red-700 underline">Delete</button>
              </>
            )}
          </li>
        ))}
      </ul>
      <form onSubmit={add} className="space-y-2">
        <textarea aria-label="New comment" value={text} onChange={(e) => setText(e.target.value)}
          rows={2} className="block w-full rounded-lg border border-gray-300 p-2 text-sm" />
        <div role="group" aria-label="Reasons" className="flex flex-wrap gap-2">
          {reasons.map((r) => (
            <button key={r.id} type="button" aria-pressed={picked.includes(r.id)} onClick={() => toggle(r.id)}
              className={`${button} border ${picked.includes(r.id) ? 'border-red-600 bg-red-50 text-red-800' : 'border-gray-300'}`}>
              {r.label}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={pin != null}
            onChange={(e) => setPin(e.target.checked ? currentTime() : null)} />
          Pin to this moment{pin != null && ` (${clock(pin)})`}
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" role="switch" checked={wantsChanges}
            onChange={(e) => setWantsChanges(e.target.checked)} />
          Ask for changes
        </label>
        <button type="submit" disabled={!text.trim() && !picked.length}
          className={`${button} bg-blue-600 text-white`}>Add comment</button>
        {note && <p role="status" className="text-sm">{note}</p>}
      </form>
    </section>
  )
}
