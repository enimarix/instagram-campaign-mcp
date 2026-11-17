import { useState } from 'react'
import type { Vocabulary } from '../api/client'
import { Button } from '../ui/Button'
import { Chip } from '../ui/Chip'
import { Sheet } from '../ui/Sheet'

type Props = {
  reasons: Vocabulary['values']
  onSave: (codes: string[]) => Promise<void>
  onClose: () => void
}

// The sheet after a dislike: pick the reasons, or skip.
export default function ReasonSheet({ reasons, onSave, onClose }: Props) {
  const [picked, setPicked] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState(false)

  const toggle = (id: string) =>
    setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]))

  async function save() {
    setBusy(true)
    setFailed(false)
    try {
      await onSave(picked)
    } catch {
      setFailed(true)
      setBusy(false)
    }
  }

  return (
    <Sheet title="What was wrong?" onClose={onClose}>
      <div role="group" aria-label="Reasons" className="mt-4 flex flex-wrap gap-2">
        {reasons.map((r) => (
          <Chip key={r.id} tone="danger" pressed={picked.includes(r.id)} onClick={() => toggle(r.id)}>
            {r.label}
          </Chip>
        ))}
      </div>
      {failed && (
        <p role="alert" className="mt-3 text-sm text-danger">
          Could not save. Try again.
        </p>
      )}
      <div className="mt-5 grid grid-cols-2 gap-2">
        <Button onClick={onClose}>Skip</Button>
        <Button variant="danger" onClick={save} disabled={!picked.length} loading={busy}>
          Save
        </Button>
      </div>
    </Sheet>
  )
}
