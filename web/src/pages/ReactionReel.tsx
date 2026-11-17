import { useCallback, useEffect, useState } from 'react'
import {
  activateReactionReel, errorMessage, listReactionReels, resetReactionReel, uploadReactionReel,
  type ReactionReel,
} from '../api/client'
import { button } from '../inbox/ui'

// Same list as VIDEO_SUFFIXES in src/studio/reactions.py.
const ACCEPT = '.mp4,.mov,.m4v,.mkv,.webm'

const pad = (n: number) => String(n).padStart(2, '0')
/** 754 → "12:34", 3725 → "1:02:05". */
function clock(seconds: number) {
  const t = Math.floor(seconds)
  const h = Math.floor(t / 3600)
  const m = Math.floor((t % 3600) / 60)
  return h ? `${h}:${pad(m)}:${pad(t % 60)}` : `${m}:${pad(t % 60)}`
}

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
    <section aria-label="Reaction reel" className="mt-4 rounded-lg border border-gray-200 bg-white p-4">
      <h3 className="font-semibold">Reaction reel</h3>
      <p className="mt-1 text-sm text-gray-500">
        One long recording of you reacting. Each reaction video uses the next piece of it, in a loop.
      </p>
      {reels === undefined && !error && <p className="mt-2 text-sm text-gray-500">Loading…</p>}
      {reels && !active && <p className="mt-2 text-sm">No reel yet: upload one.</p>}
      {active && (
        <div className="mt-2 text-sm">
          <p>
            {clock(active.cursor_s)} of {clock(active.duration_s)} used, {active.pieces_used}{' '}
            {active.pieces_used === 1 ? 'piece' : 'pieces'}
          </p>
          <div role="progressbar" aria-label="Reel used" aria-valuemin={0} aria-valuemax={100}
            aria-valuenow={active.used_pct} className="mt-1 h-2 overflow-hidden rounded bg-gray-200">
            <div className="h-full bg-blue-600" style={{ width: `${active.used_pct}%` }} />
          </div>
          <button type="button" className={`${button} mt-2 bg-gray-100`}
            onClick={() => {
              if (window.confirm('Start the reel over from the beginning?')) void act(() => resetReactionReel(active.id))
            }}>
            Reset
          </button>
        </div>
      )}
      <label className={`${button} mt-3 flex w-full cursor-pointer items-center justify-center bg-blue-600 text-white md:inline-flex md:w-auto ${progress !== null ? 'opacity-60' : ''}`}>
        {progress === null ? 'Upload a reel' : progress < 1 ? `Uploading… ${Math.round(progress * 100)}%` : 'Processing…'}
        <input type="file" accept={ACCEPT} className="sr-only" disabled={progress !== null}
          onChange={(e) => {
            const file = e.target.files?.[0]
            e.target.value = ''
            if (file) void upload(file)
          }} />
      </label>
      {error && <p role="alert" className="mt-2 text-sm text-red-700">{error}</p>}
      {others.length > 0 && (
        <ul aria-label="Other reels" className="mt-3 divide-y divide-gray-100 text-sm">
          {others.map((r) => (
            <li key={r.id} className="flex items-center justify-between gap-2 py-2">
              <span>
                Reel {r.id} · {clock(r.duration_s)} · {r.used_pct}% used
              </span>
              <button type="button" className={`${button} bg-gray-100`}
                onClick={() => void act(() => activateReactionReel(r.id))}>
                Activate
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
