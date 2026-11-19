import { useState } from 'react'
import type { Style } from '../api/client'
import { Chip } from '../ui/Chip'
import { useStyles } from './useStyles'

/** What a style looks like: its sample clip (muted, looping) or still, and its one line. */
function StylePreview({ style, small }: { style: Style; small?: boolean }) {
  const { still, clip } = style.preview
  const box = `aspect-[9/16] ${small ? 'w-12' : 'w-20'} shrink-0 rounded-control bg-black object-cover`
  return (
    <div aria-label={`Aperçu ${style.label}`} className="mt-2 flex items-start gap-3 rounded-control bg-surface-2 p-2">
      {clip ? (
        <video key={clip} src={clip} poster={still ?? undefined} muted autoPlay loop playsInline preload="metadata"
          className={box} />
      ) : still ? (
        <img src={still} alt="" className={box} />
      ) : null}
      <p className="text-xs">
        <span className="font-semibold">{style.label}</span>
        {style.description && <> : {style.description}</>}
      </p>
    </div>
  )
}

/** One button per enabled style plus « Auto (l'IA choisit) » (null). The preview follows the
 * hovered button (desktop) or the chosen one (a tap, on a phone). compact: one scrolling row
 * and a small preview (the Tendances selection bar). */
export function StylePicker({ value, onChange, autoLabel = "Auto (l'IA choisit)", exclude, compact }: {
  value: string | null
  onChange: (style: string | null) => void
  autoLabel?: string
  exclude?: string | null // e.g. the video's own style on « même vidéo, autre style »
  compact?: boolean
}) {
  const { styles, error } = useStyles()
  const [peek, setPeek] = useState<string | null>(null)
  const shown = styles?.find((s) => s.id === (peek ?? value))
  return (
    <div>
      <p className="text-sm font-medium">Style</p>
      <div role="group" aria-label="Style" className={`mt-1 flex gap-2 ${compact ? 'overflow-x-auto pb-1 [&>*]:shrink-0' : 'flex-wrap'}`}>
        <Chip pressed={value === null} onClick={() => onChange(null)}>{autoLabel}</Chip>
        {styles?.filter((s) => s.enabled && s.id !== exclude).map((s) => (
          <span key={s.id} className="inline-flex" onMouseEnter={() => setPeek(s.id)} onMouseLeave={() => setPeek(null)}
            onFocus={() => setPeek(s.id)} onBlur={() => setPeek(null)}>
            <Chip pressed={value === s.id} onClick={() => onChange(s.id)} title={s.description ?? undefined}>{s.label}</Chip>
          </span>
        ))}
      </div>
      {error && <p role="alert" className="mt-1 text-xs text-danger">Styles indisponibles : {error}</p>}
      {shown ? <StylePreview style={shown} small={compact} />
        : <p className="mt-1 text-xs text-muted">L'IA choisit le style qui va le mieux à l'idée.</p>}
    </div>
  )
}
