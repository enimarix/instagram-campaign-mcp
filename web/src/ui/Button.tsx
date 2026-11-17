import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { buttonClass, type Size, type Variant } from './styles'

type Props = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: Size; loading?: boolean }

/** A button of the design system. `type` defaults to "button": pass type="submit" in forms. */
export function Button({ variant, size, loading, className = '', disabled, children, type = 'button', ...rest }: Props) {
  return (
    <button type={type} disabled={disabled || loading} aria-busy={loading || undefined}
      className={`${buttonClass(variant, size)} ${className}`} {...rest}>
      {loading && <span aria-hidden className="size-4 animate-spin rounded-full border-2 border-current border-r-transparent" />}
      {children}
    </button>
  )
}

/** A square icon-only button; `label` is its accessible name and tooltip. */
export function IconButton({ label, icon, className = '', ...rest }: Omit<Props, 'children'> & { label: string; icon: ReactNode }) {
  return (
    <Button aria-label={label} title={label} className={`w-11 px-0! ${className}`} {...rest}>
      {icon}
    </Button>
  )
}
