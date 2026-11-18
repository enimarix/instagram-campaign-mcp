import type { WorkMode } from '../api/client'
import { Chip } from '../ui/Chip'
import { MODES } from './format'

/** Inspiré / Réaction, with what the chosen one means. */
export function ModePicker({ value, onChange }: { value: WorkMode; onChange: (m: WorkMode) => void }) {
  return (
    <div>
      <div role="group" aria-label="Mode" className="flex gap-2">
        {MODES.map((m) => (
          <Chip key={m.id} pressed={value === m.id} onClick={() => onChange(m.id)}>{m.label}</Chip>
        ))}
      </div>
      <p className="mt-1 text-xs text-muted">{MODES.find((m) => m.id === value)?.hint}</p>
    </div>
  )
}

/** Instagram's embed page of a Reel (when there is no playable media); `src` from embedSrc. */
export function Embed({ src, title }: { src: string; title: string }) {
  return (
    <iframe src={src} title={title} loading="lazy"
      sandbox="allow-scripts allow-same-origin allow-popups allow-popups-to-escape-sandbox"
      className="aspect-[9/16] max-h-[75dvh] w-full rounded-control border-0 bg-surface-2" />
  )
}
