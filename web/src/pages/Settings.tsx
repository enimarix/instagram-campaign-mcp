import { useEffect, useState } from 'react'
import { getHealth, type Health } from '../api/client'

export default function Settings() {
  const [health, setHealth] = useState<Health | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getHealth().then(setHealth, (e: unknown) => setError(String(e)))
  }, [])

  return (
    <section>
      <h2 className="text-2xl font-semibold">Settings</h2>
      {health && !health.instagram_configured && (
        <p role="status" className="mt-4 rounded-lg bg-amber-100 p-4 text-amber-900">
          Setup mode: add your Instagram token
        </p>
      )}
      <dl className="mt-4 text-sm text-gray-600">
        <dt className="font-medium">Server</dt>
        <dd>{error ? `Unreachable (${error})` : health ? `${health.status}, v${health.version}` : 'Checking…'}</dd>
      </dl>
    </section>
  )
}
