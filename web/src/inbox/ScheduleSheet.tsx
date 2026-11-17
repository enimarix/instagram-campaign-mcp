import { useEffect, useState } from 'react'
import {
  errorMessage,
  getProposedSlot,
  getSlot,
  scheduleAsset,
  unscheduleAsset,
  type Asset,
  type ProposedSlot,
} from '../api/client'
import { Button } from '../ui/Button'
import { Sheet } from '../ui/Sheet'
import { field } from '../ui/styles'
import { inputValue, wallClock } from './ui'

type Props = {
  assetId: number
  onScheduled: (a: Asset) => void
  onClose: () => void
}

// Second step after approving: accept the planner's slot or pick another time.
export default function ScheduleSheet({ assetId, onScheduled, onClose }: Props) {
  const [slot, setSlot] = useState<ProposedSlot | null>(null)
  const [picking, setPicking] = useState(false)
  const [when, setWhen] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

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
    <Sheet title="Schedule this video" onClose={onClose}>
      <p className="mt-2 text-sm text-muted">
        {slot ? <>Proposed time: <strong className="text-fg">{wallClock(slot.local)}</strong></> : !error && 'Finding a slot…'}
      </p>
      {slot?.needs_confirmation && (
        <label className="mt-3 flex items-start gap-2 text-sm">
          <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)}
            className="mt-0.5 size-5" />
          I checked this reaction video: my own take is a substantial part and the creator is credited.
        </label>
      )}
      {picking && (
        <label className="mt-3 block text-sm font-medium">
          Another time
          <input type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)}
            className={`${field} mt-1 block w-full font-normal`} />
        </label>
      )}
      {error && <p role="alert" className="mt-3 text-sm text-danger">{error}</p>}
      <div className="mt-5 grid grid-cols-2 gap-2">
        <Button onClick={onClose}>Later</Button>
        {picking ? (
          <Button variant="primary" disabled={blocked || !when} onClick={() => schedule(new Date(when).toISOString())}>
            Schedule at this time
          </Button>
        ) : (
          <>
            <Button variant="primary" disabled={blocked || !slot} onClick={() => slot && schedule(slot.publish_at)}>
              Accept
            </Button>
            <Button variant="ghost" className="col-span-2" onClick={() => setPicking(true)}>
              Pick another time
            </Button>
          </>
        )}
      </div>
    </Sheet>
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
        <span className="text-muted">Scheduled{local && <> for <strong className="text-fg">{wallClock(local)}</strong></>}</span>
        <Button size="sm" onClick={unschedule}>Unschedule</Button>
      </div>
      {error && <p role="alert" className="text-sm text-danger">{error}</p>}
    </div>
  )
}
