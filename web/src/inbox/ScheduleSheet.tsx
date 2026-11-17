import { useEffect, useRef, useState } from 'react'
import {
  errorMessage,
  getProposedSlot,
  getSlot,
  scheduleAsset,
  unscheduleAsset,
  type Asset,
  type ProposedSlot,
} from '../api/client'
import { button } from './ui'

/** "2026-11-18T11:00:00+01:00" → "2026-11-18 11:00": the owner's wall-clock time as sent. */
const wallClock = (iso: string) => iso.slice(0, 16).replace('T', ' ')

/** A Date as a <input type="datetime-local"> value, in the browser's time zone. */
function inputValue(d: Date) {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

type Props = {
  assetId: number
  onScheduled: (a: Asset) => void
  onClose: () => void
}

// Second step after approving: accept the planner's slot or pick another time. Same
// native modal <dialog> as ReasonSheet.
export default function ScheduleSheet({ assetId, onScheduled, onClose }: Props) {
  const ref = useRef<HTMLDialogElement>(null)
  const [slot, setSlot] = useState<ProposedSlot | null>(null)
  const [picking, setPicking] = useState(false)
  const [when, setWhen] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!ref.current?.open) ref.current?.showModal()
  }, [])

  useEffect(() => {
    getProposedSlot(assetId).then(
      (s) => {
        setSlot(s)
        setWhen(inputValue(new Date(s.publish_at)))
      },
      (e: unknown) => setError(`No slot proposed (${errorMessage(e)}). Pick a time.`),
    )
  }, [assetId])

  async function schedule(publishAt: string) {
    setBusy(true)
    setError(null)
    try {
      onScheduled((await scheduleAsset(assetId, publishAt, confirmed)).asset)
    } catch (e) {
      setError(errorMessage(e))
      setBusy(false)
    }
  }

  const blocked = busy || (slot?.needs_confirmation === true && !confirmed)

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      aria-labelledby="schedule-title"
      className="mx-auto mt-auto mb-0 w-full max-w-full rounded-t-2xl bg-white p-4 pb-[max(1rem,env(safe-area-inset-bottom))] backdrop:bg-black/40 md:mb-auto md:max-w-md md:rounded-2xl"
    >
      <h2 id="schedule-title" className="text-lg font-semibold">Schedule this video</h2>
      <p className="mt-2 text-sm">
        {slot ? <>Proposed time: <strong>{wallClock(slot.local)}</strong></> : !error && 'Finding a slot…'}
      </p>
      {slot?.needs_confirmation && (
        <label className="mt-3 flex items-start gap-2 text-sm">
          <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)}
            className="mt-1 size-4" />
          I checked this reaction video: my own take is a substantial part and the creator is credited.
        </label>
      )}
      {picking && (
        <label className="mt-3 block text-sm font-medium">
          Another time
          <input type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)}
            className="mt-1 block min-h-11 w-full rounded-lg border border-gray-300 px-2 font-normal" />
        </label>
      )}
      {error && <p role="alert" className="mt-3 text-sm text-red-700">{error}</p>}
      <div className="mt-4 grid grid-cols-2 gap-2">
        <button type="button" onClick={onClose} className={`${button} bg-gray-100`}>
          Later
        </button>
        {picking ? (
          <button type="button" disabled={blocked || !when}
            onClick={() => schedule(new Date(when).toISOString())}
            className={`${button} bg-blue-600 text-white`}>
            Schedule at this time
          </button>
        ) : (
          <>
            <button type="button" disabled={blocked || !slot} onClick={() => slot && schedule(slot.publish_at)}
              className={`${button} bg-blue-600 text-white`}>
              Accept
            </button>
            <button type="button" onClick={() => setPicking(true)} className={`${button} col-span-2 bg-gray-100`}>
              Pick another time
            </button>
          </>
        )}
      </div>
    </dialog>
  )
}

/** A scheduled asset's slot, with the action that takes it out of the queue (→ approved). */
export function ScheduledSlot({ assetId, onUnscheduled }: { assetId: number; onUnscheduled: (a: Asset) => void }) {
  const [local, setLocal] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getSlot(assetId).then((s) => setLocal(s.local), () => {}) // no time shown: still unschedulable
  }, [assetId])

  async function unschedule() {
    setError(null)
    try {
      onUnscheduled(await unscheduleAsset(assetId))
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  return (
    <div className="space-y-1">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span>Scheduled{local && <> for <strong>{wallClock(local)}</strong></>}</span>
        <button type="button" onClick={unschedule} className={`${button} bg-gray-100`}>Unschedule</button>
      </div>
      {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
    </div>
  )
}
