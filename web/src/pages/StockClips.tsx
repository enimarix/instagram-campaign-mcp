import { useEffect, useState, type FormEvent } from 'react'
import { addStockClip, errorMessage, searchStock, stockStatus, type StockResult } from '../api/client'
import { safeUrl } from '../inbox/ui'
import { Button } from '../ui/Button'
import { field } from '../ui/styles'

/** Stock clips (step 064): search Pexels and add a video as a licensed clip. Hidden until
 * PEXELS_API_KEY is set. */
export default function StockClips({ onAdded }: { onAdded: () => void }) {
  const [configured, setConfigured] = useState(false)
  const [results, setResults] = useState<StockResult[]>()
  const [added, setAdded] = useState<number[]>([])
  const [busy, setBusy] = useState<number | 'search' | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    stockStatus().then((s) => setConfigured(s.configured), () => setConfigured(false))
  }, [])
  if (!configured) return null

  async function run(what: number | 'search', fn: () => Promise<void>) {
    setBusy(what)
    setError(null)
    try {
      await fn()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(null)
    }
  }
  function search(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const q = String(new FormData(e.currentTarget).get('q') ?? '').trim()
    if (q) void run('search', async () => setResults(await searchStock(q)))
  }
  const add = (id: number) => run(id, async () => {
    await addStockClip(id)
    setAdded((a) => [...a, id])
    onAdded()
  })

  return (
    <section aria-label="Clips de banque" className="mt-4 border-t border-line/60 pt-4 text-sm">
      <h3 className="font-semibold">Clips de banque</h3>
      <p className="mt-1 text-muted">Vidéos Pexels, libres d’usage sous la licence Pexels (créditées à leur auteur).</p>
      <form role="search" onSubmit={search} className="mt-2 flex gap-2">
        <input name="q" type="search" aria-label="Chercher des clips de banque" placeholder="ex. gym, course"
          className={`${field} min-w-0 flex-1`} />
        <Button type="submit" loading={busy === 'search'}>Chercher</Button>
      </form>
      {error && <p role="alert" className="mt-2 text-danger">{error}</p>}
      {results?.length === 0 && <p className="mt-2">Aucune vidéo trouvée.</p>}
      {results && results.length > 0 && (
        <ul className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3">
          {results.map((r) => (
            <li key={r.id} className="flex flex-col gap-1">
              {safeUrl(r.image) && (
                <img src={safeUrl(r.image)!} alt={`Vidéo Pexels ${r.id}`} loading="lazy"
                  className="aspect-[9/16] w-full rounded-control object-cover" />
              )}
              <span className="break-words text-xs text-muted">
                {r.author ?? 'Inconnu'} · {r.duration_s ?? '?'} s
              </span>
              <Button size="sm" disabled={added.includes(r.id)} loading={busy === r.id}
                onClick={() => void add(r.id)} aria-label={`Ajouter la vidéo Pexels ${r.id}`}>
                {added.includes(r.id) ? 'Ajoutée' : 'Ajouter'}
              </Button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
