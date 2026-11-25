import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Link } from 'react-router'
import type { Asset } from '../api/client'
import { IconButton } from '../ui/Button'
import { Chip } from '../ui/Chip'
import { BookmarkIcon, CheckIcon, CloseIcon, EditIcon, InfoIcon, SoundOffIcon, SoundOnIcon } from '../ui/icons'
import { buttonClass } from '../ui/styles'
import { VoiceBadge } from '../voices/VoiceBadge'
import { bestBeforeLabel } from './ui'

type Props = {
  asset: Asset
  index: number // in the feed: the page's IntersectionObserver reads it back (data-index)
  active: boolean // the card on screen: it plays
  preload: boolean // the next card: its preview loads ahead
  muted: boolean
  showBestBefore?: boolean // bench cards
  settling?: boolean // a decision was just taken: the decision buttons wait a moment (UI-001)
  change?: string | null // a revised video: "Changé : « … »", what the owner asked (133)
  onToggleSound: () => void
  onApprove: () => void
  onDecline: () => void
  onChange: () => void
  onSave?: () => void // « Garder » (onto the bench); not on bench cards
}

const onVideo = 'rounded-full bg-black/55! text-white! backdrop-blur hover:bg-black/70!' // small buttons on the video

// The rail's round buttons (Reels-like): white on the video, the theme's beside it (desktop).
function RailButton({ label, icon, onClick, primary, disabled }: { label: string; icon: ReactNode; onClick: () => void; primary?: boolean; disabled?: boolean }) {
  return (
    <button type="button" onClick={onClick} disabled={disabled}
      className="group flex min-w-14 flex-col items-center gap-1 text-xs font-medium text-white lg:text-fg">
      <span aria-hidden className={`grid size-12 place-items-center rounded-full shadow-overlay transition group-active:scale-95 ${
        primary ? 'bg-accent text-on-accent' : 'bg-black/55 ring-1 ring-white/25 ring-inset backdrop-blur group-hover:bg-black/70 lg:bg-surface-2 lg:text-fg lg:ring-0 lg:group-hover:bg-line'}`}>
        {icon}
      </span>
      {label}
    </button>
  )
}

/** One screen of the review feed: the video, an overlay of what the agent says about it,
 * and the decision rail (Approuver, Changer, Refuser). */
export default function AssetCard({ asset: a, index, active, preload, muted, showBestBefore, settling, change, onToggleSound, onApprove, onDecline, onChange, onSave }: Props) {
  const video = useRef<HTMLVideoElement>(null)
  const [expanded, setExpanded] = useState(false)

  useEffect(() => {
    const v = video.current
    if (!v) return
    if (active) v.play()?.catch(() => {}) // autoplay refused: the poster stays, a tap starts it
    else v.pause()
  }, [active])

  return (
    <article id={`asset-${a.id}`} data-index={index} aria-label={`Vidéo ${a.id}`}
      className="relative flex h-full snap-start snap-always justify-center lg:gap-4">
      {/* data-theme: on the video, chips and buttons keep the dark theme's colours (light ones fail contrast on black). */}
      <div data-theme="dark" className="relative h-full w-full overflow-hidden bg-black lg:aspect-[9/16] lg:w-auto lg:rounded-card">
        {/* Tap = sound on / off, like Reels. No native controls: the feed scrolls. */}
        <video ref={video} src={a.preview_url ?? undefined} poster={a.poster_url ?? a.thumbnail_url ?? undefined}
          muted={muted} playsInline loop preload={active || preload ? 'auto' : 'none'}
          onClick={onToggleSound} className="size-full object-contain" />
        <div className="absolute top-3 right-3 flex gap-2">
          <IconButton label={muted ? 'Activer le son' : 'Couper le son'} icon={muted ? <SoundOffIcon /> : <SoundOnIcon />}
            onClick={onToggleSound} className={onVideo} />
          {onSave && <IconButton label="Garder" icon={<BookmarkIcon />} onClick={onSave} disabled={settling}
            className={`${onVideo} disabled:pointer-events-auto! disabled:opacity-100!`} />}
          <Link to={`/assets/${a.id}`} aria-label="Détails" title="Détails"
            className={`${buttonClass('secondary')} w-11 px-0! ${onVideo}`}>
            <InfoIcon />
          </Link>
        </div>
        <div className="pointer-events-none absolute inset-x-0 bottom-0 space-y-2 bg-linear-to-t from-black/85 via-black/50 to-transparent px-4 pt-20 pr-24 pb-4 text-white lg:pr-4">
          <div className="flex flex-wrap gap-1.5">
            {a.work_order && <Chip tone="info">{a.work_order.source === 'dm' ? 'Mes envois' : 'Tendance'}</Chip>}
            {a.dm_pick_sender && <Chip tone="accent">Choix DM de @{a.dm_pick_sender}</Chip>}
            {a.rights_basis === 'commentary' && <Chip tone="warn">commentaire</Chip>}
            {a.recipe?.inputs?.reaction && <Chip tone="accent">réaction</Chip>}
            {a.recipe?.voiced_by && <VoiceBadge by={a.recipe.voiced_by} />}
            {a.strategy === 'explore' && <Chip tone="explore">Exploration</Chip>}
            {a.track && <Chip>{a.track}</Chip>}
            {a.pillar && <Chip>{a.pillar}</Chip>}
            {showBestBefore && a.best_before && <Chip tone="warn">{bestBeforeLabel(a.best_before)}</Chip>}
          </div>
          {change && <p className="line-clamp-2 text-sm font-medium">{change}</p>}
          {a.work_order?.instruction && <p className="line-clamp-2 text-sm">Ta consigne : « {a.work_order.instruction} »</p>}
          {/* the agent's note on a new version: what it changed (no self-score since 189) */}
          {change && a.self_score_reason && <p className="truncate text-sm" title={a.self_score_reason}>{a.self_score_reason}</p>}
          {a.description && (
            <button type="button" aria-expanded={expanded} onClick={() => setExpanded((x) => !x)}
              className={`pointer-events-auto text-left text-sm ${expanded ? '' : 'line-clamp-2'}`}>
              {a.description}
            </button>
          )}
          {a.caption && <p className="line-clamp-1 text-sm text-white/75">{a.caption}</p>}
        </div>
      </div>
      {/* Phone: above the trial Reel choice and the undo toast, which would cover it for 5 s. */}
      <div className="absolute right-2 bottom-38 flex flex-col items-center gap-4 lg:static lg:justify-end lg:pb-6">
        <RailButton label="Approuver" icon={<CheckIcon />} onClick={onApprove} disabled={settling} primary />
        <RailButton label="Changer" icon={<EditIcon />} onClick={onChange} disabled={settling} />
        <RailButton label="Refuser" icon={<CloseIcon />} onClick={onDecline} disabled={settling} />
      </div>
    </article>
  )
}
