import { useEffect, useRef, useState, type PointerEvent } from 'react'
import { Link } from 'react-router'
import type { Asset, Verdict } from '../api/client'
import { Button, IconButton } from '../ui/Button'
import { Chip } from '../ui/Chip'
import { SoundOffIcon, SoundOnIcon } from '../ui/icons'
import { card, link, verdictButton, type Tone } from '../ui/styles'
import { ScheduledSlot } from './ScheduleSheet'

const SWIPE_PX = 80 // horizontal travel that counts as a like / dislike
const VISIBLE = 0.6 // share of the video on screen before it plays

const STATUS_TONE: Record<string, Tone> = { ready: 'info', approved: 'success', failed: 'danger' }

type Props = {
  asset: Asset
  current: boolean
  showBestBefore?: boolean // bench cards
  onVerdict: (v: Verdict) => void
  onApprove: () => void
  onSchedule: () => void
  onChange: (a: Asset) => void
  onFocus: () => void
}

export default function AssetCard({ asset: a, current, showBestBefore, onVerdict, onApprove, onSchedule, onChange, onFocus }: Props) {
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
      className={`${card} touch-pan-y overflow-hidden transition-[opacity,box-shadow] ${
        current ? 'md:ring-2 md:ring-accent' : '' // keyboard cursor (desktop)
      } ${a.verdict === 'liked' ? 'border-l-4 border-l-success' : ''} ${
        a.verdict === 'disliked' ? 'border-l-4 border-l-danger opacity-70' : ''
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
        <IconButton
          label={muted ? 'Sound on' : 'Mute'}
          icon={muted ? <SoundOffIcon /> : <SoundOnIcon />}
          onClick={() => setMuted((m) => !m)}
          className="absolute top-3 right-3 rounded-full bg-black/55! text-white! backdrop-blur hover:bg-black/70!"
        />
      </div>
      <div className="space-y-3 p-4">
        <div className="flex flex-wrap gap-1.5">
          <Chip tone={STATUS_TONE[a.status] ?? 'neutral'}>{a.status.replace('_', ' ')}</Chip>
          {a.strategy === 'explore' && <Chip tone="explore">Explore</Chip>}
          {a.track && <Chip>{a.track}</Chip>}
          {showBestBefore && a.best_before && <Chip tone="warn">best before {a.best_before}</Chip>}
        </div>
        {a.self_score != null && (
          <p className="truncate text-sm text-muted" title={a.self_score_reason ?? undefined}>
            <strong className="mr-1 text-base text-fg tabular-nums">{a.self_score}/10</strong> {a.self_score_reason}
          </p>
        )}
        {a.caption && <p className="line-clamp-2 text-sm">{a.caption}</p>}
        <Link to={`/assets/${a.id}`} className={`inline-flex min-h-11 items-center text-sm ${link}`}>
          Details and comments
        </Link>
        <div className="grid grid-cols-3 gap-2">
          <Button aria-pressed={a.verdict === 'disliked'} onClick={() => onVerdict('disliked')}
            className={verdictButton('danger', a.verdict === 'disliked')}>
            Dislike
          </Button>
          <Button aria-pressed={a.verdict === 'liked'} onClick={() => onVerdict('liked')}
            className={verdictButton('success', a.verdict === 'liked')}>
            Like
          </Button>
          {a.status === 'ready' && <Button variant="primary" onClick={onApprove}>Approve</Button>}
          {a.status === 'approved' && <Button variant="primary" onClick={onSchedule}>Schedule</Button>}
        </div>
        {a.status === 'scheduled' && <ScheduledSlot assetId={a.id} onUnscheduled={onChange} />}
      </div>
    </article>
  )
}
