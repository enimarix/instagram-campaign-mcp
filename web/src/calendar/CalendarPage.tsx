import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router'
import {
  ApiError,
  cancelPost,
  errorMessage,
  getCalendar,
  releaseAsset,
  replanPost,
  reschedulePost,
  type Calendar,
  type CalendarPost,
} from '../api/client'
import { button, chip, inputValue, localDate } from '../inbox/ui'

const STATUS_COLOR: Record<CalendarPost['status'], string> = {
  pending: 'bg-blue-100 text-blue-800',
  publishing: 'bg-amber-100 text-amber-800',
  published: 'bg-green-100 text-green-800',
  failed: 'bg-red-100 text-red-800',
  cancelled: 'bg-gray-100 text-gray-600',
}
const RELEASE_CONFIRM = 'I checked: it is not on Instagram. Release this video so it can be queued again?'
const RIGHTS_CONFIRM =
  'I checked this reaction video: my own take is a substantial part and the creator is credited.'

const addDays = (d: Date, n: number) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n)
const monday = (d: Date) => addDays(d, -((d.getDay() + 6) % 7))
const dayLabel = (iso: string) =>
  new Date(`${iso}T00:00`).toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' })

type Act = (fn: () => Promise<unknown>) => Promise<boolean>

/** A failed row gets a new slot; a commentary clip asks the owner's check first (GOAL §5.1). */
async function replan(id: number) {
  try {
    await replanPost(id)
  } catch (e) {
    if (!(e instanceof ApiError && e.code === 'rights' && window.confirm(`${errorMessage(e)}\n\n${RIGHTS_CONFIRM}`)))
      throw e
    await replanPost(id, true)
  }
}

// The publish queue by week (GOAL §3.3): a 7-column week on md and up, a list of the
// days that have posts on a phone.
export default function CalendarPage() {
  const [week, setWeek] = useState(() => monday(new Date()))
  const [cal, setCal] = useState<Calendar | null>(null)
  const [error, setError] = useState<string | null>(null)

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
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="mr-auto text-lg font-semibold">Calendar</h2>
        <button type="button" onClick={() => setWeek(addDays(week, -7))} className={`${button} bg-gray-100`}>
          Previous week
        </button>
        <button type="button" onClick={() => setWeek(monday(new Date()))} className={`${button} bg-gray-100`}>
          This week
        </button>
        <button type="button" onClick={() => setWeek(addDays(week, 7))} className={`${button} bg-gray-100`}>
          Next week
        </button>
      </div>
      {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
      {cal && cal.publish_check.length > 0 && (
        <section aria-labelledby="check-title" className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm">
          <h3 id="check-title" className="font-semibold">Did these reach Instagram?</h3>
          <p className="mt-1">
            The publish may have gone through. The worker looks for them on the account; if a video is
            not there, release it so it can be queued again.
          </p>
          <ul className="mt-2 space-y-2">
            {cal.publish_check.map((a) => (
              <li key={a.id} aria-label={`Video ${a.id}`} className="flex flex-wrap items-center gap-2">
                <Link to={`/assets/${a.id}`} className="font-medium text-blue-700 underline">Video {a.id}</Link>
                <span className="min-w-0 flex-1 truncate">{a.caption}</span>
                <button type="button" className={`${button} bg-white`}
                  onClick={() => window.confirm(RELEASE_CONFIRM) && act(() => releaseAsset(a.id))}>
                  Not on Instagram → release
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
      {cal && (
        <ol className="grid gap-3 md:grid-cols-7 md:gap-2">
          {cal.days.map((d) => (
            <li key={d.date} aria-label={d.date} className={d.posts.length ? '' : 'hidden md:block'}>
              <h3 className={`mb-1 text-sm font-semibold ${d.date === today ? 'text-blue-700' : 'text-gray-700'}`}>
                {dayLabel(d.date)}
              </h3>
              <ul className="space-y-2">
                {d.posts.map((p) => <PostCard key={p.id} post={p} act={act} />)}
              </ul>
            </li>
          ))}
        </ol>
      )}
      {cal?.days.every((d) => !d.posts.length) && <p className="text-sm text-gray-600">Nothing queued this week.</p>}
    </div>
  )
}

function PostCard({ post: p, act }: { post: CalendarPost; act: Act }) {
  const [when, setWhen] = useState<string | null>(null) // set while picking a new time

  return (
    <li aria-label={`Post ${p.id}`} className="rounded-lg border border-gray-200 bg-white p-2 text-sm">
      <div className="flex flex-wrap items-center gap-1">
        <strong>{p.local.slice(11, 16)}</strong>
        <span className={`${chip} ${STATUS_COLOR[p.status]}`}>{p.status}</span>
        {p.replanned && <span className={`${chip} bg-amber-100 text-amber-800`}>re-planned</span>}
      </div>
      {p.caption && <p className="mt-1 line-clamp-3 break-words">{p.caption}</p>}
      {p.error && <p className={`mt-1 text-xs ${p.status === 'failed' ? 'text-red-700' : 'text-gray-600'}`}>{p.error}</p>}
      <div className="mt-1 flex flex-wrap gap-x-2 text-xs">
        {p.asset_id !== null && (
          <Link to={`/assets/${p.asset_id}`} className="text-blue-700 underline">Video {p.asset_id}</Link>
        )}
        {p.permalink?.startsWith('https://') && (
          <a href={p.permalink} target="_blank" rel="noreferrer" className="text-blue-700 underline">On Instagram</a>
        )}
      </div>
      {when !== null && (
        <label className="mt-2 block text-xs font-medium">
          New time
          <input type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)}
            className="mt-1 block min-h-11 w-full rounded-lg border border-gray-300 px-1 font-normal" />
        </label>
      )}
      <div className="mt-2 flex flex-wrap gap-1">
        {p.status === 'pending' && (when === null ? (
          <button type="button" onClick={() => setWhen(inputValue(new Date(p.publish_at)))} className={`${button} bg-gray-100`}>
            Reschedule
          </button>
        ) : (
          <button type="button" disabled={!when} className={`${button} bg-blue-600 text-white`}
            onClick={() => act(() => reschedulePost(p.id, new Date(when).toISOString())).then((ok) => ok && setWhen(null))}>
            Save
          </button>
        ))}
        {p.status === 'failed' && (
          <button type="button" onClick={() => act(() => replan(p.id))} className={`${button} bg-blue-600 text-white`}>
            Re-plan
          </button>
        )}
        {(p.status === 'pending' || p.status === 'failed') && (
          <button type="button" onClick={() => window.confirm('Cancel this post?') && act(() => cancelPost(p.id))}
            className={`${button} bg-gray-100`}>
            Cancel
          </button>
        )}
      </div>
    </li>
  )
}
