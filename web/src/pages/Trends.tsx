import { useCallback, useEffect, useState, type FormEvent } from 'react'
import {
  addWatch, errorMessage, getTrends, listWatchlist, removeWatch,
  type TrendItem, type TrendReport, type Watch,
} from '../api/client'
import { button, chip, safeUrl } from '../inbox/ui'

const label = (w: Pick<Watch, 'kind' | 'value'>) => (w.kind === 'hashtag' ? '#' : '@') + w.value

// Captions are other accounts' words: rendered as quoted text only, never as HTML.
function TrendCard({ item }: { item: TrendItem }) {
  const href = safeUrl(item.url)
  return (
    <li className="rounded-lg border border-gray-200 bg-white p-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold break-all">
          {item.account ? `@${item.account}` : `#${item.hashtag}`}
        </span>
        {item.outlier !== null ? (
          <span className={`${chip} bg-amber-100 text-amber-900`}>×{item.outlier} {item.metric}</span>
        ) : (
          <span className={`${chip} bg-gray-100 text-gray-600`} title={item.outlier_note ?? undefined}>
            no score
          </span>
        )}
        <span className="text-gray-500">posted {String(item.hour).padStart(2, '0')}:00</span>
        {item.duration_s !== null && <span className="text-gray-500">{Math.round(item.duration_s)} s</span>}
      </div>
      {item.outlier === null && item.outlier_note && (
        <p className="mt-1 text-xs text-gray-500">{item.outlier_note}</p>
      )}
      {item.hook_quote && <q className="mt-1 block break-words">{item.hook_quote}</q>}
      {item.hashtags.length > 0 && (
        <p className="mt-1 break-words text-xs text-blue-700">{item.hashtags.map((t) => `#${t}`).join(' ')}</p>
      )}
      {href && (
        <a href={href} target="_blank" rel="noopener noreferrer"
          className="mt-2 inline-flex min-h-11 items-center text-blue-600 underline">
          Open on Instagram
        </a>
      )}
    </li>
  )
}

function Watchlist() {
  const [items, setItems] = useState<Watch[] | null>(null)
  const [kind, setKind] = useState<Watch['kind']>('hashtag')
  const [value, setValue] = useState('')
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    listWatchlist().then(setItems, (e: unknown) => setError(errorMessage(e)))
  }, [])
  useEffect(load, [load])

  async function act(fn: () => Promise<unknown>) {
    setError(null)
    try {
      await fn()
      load()
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  function submit(e: FormEvent) {
    e.preventDefault()
    if (value.trim()) void act(() => addWatch(kind, value.trim()).then(() => setValue('')))
  }

  return (
    <section aria-label="Watchlist" className="mt-4">
      <h3 className="font-semibold">Watchlist</h3>
      <p className="text-xs text-gray-500">The agent's research looks these up (hashtag top posts, accounts' recent posts).</p>
      <form onSubmit={submit} className="mt-2 flex flex-wrap gap-2">
        <select aria-label="Kind" value={kind} onChange={(e) => setKind(e.target.value as Watch['kind'])}
          className="min-h-11 rounded-lg border border-gray-300 bg-white px-2 text-sm">
          <option value="hashtag">Hashtag</option>
          <option value="account">Account</option>
        </select>
        <input aria-label="Hashtag or username" value={value} onChange={(e) => setValue(e.target.value)}
          placeholder={kind === 'hashtag' ? '#fitness' : '@username'}
          className="min-h-11 min-w-0 flex-1 rounded-lg border border-gray-300 px-3 text-sm" />
        <button type="submit" className={`${button} bg-blue-600 text-white`}>Add</button>
      </form>
      {error && <p role="alert" className="mt-2 text-sm text-red-700">{error}</p>}
      {items === null ? (
        <p className="mt-2 text-sm text-gray-500">Loading…</p>
      ) : items.length === 0 ? (
        <p className="mt-2 text-sm text-gray-500">Nothing watched yet</p>
      ) : (
        <ul className="mt-2 flex flex-wrap gap-2">
          {items.map((w) => (
            <li key={w.id} className="flex items-center gap-1 rounded-full bg-gray-100 pl-3 text-sm">
              <span className="break-all">{label(w)}</span>
              <button type="button" aria-label={`Remove ${label(w)}`} className={`${button} px-2`}
                onClick={() => void act(() => removeWatch(w.id))}>
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

export default function Trends() {
  const [report, setReport] = useState<TrendReport | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getTrends().then(setReport, (e: unknown) => setError(errorMessage(e)))
  }, [])

  const tags = report ? Object.entries(report.hashtags) : []
  return (
    <section>
      <h2 className="text-2xl font-semibold">Trends</h2>
      <p className="text-sm text-gray-500">Last 14 days. ×N = the post against its account's (or hashtag's) median.</p>
      <Watchlist />
      <section aria-label="Trend report" className="mt-6">
        {error && <p role="alert" className="mt-2 text-sm text-red-700">{error}</p>}
        {report === null ? (
          !error && <p className="mt-2 text-sm text-gray-500">Loading…</p>
        ) : report.accounts.length === 0 && tags.length === 0 ? (
          <p className="mt-2 text-sm text-gray-500">No trends yet: add to the watchlist, then let the agent research.</p>
        ) : (
          <>
            {report.accounts.length > 0 && <h3 className="font-semibold">Watched accounts</h3>}
            <ul className="mt-2 space-y-2">
              {report.accounts.map((i) => <TrendCard key={i.source_id} item={i} />)}
            </ul>
            {tags.map(([tag, items]) => (
              <section key={tag} aria-label={`#${tag}`} className="mt-4">
                <h3 className="font-semibold">#{tag} <span className="text-xs font-normal text-gray-500">ranked within the hashtag</span></h3>
                <ul className="mt-2 space-y-2">
                  {items.map((i) => <TrendCard key={i.source_id} item={i} />)}
                </ul>
              </section>
            ))}
          </>
        )}
      </section>
    </section>
  )
}
