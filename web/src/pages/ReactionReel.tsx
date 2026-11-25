import { useCallback, useEffect, useState } from 'react'
import {
  activateReactionReel, errorMessage, listReactionReels, resetReactionReel, uploadReactionReel,
  type ReactionReel,
} from '../api/client'
import { Button } from '../ui/Button'
import { Card, Skeleton } from '../ui/Card'
import { buttonClass } from '../ui/styles'
import { clock } from './load'

// Same list as VIDEO_SUFFIXES in src/studio/reactions.py.
const ACCEPT = '.mp4,.mov,.m4v,.mkv,.webm'

/** Settings section: the long reaction recording each reaction video takes its next piece from. */
export default function ReactionReelSection() {
  const [reels, setReels] = useState<ReactionReel[]>()
  const [error, setError] = useState<string | null>(null)
  const [progress, setProgress] = useState<number | null>(null)

  const load = useCallback(
    () => listReactionReels().then(setReels, (e: unknown) => setError(errorMessage(e))), [])
  useEffect(() => { void load() }, [load])

  async function act(fn: () => Promise<unknown>) {
    setError(null)
    try {
      await fn()
      await load()
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  async function upload(file: File) {
    setProgress(0)
    await act(() => uploadReactionReel(file, setProgress))
    setProgress(null)
  }

  const active = reels?.find((r) => r.active)
  const others = reels?.filter((r) => !r.active) ?? []

  return (
    <Card as="section" id="reaction-reel" aria-label="Reaction reel" className="scroll-mt-16 lg:scroll-mt-4">
      <h2 className="font-semibold">Reaction reel</h2>
      <p className="mt-1 text-sm text-muted">
        One long recording of you reacting. Each reaction video uses the next piece of it, in a loop.
      </p>
      {reels === undefined && !error && <Skeleton className="mt-3 h-12" />}
      {reels && !active && (
        <p className="mt-2 text-sm">{others.length ? 'No reel in use: activate one below or upload a new one.' : 'No reel yet: upload one.'}</p>
      )}
      {active && (
        <div className="mt-2 text-sm">
          <p>
            {clock(active.cursor_s)} of {clock(active.duration_s)} used, {active.pieces_used}{' '}
            {active.pieces_used === 1 ? 'piece' : 'pieces'}
          </p>
          <div role="progressbar" aria-label="Reel used" aria-valuemin={0} aria-valuemax={100}
            aria-valuenow={active.used_pct} className="mt-2 h-2 overflow-hidden rounded-full bg-surface-2">
            <div className="h-full rounded-full bg-accent" style={{ width: `${active.used_pct}%` }} />
          </div>
          <Button size="sm" className="mt-3"
            onClick={() => {
              if (window.confirm('Start the reel over from the beginning?')) void act(() => resetReactionReel(active.id))
            }}>
            Reset
          </Button>
        </div>
      )}
      <label className={`${buttonClass('primary')} mt-3 flex w-full cursor-pointer has-focus-visible:outline-2 has-focus-visible:outline-offset-2 has-focus-visible:outline-accent md:inline-flex md:w-auto ${progress !== null ? 'opacity-60' : ''}`}>
        {progress === null ? 'Upload a reel' : progress < 1 ? `Uploading… ${Math.round(progress * 100)}%` : 'Processing…'}
        <input type="file" accept={ACCEPT} className="sr-only" disabled={progress !== null}
          onChange={(e) => {
            const file = e.target.files?.[0]
            e.target.value = ''
            if (file) void upload(file)
          }} />
      </label>
      {error && <p role="alert" className="mt-2 text-sm text-danger">{error}</p>}
      {others.length > 0 && (
        <ul aria-label="Other reels" className="mt-3 divide-y divide-line/60 text-sm">
          {others.map((r) => (
            <li key={r.id} className="flex items-center justify-between gap-2 py-2">
              <span>
                Reel {r.id} · {clock(r.duration_s)} · {r.used_pct}% used
              </span>
              <Button size="sm" onClick={() => void act(() => activateReactionReel(r.id))}>Activate</Button>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}
