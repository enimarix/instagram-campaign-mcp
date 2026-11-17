import type { ReactNode } from 'react'
import { TONE, type Tone } from './styles'

type Props = { tone?: Tone; children: ReactNode; className?: string; title?: string }
type Toggle = Props & { pressed: boolean; onClick: () => void }

const base = 'inline-flex items-center gap-1 rounded-full font-medium'

/** A small status label, or with `onClick` + `pressed` a 44 px toggle chip (aria-pressed). */
export function Chip(props: Props | Toggle) {
  const { tone = 'neutral', children, className = '', title } = props
  if (!('onClick' in props))
    return <span title={title} className={`${base} px-2.5 py-0.5 text-xs ${TONE[tone]} ${className}`}>{children}</span>
  const on = props.pressed
  return (
    <button type="button" aria-pressed={on} title={title} onClick={props.onClick}
      className={`${base} min-h-11 border px-4 text-sm transition ${
        on ? `border-current ${TONE[tone === 'neutral' ? 'accent' : tone]}` : 'border-line bg-surface-2 text-fg hover:bg-line'
      } ${className}`}>
      {children}
    </button>
  )
}
