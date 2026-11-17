import { useState } from 'react'
import type { CommentIn, Vocabulary } from '../api/client'
import { Button } from '../ui/Button'
import { Chip } from '../ui/Chip'
import { Sheet } from '../ui/Sheet'
import { field } from '../ui/styles'
import { clock } from './ui'

type Props = {
  reasons: Vocabulary['values']
  at: number // the playback time when the sheet opened, for the optional pin
  onSave: (fb: CommentIn) => void
  onClose: () => void
}

// The Change sheet: what is wrong (chips and/or text), optionally pinned to a moment.
// Saving asks for a new version (wants_changes); the agent reworks it.
export default function ReasonSheet({ reasons, at, onSave, onClose }: Props) {
  const [picked, setPicked] = useState<string[]>([])
  const [text, setText] = useState('')
  const [pin, setPin] = useState(false)

  const toggle = (id: string) =>
    setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]))

  return (
    <Sheet title="What should change?" onClose={onClose}>
      <div role="group" aria-label="Reasons" className="mt-4 flex flex-wrap gap-2">
        {reasons.map((r) => (
          <Chip key={r.id} tone="danger" pressed={picked.includes(r.id)} onClick={() => toggle(r.id)}>
            {r.label}
          </Chip>
        ))}
        <Chip tone="accent" pressed={pin} onClick={() => setPin((p) => !p)}>at {clock(at)}</Chip>
      </div>
      <textarea aria-label="What to change" value={text} onChange={(e) => setText(e.target.value)}
        rows={2} placeholder="Same video, shorter hook…" className={`${field} mt-3 block w-full py-2`} />
      <div className="mt-5 grid grid-cols-2 gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={!picked.length && !text.trim()}
          onClick={() => onSave({
            reason_codes: picked,
            ...(text.trim() && { text: text.trim() }),
            ...(pin && { video_time_s: at }),
            wants_changes: true,
          })}>
          Send for changes
        </Button>
      </div>
    </Sheet>
  )
}
