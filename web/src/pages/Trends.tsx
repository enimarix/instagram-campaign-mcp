import { useCallback, useEffect, useState, type FormEvent } from 'react'
import {
  addInspiration, addWatch, deleteInspiration, downloadReel, errorMessage, getTrends, listInspirations,
  listWatchlist, removeWatch, setInspirationStatus,
  type Inspiration, type TrendItem, type TrendReport, type Watch,
} from '../api/client'
import { safeUrl } from '../inbox/ui'
import { Button, IconButton } from '../ui/Button'
import { Card, EmptyState, Skeleton } from '../ui/Card'
import { Chip } from '../ui/Chip'
import { CloseIcon } from '../ui/icons'
import { PageHeader } from '../ui/PageHeader'
import { field, link, type Tone } from '../ui/styles'
import { useToast } from '../ui/useToast'

const label = (w: Pick<Watch, 'kind' | 'value'>) => (w.kind === 'hashtag' ? '#' : '@') + w.value

/** Saves the Reel for a reaction (step 063b); the toast says downloaded, or refused and why. */
function DownloadButton({ target }: { target: { source_id: number } | { url: string } }) {
  const toast = useToast()
  const [busy, setBusy] = useState(false)

  async function download() {
    setBusy(true)
    try {
      const r = await downloadReel(target)
      const by = r.source?.author ? ` (@${r.source.author})` : ''
      toast({ message: r.status === 'downloaded' || r.status === 'exists'
        ? `Downloaded for reaction${by}` : `Not downloaded: ${r.reason ?? r.status}` })
    } catch (e) {
      toast({ message: `Not downloaded: ${errorMessage(e)}` })
    } finally {
      setBusy(false)
    }
  }
  return (
    <Button size="sm" variant="ghost" loading={busy} onClick={() => void download()}>
      Download for reaction
    </Button>
  )
}

// Captions are other accounts' words: rendered as quoted text only, never as HTML.
function TrendCard({ item }: { item: TrendItem }) {
  const href = safeUrl(item.url)
  return (
    <Card as="li" className="text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold break-all">
          {item.account ? `@${item.account}` : `#${item.hashtag}`}
        </span>
        {item.outlier !== null ? (
          <Chip tone="accent">×{item.outlier} {item.metric}</Chip>
        ) : (
          <Chip title={item.outlier_note ?? undefined}>no score</Chip>
        )}
        <span className="text-muted">posted {String(item.hour).padStart(2, '0')}:00</span>
        {item.duration_s !== null && <span className="text-muted">{Math.round(item.duration_s)} s</span>}
      </div>
      {item.outlier === null && item.outlier_note && (
        <p className="mt-1 text-xs text-muted">{item.outlier_note}</p>
      )}
      {item.hook_quote && <q className="mt-2 block break-words">{item.hook_quote}</q>}
      {item.hashtags.length > 0 && (
        <p className="mt-1 break-words text-xs text-info">{item.hashtags.map((t) => `#${t}`).join(' ')}</p>
      )}
      <div className="mt-1 flex flex-wrap items-center gap-2">
        {href && (
          <a href={href} target="_blank" rel="noopener noreferrer"
            className={`mr-auto inline-flex min-h-11 items-center ${link}`}>
            Open on Instagram
          </a>
        )}
        {href && <DownloadButton target={{ source_id: item.source_id }} />}
      </div>
    </Card>
  )
}

/** A list the box edits: `act` runs a change, then reloads (or shows the error). */
function useEditableList<T>(fetchAll: () => Promise<T[]>) {
  const [items, setItems] = useState<T[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    fetchAll().then(setItems, (e: unknown) => setError(errorMessage(e)))
  }, [fetchAll])
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
  return { items, error, act }
}

const STATUS_TONE: Record<Inspiration['status'], Tone> = { new: 'info', used: 'success', dismissed: 'neutral' }

// Reels the owner pastes from the phone (step 051b); the agent reads the new ones.
function Inspirations() {
  const { items, error, act } = useEditableList(listInspirations)
  const [url, setUrl] = useState('')
  const [note, setNote] = useState('')

  function submit(e: FormEvent) {
    e.preventDefault()
    if (url.trim()) {
      void act(() => addInspiration(url.trim(), note.trim()).then(() => {
        setUrl('')
        setNote('')
      }))
    }
  }

  return (
    <Card as="section" aria-label="Inspirations">
      <h2 className="font-semibold">Inspirations</h2>
      <p className="text-xs text-muted">Paste a Reel link and say what you like about it. The agent learns the format, never copies it.</p>
      <form onSubmit={submit} className="mt-3 flex flex-col gap-2">
        <input aria-label="Reel link" type="url" inputMode="url" value={url} onChange={(e) => setUrl(e.target.value)}
          placeholder="https://www.instagram.com/reel/…"
          className={`${field} min-w-0`} />
        <div className="flex gap-2">
          <input aria-label="Note" value={note} maxLength={200} onChange={(e) => setNote(e.target.value)}
            placeholder="this format is funny"
            className={`${field} min-w-0 flex-1`} />
          <Button type="submit" variant="primary">Add</Button>
        </div>
      </form>
      {error && <p role="alert" className="mt-2 text-sm text-danger">{error}</p>}
      {items === null ? (
        !error && <Skeleton className="mt-3 h-12" />
      ) : items.length === 0 ? (
        <p className="mt-3 text-sm text-muted">No inspirations yet</p>
      ) : (
        <ul className="mt-3 space-y-2">
          {items.map((i) => {
            const href = safeUrl(i.url)
            return (
              <li key={i.id} className="rounded-control bg-surface-2 p-3 text-sm">
                <div className="flex items-start gap-2">
                  <p className="min-w-0 flex-1 break-words">{i.note ?? <span className="text-muted">No note</span>}</p>
                  <Chip tone={STATUS_TONE[i.status]}>{i.status}</Chip>
                </div>
                <div className="mt-1 flex flex-wrap items-center gap-2">
                  {href && (
                    <a href={href} target="_blank" rel="noopener noreferrer"
                      className={`mr-auto inline-flex min-h-11 items-center ${link}`}>
                      Open
                    </a>
                  )}
                  {href && <DownloadButton target={{ url: i.url }} />}
                  {i.status !== 'dismissed' && (
                    <Button size="sm" variant="ghost" onClick={() => void act(() => setInspirationStatus(i.id, 'dismissed'))}>
                      Dismiss
                    </Button>
                  )}
                  <Button size="sm" variant="ghost" className="text-danger!" onClick={() => void act(() => deleteInspiration(i.id))}>
                    Delete
                  </Button>
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </Card>
  )
}

function Watchlist() {
  const { items, error, act } = useEditableList(listWatchlist)
  const [kind, setKind] = useState<Watch['kind']>('hashtag')
  const [value, setValue] = useState('')

  function submit(e: FormEvent) {
    e.preventDefault()
    if (value.trim()) void act(() => addWatch(kind, value.trim()).then(() => setValue('')))
  }

  return (
    <Card as="section" aria-label="Watchlist">
      <h2 className="font-semibold">Watchlist</h2>
      <p className="text-xs text-muted">The agent's research looks these up (hashtag top posts, accounts' recent posts).</p>
      <form onSubmit={submit} className="mt-3 flex flex-wrap gap-2">
        <select aria-label="Kind" value={kind} onChange={(e) => setKind(e.target.value as Watch['kind'])}
          className={field}>
          <option value="hashtag">Hashtag</option>
          <option value="account">Account</option>
        </select>
        <input aria-label="Hashtag or username" value={value} onChange={(e) => setValue(e.target.value)}
          placeholder={kind === 'hashtag' ? '#fitness' : '@username'}
          className={`${field} min-w-0 flex-1`} />
        <Button type="submit" variant="primary">Add</Button>
      </form>
      {error && <p role="alert" className="mt-2 text-sm text-danger">{error}</p>}
      {items === null ? (
        <Skeleton className="mt-3 h-11" />
      ) : items.length === 0 ? (
        <p className="mt-3 text-sm text-muted">Nothing watched yet</p>
      ) : (
        <ul className="mt-3 flex flex-wrap gap-2">
          {items.map((w) => (
            <li key={w.id} className="flex items-center rounded-full bg-surface-2 pl-4 text-sm">
              <span className="break-all">{label(w)}</span>
              <IconButton variant="ghost" label={`Remove ${label(w)}`} icon={<CloseIcon className="size-4" />}
                className="rounded-full text-muted" onClick={() => void act(() => removeWatch(w.id))} />
            </li>
          ))}
        </ul>
      )}
    </Card>
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
      <PageHeader title="Trends">Last 14 days. ×N = the post against its account's (or hashtag's) median.</PageHeader>
      <div className="grid gap-4 lg:grid-cols-2">
        <Inspirations />
        <Watchlist />
      </div>
      <section aria-label="Trend report" className="mt-8">
        {error && <p role="alert" className="mt-2 text-sm text-danger">{error}</p>}
        {report === null ? (
          !error && <Skeleton className="h-32" />
        ) : report.accounts.length === 0 && tags.length === 0 ? (
          <EmptyState title="No trends yet">Add to the watchlist, then let the agent research.</EmptyState>
        ) : (
          <>
            {report.accounts.length > 0 && <h2 className="text-lg font-semibold">Watched accounts</h2>}
            <ul className="mt-3 grid gap-3 md:grid-cols-2">
              {report.accounts.map((i) => <TrendCard key={i.source_id} item={i} />)}
            </ul>
            {tags.map(([tag, items]) => (
              <section key={tag} aria-label={`#${tag}`} className="mt-6">
                <h2 className="text-lg font-semibold">#{tag} <span className="text-xs font-normal text-muted">ranked within the hashtag</span></h2>
                <ul className="mt-3 grid gap-3 md:grid-cols-2">
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
