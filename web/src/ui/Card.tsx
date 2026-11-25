import type { HTMLAttributes, ReactNode } from 'react'
import { EmptyIcon } from './icons'
import { card } from './styles'

type CardProps = HTMLAttributes<HTMLElement> & { as?: 'div' | 'section' | 'li' | 'article' }

/** A raised surface with the standard padding. A section with aria-label stays a landmark. */
export function Card({ as: Tag = 'div', className = '', ...rest }: CardProps) {
  return <Tag className={`${card} p-4 ${className}`} {...rest} />
}

/** One KPI tile; render it inside a <dl>. */
export function Stat({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className={`${card} p-4`}>
      <dt className="text-xs font-medium text-muted">{label}</dt>
      <dd className="mt-1 text-2xl font-semibold tracking-tight tabular-nums">{value}</dd>
      {sub && <dd className="mt-0.5 text-xs text-muted">{sub}</dd>}
    </div>
  )
}

/** "Nothing here yet" with an optional hint and action. */
export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-card border border-dashed border-line px-4 py-8 text-center">
      <EmptyIcon className="size-8 text-muted" />
      <p className="font-medium">{title}</p>
      {children && <p className="max-w-sm text-sm text-muted">{children}</p>}
      {action}
    </div>
  )
}

/** A pulsing placeholder block while data loads; screen readers hear « Chargement… ». */
export function Skeleton({ className = 'h-16' }: { className?: string }) {
  return (
    <div className={`animate-pulse rounded-card bg-surface-2 ${className}`}>
      <span className="sr-only">Chargement…</span>
    </div>
  )
}
