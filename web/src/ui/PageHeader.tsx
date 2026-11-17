import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { BackIcon } from './icons'

type Props = { title: string; back?: { to: string; label: string }; actions?: ReactNode; children?: ReactNode }

/** Every page's top: an optional back link, the page title (h1), actions, a subtitle. */
export function PageHeader({ title, back, actions, children }: Props) {
  return (
    <header className="mb-5">
      {back && (
        <Link to={back.to}
          className="-ml-2 inline-flex min-h-11 items-center gap-1 rounded-control pr-3 pl-1 text-sm font-medium text-muted hover:text-fg">
          <BackIcon />{back.label}
        </Link>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="mr-auto text-2xl font-bold tracking-tight lg:text-3xl">{title}</h1>
        {actions}
      </div>
      {children && <div className="mt-1 text-sm text-muted">{children}</div>}
    </header>
  )
}
