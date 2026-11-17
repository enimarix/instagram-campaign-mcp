// Class strings of the design system, for elements that are not one of the ui/ components
// (a <Link> styled as a button, a <label> wrapping a file input, inputs, selects).

export type Variant = 'primary' | 'secondary' | 'ghost' | 'danger'
export type Size = 'sm' | 'md' | 'lg'
export type Tone = 'neutral' | 'accent' | 'success' | 'warn' | 'danger' | 'info' | 'explore'

const VARIANT: Record<Variant, string> = {
  primary: 'bg-accent text-on-accent hover:brightness-110',
  secondary: 'bg-surface-2 text-fg hover:bg-line',
  ghost: 'text-fg hover:bg-surface-2',
  danger: 'bg-danger text-on-accent hover:brightness-110',
}
// Every size keeps the 44 px touch target; sizes change padding and type only.
const SIZE: Record<Size, string> = {
  sm: 'min-h-11 px-3 text-sm',
  md: 'min-h-11 px-4 text-sm',
  lg: 'min-h-12 px-5 text-base',
}

export const buttonClass = (variant: Variant = 'secondary', size: Size = 'md') =>
  `inline-flex items-center justify-center gap-2 rounded-control font-medium transition select-none active:scale-[.98] disabled:pointer-events-none disabled:opacity-40 ${VARIANT[variant]} ${SIZE[size]}`

// Soft fill + coloured text; written out so Tailwind sees every class.
export const TONE: Record<Tone, string> = {
  neutral: 'bg-surface-2 text-muted',
  accent: 'bg-accent/12 text-accent',
  success: 'bg-success/12 text-success',
  warn: 'bg-warn/12 text-warn',
  danger: 'bg-danger/12 text-danger',
  info: 'bg-info/12 text-info',
  explore: 'bg-explore/12 text-explore',
}

export const card = 'rounded-card border border-line/60 bg-surface shadow-card'
export const field =
  'min-h-11 rounded-control border border-line bg-surface-2 px-3 text-sm text-fg placeholder:text-muted'
export const link = 'text-accent underline decoration-accent/40 underline-offset-2 hover:decoration-accent'

/** Like / Dislike on a secondary Button: coloured text, filled while pressed. */
export const verdictButton = (tone: 'success' | 'danger', pressed: boolean) =>
  tone === 'success'
    ? pressed ? 'bg-success! text-on-accent!' : 'text-success!'
    : pressed ? 'bg-danger! text-on-accent!' : 'text-danger!'
