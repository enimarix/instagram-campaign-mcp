import type { ReactNode } from 'react'
import { EmptyState } from '../ui/Card'
import { PageHeader } from '../ui/PageHeader'

export default function Placeholder({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <section>
      <PageHeader title={title} />
      <EmptyState title="Coming soon.">This part of the studio is not built yet.</EmptyState>
      {children}
    </section>
  )
}
