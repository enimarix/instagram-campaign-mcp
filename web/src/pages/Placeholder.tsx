import type { ReactNode } from 'react'
import { EmptyState } from '../ui/Card'
import { PageHeader } from '../ui/PageHeader'

/** A page not built yet; `children` says what will be there (default: a generic line). */
export default function Placeholder({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <section>
      <PageHeader title={title} />
      <EmptyState title="Coming soon.">{children ?? 'This part of the studio is not built yet.'}</EmptyState>
    </section>
  )
}
