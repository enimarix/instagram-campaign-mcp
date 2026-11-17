import { useEffect, useRef, useState, type PointerEvent } from 'react'
import type { Asset, Verdict } from '../api/client'
import { button, chip } from './ui'

const SWIPE_PX = 80 // horizontal travel that counts as a like / dislike
const VISIBLE = 0.6 // share of the video on screen before it plays

const STATUS_COLOR: Record<string, string> = {
  ready: 'bg-blue-100 text-blue-800',
  approved: 'bg-green-100 text-green-800',
  failed: 'bg-red-100 text-red-800',
}

type Props = {
  asset: Asset
  current: boolean
  onVerdict: (v: Verdict) => void
  onApprove: () => void
  onFocus: () => void
}

export default function AssetCard({ asset: a, current, onVerdict, onApprove, onFocus }: Props) {
  const video = useRef<HTMLVideoElement>(null)
  const start = useRef<{ x: number; y: number } | null>(null)
  const [dx, setDx] = useState(0)
  const [muted, setMuted] = useState(true)

  // Play while mostly visible, pause otherwise. jsdom has no IntersectionObserver.
  useEffect(() => {
    const v = video.current
    if (!v || typeof IntersectionObserver === 'undefined') return
    const io = new IntersectionObserver(
      ([e]) => (e.intersectionRatio >= VISIBLE ? v.play().catch(() => {}) : v.pause()),
      { threshold: VISIBLE },
    )
    io.observe(v)
    return () => io.disconnect()
  }, [])

  // Swipe on touch only. `touch-pan-y` leaves vertical scrolling to the browser, which
  // then sends pointercancel, so a scroll never turns into a verdict.
  function down(e: PointerEvent) {
    if (e.pointerType === 'touch') start.current = { x: e.clientX, y: e.clientY }
  }
  function move(e: PointerEvent) {
    const s = start.current
    if (s && Math.abs(e.clientX - s.x) > Math.abs(e.clientY - s.y)) setDx(e.clientX - s.x)
  }
  function up(e: PointerEvent) {
    const s = start.current
    cancel()
    if (!s) return
    const x = e.clientX - s.x
    if (Math.abs(x) >= SWIPE_PX && Math.abs(x) > Math.abs(e.clientY - s.y))
      onVerdict(x > 0 ? 'liked' : 'disliked')
  }
  function cancel() {
    start.current = null
    setDx(0)
  }

  return (
    <article
      id={`asset-${a.id}`}
      aria-label={`Video ${a.id}`}
      onFocusCapture={onFocus}
      onPointerDown={down}
      onPointerMove={move}
      onPointerUp={up}
      onPointerCancel={cancel}
      style={dx ? { transform: `translateX(${dx}px)` } : undefined}
      className={`touch-pan-y overflow-hidden rounded-xl bg-white shadow-sm ${
        current ? 'ring-2 ring-blue-500' : ''
      } ${a.verdict === 'liked' ? 'border-l-4 border-green-500' : ''} ${
        a.verdict === 'disliked' ? 'border-l-4 border-red-500 opacity-70' : ''
      }`}
    >
      <div className="relative">
        {/* No native controls: their seek bar would fight the horizontal swipe. */}
        <video
          ref={video}
          src={a.preview_url ?? undefined}
          poster={a.thumbnail_url ?? undefined}
          muted={muted}
          playsInline
          loop
          preload="metadata"
          className="mx-auto aspect-[9/16] max-h-[70dvh] w-full bg-black object-contain"
        />
        <button
          type="button"
          onClick={() => setMuted((m) => !m)}
          className={`${button} absolute top-2 right-2 bg-black/60 text-white`}
        >
          {muted ? 'Sound on' : 'Mute'}
        </button>
      </div>
      <div className="space-y-2 p-3">
        <div className="flex flex-wrap gap-1">
          <span className={`${chip} ${STATUS_COLOR[a.status] ?? 'bg-gray-100 text-gray-700'}`}>
            {a.status.replace('_', ' ')}
          </span>
          {a.strategy === 'explore' && (
            <span className={`${chip} bg-purple-100 text-purple-800`}>Explore</span>
          )}
          {a.track && <span className={`${chip} bg-gray-100 text-gray-700`}>{a.track}</span>}
        </div>
        {a.self_score != null && (
          <p className="truncate text-sm" title={a.self_score_reason ?? undefined}>
            <strong>{a.self_score}/10</strong> {a.self_score_reason}
          </p>
        )}
        {a.caption && <p className="line-clamp-2 text-sm text-gray-600">{a.caption}</p>}
        <div className="grid grid-cols-3 gap-2">
          <button
            type="button"
            aria-pressed={a.verdict === 'disliked'}
            onClick={() => onVerdict('disliked')}
            className={`${button} ${a.verdict === 'disliked' ? 'bg-red-600 text-white' : 'bg-red-50 text-red-800'}`}
          >
            Dislike
          </button>
          <button
            type="button"
            aria-pressed={a.verdict === 'liked'}
            onClick={() => onVerdict('liked')}
            className={`${button} ${a.verdict === 'liked' ? 'bg-green-600 text-white' : 'bg-green-50 text-green-800'}`}
          >
            Like
          </button>
          {a.status === 'ready' && (
            <button type="button" onClick={onApprove} className={`${button} bg-blue-600 text-white`}>
              Approve
            </button>
          )}
        </div>
      </div>
    </article>
  )
}
