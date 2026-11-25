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
import { COMMENTARY_CONFIRMATION, localDate } from '../inbox/ui'
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
const STATUS_LABEL: Record<CalendarPost['status'], string> = {
  pending: 'en attente', publishing: 'en cours', published: 'publiée', failed: 'échouée', cancelled: 'annulée',
}
const RELEASE_CONFIRM = 'J’ai vérifié : elle n’est pas sur Instagram. Libérer cette vidéo pour qu’elle puisse être reprogrammée ?'

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
    if (!(e instanceof ApiError && e.code === 'rights' && window.confirm(`${errorMessage(e)}\n\n${COMMENTARY_CONFIRMATION}`)))
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
      <PageHeader title="Calendrier" actions={
        <div className="flex flex-wrap gap-1">
          <Button size="sm" onClick={() => setWeek(addDays(week, -7))}>Semaine précédente</Button>
          <Button size="sm" onClick={() => setWeek(monday(new Date()))}>Cette semaine</Button>
          <Button size="sm" onClick={() => setWeek(addDays(week, 7))}>Semaine suivante</Button>
        </div>
      }>
        {cal && `${dayLabel(cal.days[0].date)} – ${dayLabel(cal.days.at(-1)!.date)}`}
      </PageHeader>
      {error && <p role="alert" className="text-sm text-danger">{error}</p>}
      {notice && (
        <p role="status" className="rounded-card border border-line/60 bg-surface-2 p-3 text-sm">
          Reprogrammée le <strong>{slotLabel(notice.local)}</strong> —{' '}
          <button type="button" className={link} onClick={() => show(notice.local)}>la voir</button> ou{' '}
          <button type="button" className={link} onClick={() => setPicking(notice)}>changer l’heure</button>.
        </p>
      )}
      {picking && (
        <HotHoursSheet post={picking} onClose={() => setPicking(null)}
          onSaved={() => { setPicking(null); setNotice(null); load() }} />
      )}
      {cal && cal.publish_check.length > 0 && (
        <section aria-labelledby="check-title" className="rounded-card border border-warn/30 bg-warn/12 p-4 text-sm">
          <h2 id="check-title" className="font-semibold">Ces vidéos sont-elles arrivées sur Instagram ?</h2>
          <p className="mt-1">
            La publication est peut-être passée. Le Worker les cherche sur le compte ; si une vidéo
            n’y est pas, libère-la pour qu’elle puisse être reprogrammée.
          </p>
          <ul className="mt-2 space-y-2">
            {cal.publish_check.map((a) => (
              <li key={a.id} aria-label={`Vidéo ${a.id}`} className="flex flex-wrap items-center gap-2">
                <Link to={`/assets/${a.id}`} className={`font-medium ${link}`}>Vidéo {a.id}</Link>
                <span className="min-w-0 flex-1 truncate">{a.caption}</span>
                <Button size="sm" onClick={() => window.confirm(RELEASE_CONFIRM) && act(() => releaseAsset(a.id))}>
                  Pas sur Instagram → libérer
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
              <h2 className={`mb-2 text-xs font-semibold tracking-wide uppercase ${d.date === today ? 'text-accent' : 'text-muted'}`}>
                {dayLabel(d.date)}
              </h2>
              <ul className="space-y-2">
                {d.posts.map((p) => <PostCard key={p.id} post={p} page={page} />)}
              </ul>
            </li>
          ))}
        </ol>
      )}
      {cal?.days.every((d) => !d.posts.length) && (
        <EmptyState title="Rien de programmé cette semaine.">Les vidéos approuvées arrivent ici une fois programmées.</EmptyState>
      )}
    </div>
  )
}

function PostCard({ post: p, page: { act, show, replanned, pick } }: { post: CalendarPost; page: Page }) {
  const moved = p.moved_to
  return (
    <Card as="li" aria-label={`Publication ${p.id}`} className="p-3! text-sm">
      <div className="flex flex-wrap items-center gap-1.5">
        <strong className="tabular-nums">{p.local.slice(11, 16)}</strong>
        <Chip tone={STATUS_TONE[p.status]}>{STATUS_LABEL[p.status]}</Chip>
        {p.replanned && <Chip tone="warn">reprogrammée</Chip>}
      </div>
      {p.caption && <p className="mt-1 line-clamp-3 break-words">{p.caption}</p>}
      {p.error && <p className={`mt-1 text-xs ${p.status === 'failed' ? 'text-danger' : 'text-muted'}`}>{p.error}</p>}
      {moved && (
        <p className="mt-1 text-xs text-muted">
          Reprogrammée →{' '}
          <button type="button" className={`inline-flex min-h-11 items-center ${link}`} onClick={() => show(moved.local)}>
            {slotLabel(moved.local)}
          </button>
        </p>
      )}
      <div className="mt-1 flex flex-wrap gap-x-3 text-xs">
        {p.asset_id !== null && (
          <Link to={`/assets/${p.asset_id}`} className={`inline-flex min-h-11 items-center ${link}`}>Vidéo {p.asset_id}</Link>
        )}
        {p.permalink?.startsWith('https://') && (
          <a href={p.permalink} target="_blank" rel="noreferrer" className={`inline-flex min-h-11 items-center ${link}`}>Sur Instagram</a>
        )}
      </div>
      <div className="mt-2 flex flex-wrap gap-1">
        {p.status === 'pending' && <Button size="sm" onClick={() => pick(p)}>Changer l’heure</Button>}
        {p.status === 'failed' && (
          <Button size="sm" variant="primary" onClick={() => act(async () => replanned(await replan(p.id)))}>
            Reprogrammer
          </Button>
        )}
        {(p.status === 'pending' || p.status === 'failed') && (
          <Button size="sm" variant="ghost" onClick={() => window.confirm('Annuler cette publication ?') && act(() => cancelPost(p.id))}>
            Annuler
          </Button>
        )}
      </div>
    </Card>
  )
}
