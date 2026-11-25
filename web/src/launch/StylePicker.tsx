import { useState } from 'react'
import type { CatalogStyle, Style } from '../api/client'
import { StyleGallery } from '../styles/StyleGallery'
import { Button } from '../ui/Button'
import { Chip } from '../ui/Chip'
import { Sheet } from '../ui/Sheet'
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
        {style.description && <> : {style.description}</>}
      </p>
    </div>
  )
}

/** One button per enabled style plus « Auto (l'IA choisit) » (null); the preview follows the
 * chosen one (a click: hovering selects nothing). compact: one scrolling row and a small
 * preview (the Tendances selection bar). all: « Tous les styles » opens the whole catalog
 * (studio + Lemo-Opuscar, step 172), for owner-mode orders only (the server refuses a Lemo
 * style on the others). */
export function StylePicker({ value, onChange, autoLabel = "Auto (l'IA choisit)", exclude, compact, all }: {
  value: string | null
  onChange: (style: string | null) => void
  autoLabel?: string
  exclude?: string | null // e.g. the video's own style on « même vidéo, autre style »
  compact?: boolean
  all?: boolean
}) {
  const { styles, error } = useStyles()
  const [gallery, setGallery] = useState(false)
  const [picked, setPicked] = useState<CatalogStyle | null>(null) // the last gallery pick, for its name
  const studio = styles?.filter((s) => s.enabled && s.id !== exclude)
  const shown = styles?.find((s) => s.id === value)
  const lemo = picked?.id === value && !shown ? picked : null
  // a value no studio button shows (a Lemo style, an order's style turned off since): its own chip
  const outside = value !== null && (styles !== undefined || error !== null) && !studio?.some((s) => s.id === value)
  return (
    <div>
      <p className="text-sm font-medium">Style</p>
      <div role="group" aria-label="Style" className={`mt-1 flex gap-2 ${compact ? 'overflow-x-auto pb-1 [&>*]:shrink-0' : 'flex-wrap'}`}>
        <Chip pressed={value === null} onClick={() => onChange(null)}>{autoLabel}</Chip>
        {studio?.map((s) => (
          <Chip key={s.id} pressed={value === s.id} onClick={() => onChange(s.id)}>{s.label}</Chip>
        ))}
        {outside && <Chip pressed onClick={() => onChange(value)}>{picked?.id === value ? picked.label : (shown?.label ?? value)}</Chip>}
        {all && <Button onClick={() => setGallery(true)}>Tous les styles</Button>}
      </div>
      {error && <p role="alert" className="mt-1 text-xs text-danger">Styles indisponibles : {error}</p>}
      {shown ? <StylePreview style={shown} small={compact} />
        : lemo ? (
          <p className="mt-2 rounded-control bg-surface-2 p-2 text-xs">
            <span className="font-semibold">{lemo.label}</span>{lemo.essence && <> : {lemo.essence}</>}
          </p>
        ) : value === null && <p className="mt-1 text-xs text-muted">L'IA choisit le style qui va le mieux à l'idée.</p>}
      {gallery && (
        <Sheet title="Tous les styles" wide onClose={() => setGallery(false)}>
          <div className="mt-3">
            <StyleGallery selectedId={value} onSelect={(id, s) => { // the video's own style: the server says so
              setPicked(s)
              onChange(id)
              setGallery(false)
            }} />
          </div>
        </Sheet>
      )}
    </div>
  )
}
