import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import {
  errorMessage, listDmPicks, listPinnedAccounts, pinAccount, skipDmPick, unpinAccount,
  type DmPick, type DmPickStatus, type PinnedAccount,
} from '../api/client'
import { safeUrl } from '../inbox/ui'
import { Button, IconButton } from '../ui/Button'
import { Card, Skeleton } from '../ui/Card'
import { Chip } from '../ui/Chip'
import { CloseIcon } from '../ui/icons'
import { field, link, type Tone } from '../ui/styles'
import { dateTime } from './load'

const STATUS_TONE: Record<DmPickStatus, Tone> = {
  new: 'accent', downloaded: 'info', in_production: 'explore', posted: 'success', skipped: 'neutral',
}

/** The Skip button of a `new` pick; it asks for the reason inline. */
function SkipForm({ pick, onDone }: { pick: DmPick; onDone: () => Promise<void> }) {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  if (!open) return <Button size="sm" onClick={() => setOpen(true)}>Skip</Button>

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await skipDmPick(pick.id, String(new FormData(e.currentTarget).get('reason') ?? ''))
      await onDone()
    } catch (err) {
      setError(errorMessage(err))
      setBusy(false)
    }
  }

  return (
    <form aria-label={`Skip pick from @${pick.sender_username}`} onSubmit={(e) => void submit(e)}
      className="mt-2 flex w-full flex-wrap items-end gap-2">
      <label className="min-w-0 flex-1">Why skip it?
        <input name="reason" required maxLength={300} className={`${field} mt-1 block w-full`} />
      </label>
      <Button type="submit" variant="danger" size="sm" loading={busy}>Skip pick</Button>
      <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>Cancel</Button>
      {error && <p role="alert" className="w-full text-danger">{error}</p>}
    </form>
  )
}

/** The picks: Reels the pinned accounts sent by DM (on the Trending page, Mes envois). */
export function DmPicksList() {
  const [picks, setPicks] = useState<DmPick[]>()
  const [error, setError] = useState<string | null>(null)

  const reload = useCallback(() => listDmPicks().then(setPicks, (e: unknown) => setError(errorMessage(e))), [])
  useEffect(() => { void reload() }, [reload])

  if (error) return <p role="alert" className="mt-2 text-sm text-danger">{error}</p>
  if (!picks) return <Skeleton className="mt-3 h-12" />
  if (picks.length === 0) return <p className="mt-2 text-sm text-muted">No picks yet</p>
  return (
    <ul aria-label="Picks" className="mt-1 divide-y divide-line/60 text-sm">
      {picks.map((p) => {
        const href = safeUrl(p.reel_url)
        return (
          <li key={p.id} className="flex flex-wrap items-center gap-x-2 gap-y-1 py-2">
            <Chip tone={STATUS_TONE[p.status]}>{p.status.replace('_', ' ')}</Chip>
            <span className="font-medium">@{p.sender_username}</span>
            <span className="ml-auto text-muted">{dateTime(p.received_at)}</span>
            {p.sender_note && <q className="w-full break-words italic">{p.sender_note}</q>}
            {p.skip_reason && <p className="w-full text-muted">Skipped: {p.skip_reason}</p>}
            {href && (
              <a href={href} target="_blank" rel="noopener noreferrer" className={`inline-flex min-h-11 items-center ${link}`}>
                Open Reel
              </a>
            )}
            {p.status === 'new' && <SkipForm pick={p} onDone={reload} />}
          </li>
        )
      })}
    </ul>
  )
}

/** Settings section: the pinned accounts whose DM'd Reels become picks (listed on Trending). */
export default function DmPicksSection() {
  const [pinned, setPinned] = useState<PinnedAccount[]>()
  const [loadError, setLoadError] = useState<unknown>()
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const reload = useCallback(() => listPinnedAccounts().then(setPinned, setLoadError), [])
  useEffect(() => { void reload() }, [reload])

  async function act(fn: () => Promise<unknown>) {
    setError(null)
    try {
      await fn()
      await reload()
      return true
    } catch (e) {
      setError(errorMessage(e))
      return false
    }
  }

  async function pin(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const form = e.currentTarget
    const f = new FormData(form)
    setBusy(true)
    if (await act(() => pinAccount(String(f.get('username') ?? ''), String(f.get('note') ?? '').trim()))) form.reset()
    setBusy(false)
  }

  return (
    <Card as="section" id="dm-picks" aria-label="DM picks" className="scroll-mt-16 lg:scroll-mt-4">
      <h2 className="font-semibold">DM picks</h2>
      <p className="mt-1 text-sm text-muted">
        Only Reels these accounts send the brand account by DM become picks: they show on{' '}
        <Link to="/trending?tab=envois" className={link}>Trending, Mes envois</Link>. Nothing is ever sent back.
        Reading DMs needs the <code>instagram_manage_messages</code> permission.
      </p>
      {loadError !== undefined ? (
        <p role="alert" className="mt-2 text-sm text-danger">{errorMessage(loadError)}</p>
      ) : !pinned ? (
        <Skeleton className="mt-3 h-12" />
      ) : (
        <>
          <h3 className="mt-4 text-sm font-medium">Pinned accounts</h3>
          {pinned.length === 0 ? (
            <p className="mt-1 text-sm text-muted">No pinned accounts yet: pin one below.</p>
          ) : (
            <ul aria-label="Pinned accounts" className="mt-1 divide-y divide-line/60 text-sm">
              {pinned.map((a) => (
                <li key={a.id} className="flex items-center justify-between gap-2 py-1">
                  <span className="min-w-0 break-words">
                    <span className="font-medium">@{a.username}</span>
                    {a.note && <span className="text-muted"> · {a.note}</span>}
                  </span>
                  <IconButton variant="ghost" label={`Unpin @${a.username}`} icon={<CloseIcon className="size-4" />}
                    onClick={() => {
                      if (window.confirm(`Unpin @${a.username}? Their DMs stop counting; existing picks stay.`))
                        void act(() => unpinAccount(a.id))
                    }} />
                </li>
              ))}
            </ul>
          )}
          <form aria-label="Pin an account" onSubmit={(e) => void pin(e)} className="mt-2 grid gap-2 text-sm sm:grid-cols-[1fr_1fr_auto] sm:items-end">
            <label>Instagram username
              <input name="username" required autoComplete="off" placeholder="@friend" className={`${field} mt-1 block w-full`} />
            </label>
            <label>Note (optional)
              <input name="note" maxLength={300} className={`${field} mt-1 block w-full`} />
            </label>
            <Button type="submit" variant="primary" loading={busy}>Pin</Button>
          </form>
          {error && <p role="alert" className="mt-2 text-sm text-danger">{error}</p>}
        </>
      )}
    </Card>
  )
}
