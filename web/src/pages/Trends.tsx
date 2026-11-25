import { useCallback, useEffect, useState, type FormEvent } from 'react'
import {
  addInspiration, deleteInspiration, downloadReel, errorMessage, getTrends, listInspirations,
  setInspirationStatus, type Inspiration, type TrendItem, type TrendReport,
} from '../api/client'
import { safeUrl } from '../inbox/ui'
import { Button } from '../ui/Button'
import { Card, EmptyState, Skeleton } from '../ui/Card'
import { Chip } from '../ui/Chip'
import { PageHeader } from '../ui/PageHeader'
import { field, link, type Tone } from '../ui/styles'
import { useToast } from '../ui/useToast'
import { AskPermissionButton } from './Permissions'

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
        ? `Téléchargé pour une réaction${by}` : `Pas téléchargé : ${r.reason ?? r.status}` })
    } catch (e) {
      toast({ message: `Pas téléchargé : ${errorMessage(e)}` })
    } finally {
      setBusy(false)
    }
  }
  return (
    // Phones show "Télécharger" only: the full label pushed the row's other buttons to a second line.
    <Button size="sm" variant="ghost" loading={busy} aria-label="Télécharger pour une réaction" onClick={() => void download()}>
      Télécharger<span className="hidden sm:inline">&nbsp;pour une réaction</span>
    </Button>
  )
}

const METRIC: Record<string, string> = { views: 'vues', likes: 'likes' }

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
          <Chip tone="accent">×{item.outlier} {METRIC[item.metric ?? ''] ?? item.metric}</Chip>
        ) : (
          <Chip title={item.outlier_note ?? undefined}>pas de score</Chip>
        )}
        <span className="text-muted">publié à {String(item.hour).padStart(2, '0')}:00</span>
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
            Ouvrir sur Instagram
          </a>
        )}
        {href && <DownloadButton target={{ source_id: item.source_id }} />}
        <AskPermissionButton target={{ source_id: item.source_id }} />
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
const STATUS: Record<Inspiration['status'], string> = { new: 'nouvelle', used: 'utilisée', dismissed: 'écartée' }

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
      <p className="text-xs text-muted">Colle un lien de Reel et dis ce qui te plaît. L’agent apprend le format, il ne le copie jamais.</p>
      <form onSubmit={submit} className="mt-3 flex flex-col gap-2">
        <input aria-label="Lien du Reel" type="url" inputMode="url" value={url} onChange={(e) => setUrl(e.target.value)}
          placeholder="https://www.instagram.com/reel/…"
          className={`${field} min-w-0`} />
        <div className="flex gap-2">
          <input aria-label="Note" value={note} maxLength={200} onChange={(e) => setNote(e.target.value)}
            placeholder="ce format est drôle"
            className={`${field} min-w-0 flex-1`} />
          <Button type="submit" variant="primary">Ajouter</Button>
        </div>
      </form>
      {error && <p role="alert" className="mt-2 text-sm text-danger">{error}</p>}
      {items === null ? (
        !error && <Skeleton className="mt-3 h-12" />
      ) : items.length === 0 ? (
        <p className="mt-3 text-sm text-muted">Pas encore d’inspirations</p>
      ) : (
        <ul className="mt-3 space-y-2">
          {items.map((i) => {
            const href = safeUrl(i.url)
            return (
              <li key={i.id} className="rounded-control bg-surface-2 p-3 text-sm">
                <div className="flex items-start gap-2">
                  <p className="min-w-0 flex-1 break-words">{i.note ?? <span className="text-muted">Pas de note</span>}</p>
                  <Chip tone={STATUS_TONE[i.status]}>{STATUS[i.status]}</Chip>
                </div>
                <div className="mt-1 flex flex-wrap items-center gap-2">
                  {href && (
                    <a href={href} target="_blank" rel="noopener noreferrer"
                      className={`mr-auto inline-flex min-h-11 items-center ${link}`}>
                      Ouvrir
                    </a>
                  )}
                  {href && <DownloadButton target={{ url: i.url }} />}
                  {href && <AskPermissionButton target={{ url: i.url }} />}
                  {i.status !== 'dismissed' && (
                    <Button size="sm" variant="ghost" onClick={() => void act(() => setInspirationStatus(i.id, 'dismissed'))}>
                      Écarter
                    </Button>
                  )}
                  <Button size="sm" variant="ghost" className="text-danger!" onClick={() => void act(() => deleteInspiration(i.id))}>
                    Supprimer
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

export default function Trends() {
  const [report, setReport] = useState<TrendReport | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getTrends().then(setReport, (e: unknown) => setError(errorMessage(e)))
  }, [])

  const tags = report ? Object.entries(report.hashtags) : []
  return (
    <section>
      <PageHeader title="Tendances" back={{ to: '/trending', label: 'Trending' }}>
        14 derniers jours. ×N = la publication face à la médiane de son compte (ou de son hashtag). Les sujets suivis se modifient sur Trending.
      </PageHeader>
      <Inspirations />
      <section aria-label="Rapport des tendances" className="mt-8">
        {error && <p role="alert" className="mt-2 text-sm text-danger">{error}</p>}
        {report === null ? (
          !error && <Skeleton className="h-32" />
        ) : report.accounts.length === 0 && tags.length === 0 ? (
          <EmptyState title="Pas encore de tendances">Ajoute des sujets sur Trending, puis actualise.</EmptyState>
        ) : (
          <>
            {report.accounts.length > 0 && <h2 className="text-lg font-semibold">Comptes suivis</h2>}
            <ul className="mt-3 grid gap-3 md:grid-cols-2">
              {report.accounts.map((i) => <TrendCard key={i.source_id} item={i} />)}
            </ul>
            {tags.map(([tag, items]) => (
              <section key={tag} aria-label={`#${tag}`} className="mt-6">
                <h2 className="text-lg font-semibold">#{tag} <span className="text-xs font-normal text-muted">classés dans le hashtag</span></h2>
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
