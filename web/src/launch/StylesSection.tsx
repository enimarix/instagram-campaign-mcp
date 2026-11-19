import { useEffect, useState } from 'react'
import { errorMessage, listStyles, setStyle, type Style } from '../api/client'
import { Card, Skeleton } from '../ui/Card'
import { field } from '../ui/styles'

/** Settings: every style (step 138), on / off (its launch button shows or not, and the AI
 * stops picking it) and an optional daily share (empty: no limit). */
export default function StylesSection() {
  const [styles, setStyles] = useState<Style[]>()
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    listStyles().then(setStyles, (e: unknown) => setError(errorMessage(e)))
  }, [])

  async function save(s: Style, body: { enabled?: boolean; share?: number | null }) {
    setError(null)
    try {
      const next = await setStyle(s.id, body)
      setStyles((list) => list?.map((x) => (x.id === s.id ? next : x)))
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  function saveShare(s: Style, text: string) {
    const share = text.trim() === '' ? null : Number(text) / 100
    if (share !== s.share) void save(s, { share })
  }

  return (
    <Card as="section" aria-label="Styles">
      <h2 className="font-semibold">Styles</h2>
      <p className="mt-1 text-sm text-muted">
        One launch button per style that is on; the AI only picks those. Daily share: at most that
        part of a day's batch in the style (empty: no limit; your own orders always pass).
      </p>
      {error && <p role="alert" className="mt-2 text-sm text-danger">{error}</p>}
      {styles === undefined ? (
        !error && <Skeleton className="mt-3 h-12" />
      ) : (
        <ul className="mt-3 divide-y divide-line/60 text-sm">
          {styles.map((s) => (
            <li key={s.id} className="flex flex-wrap items-center gap-3 py-2">
              <label className="flex min-h-11 items-center gap-2 font-medium">
                <input type="checkbox" checked={s.enabled} onChange={(e) => void save(s, { enabled: e.target.checked })}
                  className="size-5 accent-(--color-accent)" />
                {s.label}
              </label>
              <label className="ml-auto flex items-center gap-2 text-muted">
                Daily share
                <input type="number" min={1} max={100} step={1} inputMode="numeric" aria-label={`${s.label} daily share (%)`}
                  key={s.share ?? 'none'} defaultValue={s.share == null ? '' : Math.round(s.share * 100)}
                  onBlur={(e) => saveShare(s, e.target.value)} className={`${field} w-20`} />
                %
              </label>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}
