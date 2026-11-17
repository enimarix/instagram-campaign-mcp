import type { ReactNode } from 'react'

export default function Placeholder({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <section>
      <h2 className="text-2xl font-semibold">{title}</h2>
      <p className="mt-2 text-gray-500">Coming soon.</p>
      {children}
    </section>
  )
}
