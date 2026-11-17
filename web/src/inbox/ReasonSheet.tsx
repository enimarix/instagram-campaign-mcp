import { useEffect, useRef, useState } from 'react'
import type { Vocabulary } from '../api/client'
import { button } from './ui'

type Props = {
  reasons: Vocabulary['values']
  onSave: (codes: string[]) => Promise<void>
  onClose: () => void
}

// Bottom sheet after a dislike. A native modal <dialog> traps focus, makes the page
// behind it inert and closes on Esc (its `close` event lands in onClose).
export default function ReasonSheet({ reasons, onSave, onClose }: Props) {
  const ref = useRef<HTMLDialogElement>(null)
  const [picked, setPicked] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    if (!ref.current?.open) ref.current?.showModal()
  }, [])

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
    <dialog
      ref={ref}
      onClose={onClose}
      aria-labelledby="reason-title"
      className="mx-auto mt-auto mb-0 w-full max-w-full rounded-t-2xl bg-white p-4 pb-[max(1rem,env(safe-area-inset-bottom))] backdrop:bg-black/40 md:mb-auto md:max-w-md md:rounded-2xl"
    >
      <h2 id="reason-title" className="text-lg font-semibold">
        What was wrong?
      </h2>
      <div role="group" aria-label="Reasons" className="mt-3 flex flex-wrap gap-2">
        {reasons.map((r) => (
          <button
            key={r.id}
            type="button"
            aria-pressed={picked.includes(r.id)}
            onClick={() => toggle(r.id)}
            className={`${button} border ${
              picked.includes(r.id) ? 'border-red-600 bg-red-50 text-red-800' : 'border-gray-300'
            }`}
          >
            {r.label}
          </button>
        ))}
      </div>
      {failed && (
        <p role="alert" className="mt-3 text-sm text-red-700">
          Could not save. Try again.
        </p>
      )}
      <div className="mt-4 grid grid-cols-2 gap-2">
        <button type="button" onClick={onClose} className={`${button} bg-gray-100`}>
          Skip
        </button>
        <button
          type="button"
          onClick={save}
          disabled={!picked.length || busy}
          className={`${button} bg-red-600 text-white`}
        >
          Save
        </button>
      </div>
    </dialog>
  )
}
