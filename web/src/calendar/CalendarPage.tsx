import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router'
import {
  ApiError,
  cancelPost,
  errorMessage,
  getCalendar,
  releaseAsset,
  replanPost,
  type Calendar,
  type CalendarPost,
  type Slot,
} from '../api/client'
import { localDate } from '../inbox/ui'
import { Button } from '../ui/Button'
import { Card, EmptyState } from '../ui/Card'
import { Chip } from '../ui/Chip'
import { PageHeader } from '../ui/PageHeader'
import { link, type Tone } from '../ui/styles'
import HotHoursSheet from './HotHoursSheet'
import { dayLabel, slotLabel } from './when'

const STATUS_TONE: Record<CalendarPost['status'], Tone> = {
  pending: 'info', publishing: 'warn', published: 'success', failed: 'danger', cancelled: 'neutral',
}
const RELEASE_CONFIRM = 'I checked: it is not on Instagram. Release this video so it can be queued again?'
const RIGHTS_CONFIRM =
  'I checked this reaction video: my own take is a substantial part and the creator is credited.'

const addDays = (d: Date, n: number) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n)
const monday = (d: Date) => addDays(d, -((d.getDay() + 6) % 7))

type Act = (fn: () => Promise<unknown>) => Promise<boolean>
type Moved = Slot & { id: number } // where a re-planned video went
/** What a card asks the page for: run an action, show a week, say where a post went, pick a time. */
type Page = { act: Act; show: (local: string) => void; replanned: (to: Moved) => void; pick: (p: Moved) => void }

/** A failed row gets a new slot; a commentary clip asks the owner's check first (GOAL §5.1). */
async function replan(id: number) {
  try {
    return await replanPost(id)
  } catch (e) {
    if (!(e instanceof ApiError && e.code === 'rights' && window.confirm(`${errorMessage(e)}\n\n${RIGHTS_CONFIRM}`)))
      throw e
    return replanPost(id, true)
  }
}

// The publish queue by week (GOAL §3.3): a 7-column week from xl (1280 px), a list of the
// days that have posts on a phone.
export default function CalendarPage() {
  const [week, setWeek] = useState(() => monday(new Date()))
  const [cal, setCal] = useState<Calendar | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<Moved | null>(null) // the last Re-plan's new slot
  const [picking, setPicking] = useState<Moved | null>(null) // the post in the Reschedule sheet

  const load = useCallback(
    () => getCalendar(localDate(week), localDate(addDays(week, 6))).then(setCal, (e: unknown) => setError(errorMessage(e))),
    [week],
  )
  useEffect(() => {
    load()
  }, [load])

  // Run an action, then show the queue as the server has it now. True when it worked.
  const act: Act = async (fn) => {
    setError(null)
    setNotice(null)
    let ok = true
    try {
      await fn()
    } catch (e) {
      setError(errorMessage(e))
      ok = false
    }
    await load()
    return ok
  }

  const [today] = useState(() => localDate(new Date()))
  const show = (local: string) => setWeek(monday(new Date(`${local.slice(0, 10)}T00:00`)))
  const page: Page = { act, show, replanned: setNotice, pick: setPicking }
  return (
    <div className="space-y-4">
      <PageHeader title="Calendar" actions={
        <div className="flex gap-1">
          <Button size="sm" onClick={() => setWeek(addDays(week, -7))}>Previous week</Button>
          <Button size="sm" onClick={() => setWeek(monday(new Date()))}>This week</Button>
          <Button size="sm" onClick={() => setWeek(addDays(week, 7))}>Next week</Button>
        </div>
      } />
      {error && <p role="alert" className="text-sm text-danger">{error}</p>}
      {notice && (
        <p role="status" className="rounded-card border border-line/60 bg-surface-2 p-3 text-sm">
          Re-planned for <strong>{slotLabel(notice.local)}</strong> —{' '}
          <button type="button" className={link} onClick={() => show(notice.local)}>show it</button> or{' '}
          <button type="button" className={link} onClick={() => setPicking(notice)}>reschedule it</button>{' '}
          to pick another time.
        </p>
      )}
      {picking && (
        <HotHoursSheet post={picking} onClose={() => setPicking(null)}
          onSaved={() => { setPicking(null); setNotice(null); load() }} />
      )}
      {cal && cal.publish_check.length > 0 && (
        <section aria-labelledby="check-title" className="rounded-card border border-warn/30 bg-warn/12 p-4 text-sm">
          <h3 id="check-title" className="font-semibold">Did these reach Instagram?</h3>
          <p className="mt-1">
            The publish may have gone through. The worker looks for them on the account; if a video is
            not there, release it so it can be queued again.
          </p>
          <ul className="mt-2 space-y-2">
            {cal.publish_check.map((a) => (
              <li key={a.id} aria-label={`Video ${a.id}`} className="flex flex-wrap items-center gap-2">
                <Link to={`/assets/${a.id}`} className={`font-medium ${link}`}>Video {a.id}</Link>
                <span className="min-w-0 flex-1 truncate">{a.caption}</span>
                <Button size="sm" onClick={() => window.confirm(RELEASE_CONFIRM) && act(() => releaseAsset(a.id))}>
                  Not on Instagram → release
                </Button>
              </li>
            ))}
          </ul>
        </section>
      )}
      {cal && (
        <ol className="grid gap-3 xl:grid-cols-7 xl:gap-2">
          {cal.days.map((d) => (
            <li key={d.date} aria-label={d.date} className={d.posts.length ? '' : 'hidden xl:block'}>
              <h3 className={`mb-2 text-xs font-semibold tracking-wide uppercase ${d.date === today ? 'text-accent' : 'text-muted'}`}>
                {dayLabel(d.date)}
              </h3>
              <ul className="space-y-2">
                {d.posts.map((p) => <PostCard key={p.id} post={p} page={page} />)}
              </ul>
            </li>
          ))}
        </ol>
      )}
      {cal?.days.every((d) => !d.posts.length) && (
        <EmptyState title="Nothing queued this week.">Approved videos land here once they are scheduled.</EmptyState>
      )}
    </div>
  )
}

function PostCard({ post: p, page: { act, show, replanned, pick } }: { post: CalendarPost; page: Page }) {
  const moved = p.moved_to
  return (
    <Card as="li" aria-label={`Post ${p.id}`} className="p-3! text-sm">
      <div className="flex flex-wrap items-center gap-1.5">
        <strong className="tabular-nums">{p.local.slice(11, 16)}</strong>
        <Chip tone={STATUS_TONE[p.status]}>{p.status}</Chip>
        {p.replanned && <Chip tone="warn">re-planned</Chip>}
      </div>
      {p.caption && <p className="mt-1 line-clamp-3 break-words">{p.caption}</p>}
      {p.error && <p className={`mt-1 text-xs ${p.status === 'failed' ? 'text-danger' : 'text-muted'}`}>{p.error}</p>}
      {moved && (
        <p className="mt-1 text-xs text-muted">
          Re-planned →{' '}
          <button type="button" className={`inline-flex min-h-11 items-center ${link}`} onClick={() => show(moved.local)}>
            {slotLabel(moved.local)}
          </button>
        </p>
      )}
      <div className="mt-1 flex flex-wrap gap-x-3 text-xs">
        {p.asset_id !== null && (
          <Link to={`/assets/${p.asset_id}`} className={`inline-flex min-h-11 items-center ${link}`}>Video {p.asset_id}</Link>
        )}
        {p.permalink?.startsWith('https://') && (
          <a href={p.permalink} target="_blank" rel="noreferrer" className={`inline-flex min-h-11 items-center ${link}`}>On Instagram</a>
        )}
      </div>
      <div className="mt-2 flex flex-wrap gap-1">
        {p.status === 'pending' && <Button size="sm" onClick={() => pick(p)}>Reschedule</Button>}
        {p.status === 'failed' && (
          <Button size="sm" variant="primary" onClick={() => act(async () => replanned(await replan(p.id)))}>
            Re-plan
          </Button>
        )}
        {(p.status === 'pending' || p.status === 'failed') && (
          <Button size="sm" variant="ghost" onClick={() => window.confirm('Cancel this post?') && act(() => cancelPost(p.id))}>
            Cancel
          </Button>
        )}
      </div>
    </Card>
  )
}
