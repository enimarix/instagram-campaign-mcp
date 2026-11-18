import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router'
import {
  addFeedback,
  approveAndQueue,
  declineAsset,
  errorMessage,
  getBench,
  getProposedSlot,
  getTaxonomy,
  listAssets,
  setVerdict,
  type Asset,
  type Bench,
  type CommentIn,
  type Taxonomy,
} from '../api/client'
import AssetCard from './AssetCard'
import ReasonSheet from './ReasonSheet'
import { Button } from '../ui/Button'
import { EmptyState, Skeleton } from '../ui/Card'
import { Chip } from '../ui/Chip'
import { Sheet } from '../ui/Sheet'
import { buttonClass, field } from '../ui/styles'
import { Tabs } from '../ui/Tabs'
import { useToast } from '../ui/useToast'
import { COMMENTARY_CONFIRMATION, localDate, wallClock } from './ui'

const UNDO_MS = 5000 // the Toast's own lifetime
const VISIBLE = 0.6 // share of a card on screen before it counts as the current one
type Tab = 'today' | 'bench'
/** Still waiting for the owner's decision: these make the feed. Today: not judged yet; the
 * bench ("Saved"): saved for later (liked), waiting for a slot. */
const open = (a: Asset, tab: Tab) => a.status === 'ready' && a.verdict === (tab === 'bench' ? 'liked' : 'none')
const NOT_YET = new Set(['rendering', 'failed', 'needs_reaction']) // nothing to decide yet

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`
/** "9 saved videos = 3 days at 3 a day" */
const supply = (b: Bench) =>
  `${plural(b.assets.length, 'saved video')} = ${plural(b.supply_days, 'day')} at ${b.max_posts_per_day} a day`
// The banner stays dismissed for the browser session, per suggested video and slot.
const DISMISSED = 'inbox.benchBannerDismissed'
const bannerKey = (s: NonNullable<Bench['suggestion']>) => `${s.asset_id}@${s.publish_at}`
const videoOf = (a?: Asset) => (a ? document.querySelector<HTMLVideoElement>(`#asset-${a.id} video`) : null)

type Pending = { timer: ReturnType<typeof setTimeout>; run: () => void }

// The review feed (GOAL.md §3.2 "Scroll and decide"): one video per screen, decided with
// one tap. Rule for all three decisions (approve, decline, change): the card leaves the
// feed at once (the next video takes its place) and the API calls fire when the 5 s undo
// window closes, or at once when the page is hidden or left. `archived` is final and a
// revision request cannot be taken back, so nothing is sent before the window closes;
// approve follows the same rule to keep one path.
export default function InboxPage() {
  const [date, setDate] = useState(() => localDate(new Date()))
  const [assets, setAssets] = useState<Asset[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [taxonomy, setTaxonomy] = useState<Taxonomy | null>(null)
  const [current, setCurrent] = useState(0)
  const [muted, setMuted] = useState(true)
  const [tab, setTab] = useState<Tab>('today')
  const [bench, setBench] = useState<Bench | null>(null)
  const [dismissed, setDismissed] = useState(() => sessionStorage.getItem(DISMISSED))
  const [changeFor, setChangeFor] = useState<{ asset: Asset; at: number } | null>(null)
  const [confirmFor, setConfirmFor] = useState<Asset | null>(null)
  const [why, setWhy] = useState<{ id: number; codes: string[] } | null>(null) // decline reasons
  const pending = useRef(new Map<number, Pending>())
  const inflight = useRef<Promise<unknown>>(Promise.resolve()) // committed decisions still saving
  const declineCodes = useRef(new Map<number, string[]>())
  const scroller = useRef<HTMLDivElement>(null)
  const toast = useToast()
  const navigate = useNavigate()

  useEffect(() => {
    getTaxonomy().then(setTaxonomy, () => {}) // no chips: decline and change still work
  }, [])

  // The bench feeds the tab count and the banner on both tabs, and the feed on the Bench tab.
  useEffect(() => {
    let live = true
    const failed = (what: string) => (e: unknown) =>
      live && setError(`Could not load the ${what} (${errorMessage(e)})`)
    // After the decisions still saving (a tab or day switch flushes them): a video saved
    // for later a moment ago is then on the bench.
    const settled = inflight.current
    settled.then(() => getBench()).then(
      (b) => {
        if (!live) return
        setBench(b)
        if (tab === 'bench') setAssets(b.assets)
      },
      tab === 'bench' ? failed('saved videos') : () => {}, // Today still works without the banner
    )
    if (tab === 'today')
      settled.then(() => listAssets({ batch_date: date })).then((list) => live && setAssets(list), failed('batch'))
    return () => {
      live = false
    }
  }, [date, tab])

  const flush = () => pending.current.forEach((p) => p.run())
  useEffect(() => {
    const hidden = () => document.visibilityState === 'hidden' && flush()
    document.addEventListener('visibilitychange', hidden)
    window.addEventListener('pagehide', flush)
    return () => {
      document.removeEventListener('visibilitychange', hidden)
      window.removeEventListener('pagehide', flush)
      flush() // leaving the Inbox commits what is still waiting
    }
  }, [])

  const feed = assets?.filter((a) => open(a, tab)) ?? []
  const cur = Math.min(current, Math.max(feed.length - 1, 0))
  const feedKey = feed.map((a) => a.id).join()

  // The card mostly on screen is the current one (it plays; keys act on it).
  useEffect(() => {
    const root = scroller.current
    if (!root || typeof IntersectionObserver === 'undefined') return
    const io = new IntersectionObserver((entries) => {
      for (const e of entries)
        if (e.isIntersecting && e.intersectionRatio >= VISIBLE)
          setCurrent(Number((e.target as HTMLElement).dataset.index))
    }, { root, threshold: VISIBLE })
    root.querySelectorAll('article').forEach((el) => io.observe(el))
    return () => io.disconnect()
  }, [feedKey])

  // A new day or tab starts from a blank feed (the effect above fetches it).
  function reload() {
    flush()
    setAssets(null)
    setError(null)
    setCurrent(0)
  }

  const patch = (id: number, fields: Partial<Asset>) =>
    setAssets((list) => list && list.map((a) => (a.id === id ? { ...a, ...fields } : a)))
  const forget = (id: number) => {
    pending.current.delete(id)
    declineCodes.current.delete(id)
    setWhy((w) => (w?.id === id ? null : w))
  }

  function decide(a: Asset, as: Partial<Asset>, message: string, commit: () => Promise<void>) {
    if (pending.current.has(a.id)) return
    setError(null)
    patch(a.id, as) // out of the feed
    const run = () => {
      clearTimeout(timer)
      const saving = commit()
        .catch((e: unknown) => {
          patch(a.id, a) // back in the feed
          setError(`Could not save video ${a.id} (${errorMessage(e)})`)
        })
        .finally(() => getBench().then(setBench, () => {}))
      inflight.current = Promise.all([inflight.current, saving])
      forget(a.id) // after commit() started: decline reads its reasons synchronously
    }
    const timer = setTimeout(run, UNDO_MS)
    pending.current.set(a.id, { timer, run })
    toast({ message, action: { label: 'Undo', onClick: () => undo(a) } })
  }

  function undo(a: Asset) {
    const p = pending.current.get(a.id)
    if (!p) return
    clearTimeout(p.timer)
    forget(a.id)
    patch(a.id, a)
  }

  // A commentary clip needs the owner's confirmation first (GOAL.md §5.1); the planner's
  // proposed slot says whether it does.
  async function approve(a: Asset) {
    const slot = await getProposedSlot(a.id).catch(() => null)
    if (slot?.needs_confirmation) setConfirmFor(a)
    else approveNow(a, false)
  }

  function approveNow(a: Asset, confirmed: boolean) {
    decide(a, { status: 'approved' }, 'Approved', async () => {
      const r = await approveAndQueue(a.id, confirmed)
      patch(a.id, r.asset)
      if (!r.slot)
        toast({
          message: 'Approved, no free slot: set one in Calendar',
          action: { label: 'Calendar', onClick: () => navigate('/calendar') },
        })
    })
  }

  function decline(a: Asset) {
    decide(a, { status: 'archived', verdict: 'disliked' }, 'Declined', async () => {
      patch(a.id, await declineAsset(a.id, declineCodes.current.get(a.id) ?? []))
    })
    setWhy({ id: a.id, codes: [] })
  }

  // Not now, but good: onto the bench ("Saved"), for a free slot later.
  function save(a: Asset) {
    decide(a, { verdict: 'liked' }, 'Saved for later', async () => patch(a.id, await setVerdict(a.id, 'liked')))
  }

  function toggleWhy(code: string) {
    if (!why) return
    const codes = why.codes.includes(code) ? why.codes.filter((c) => c !== code) : [...why.codes, code]
    declineCodes.current.set(why.id, codes)
    setWhy({ id: why.id, codes })
  }

  function change(a: Asset, fb: CommentIn) {
    setChangeFor(null)
    decide(a, { status: 'revision_requested' }, 'Sent for changes', async () => {
      const r = await addFeedback(a.id, fb)
      patch(a.id, r.asset)
      if (!r.moved) throw new Error(`saved, but not sent back: ${r.reason}`)
    })
  }

  const openChange = (a: Asset) => setChangeFor({ asset: a, at: videoOf(a)?.currentTime ?? 0 })

  function go(i: number) {
    const next = Math.min(Math.max(i, 0), feed.length - 1)
    setCurrent(next)
    // Smooth unless the owner prefers reduced motion (index.css turns scroll-smooth off).
    document.getElementById(`asset-${feed[next].id}`)?.scrollIntoView?.({ block: 'start' })
  }

  // Desktop keys. A layout effect: the listener with the fresh feed is attached in the same
  // commit that shows it (a passive effect runs later: a quick key hit the stale list).
  useLayoutEffect(() => {
    function onKey(e: KeyboardEvent) {
      const t = e.target
      if (e.ctrlKey || e.metaKey || e.altKey || changeFor || confirmFor || !feed.length) return
      if (t instanceof HTMLElement && (t.isContentEditable || t.closest('input, textarea, select')))
        return
      const a = feed[cur]
      const key = e.key.length === 1 ? e.key.toLowerCase() : e.key
      if (key === ' ') {
        if (t instanceof HTMLElement && t.closest('button, a')) return // Space presses it
        e.preventDefault()
        const v = videoOf(a)
        if (v?.paused) v.play()?.catch(() => {})
        else v?.pause()
        return
      }
      const act: Record<string, () => void> = {
        a: () => void approve(a),
        d: () => decline(a),
        c: () => openChange(a),
        ...(tab === 'today' && { s: () => save(a) }),
        m: () => setMuted((m) => !m),
        j: () => go(cur + 1),
        ArrowDown: () => go(cur + 1),
        k: () => go(cur - 1),
        ArrowUp: () => go(cur - 1),
      }
      if (!act[key]) return
      e.preventDefault()
      act[key]()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  function showTab(next: typeof tab) {
    if (next === tab) return
    reload()
    setTab(next)
  }

  // The suggestion is the freshest bench video, so a fresh Bench tab starts on it.
  function review(id: number) {
    if (tab !== 'bench') return showTab('bench')
    const i = feed.findIndex((a) => a.id === id)
    if (i >= 0) go(i)
  }

  const decided = assets?.filter((a) => !open(a, tab) && !NOT_YET.has(a.status)).length ?? 0
  const suggestion = bench?.suggestion
  const banner = suggestion && bannerKey(suggestion) !== dismissed ? suggestion : null

  return (
    <section aria-labelledby="inbox-title"
      className="-mx-4 -mt-4 -mb-8 flex h-[calc(100dvh-6.5rem-env(safe-area-inset-top)-env(safe-area-inset-bottom))] flex-col lg:m-0 lg:h-[calc(100dvh-6rem)]">
      <header className="shrink-0 space-y-2 px-4 pt-3 pb-2 lg:px-0 lg:pt-0">
        <h1 id="inbox-title" className="sr-only">Inbox</h1>
        <div className="mx-auto flex max-w-md items-center gap-2">
          <div className="flex-1">
            <Tabs label="Inbox view" value={tab} onChange={showTab} tabs={[
              { id: 'today', label: 'Today' },
              { id: 'bench', label: `Saved${bench ? ` (${bench.assets.length})` : ''}` },
            ]} />
          </div>
          {tab === 'today' && (
            <input type="date" aria-label="Batch date" value={date} className={`${field} w-36`}
              onChange={(e) => {
                if (!e.target.value) return
                reload()
                setDate(e.target.value)
              }} />
          )}
        </div>
        <p role="status" className="mx-auto max-w-md text-sm text-muted tabular-nums">
          {tab === 'bench' ? bench && supply(bench) : assets && `${decided} of ${decided + feed.length} decided`}
        </p>
        {banner && (
          <div role="region" aria-label="Saved video suggestion"
            className="mx-auto flex max-w-md flex-wrap items-center gap-2 rounded-card border border-warn/30 bg-warn/12 p-3 text-sm">
            <p className="flex-1">
              Free slot <strong>{wallClock(banner.local)}</strong>: your freshest saved video could take it.
            </p>
            <Button size="sm" variant="primary" onClick={() => review(banner.asset_id)}>Review it</Button>
            <Button size="sm" variant="ghost" onClick={() => {
              sessionStorage.setItem(DISMISSED, bannerKey(banner))
              setDismissed(bannerKey(banner))
            }}>
              Dismiss
            </Button>
          </div>
        )}
        {error && (
          <p role="alert" className="mx-auto max-w-md rounded-card bg-danger/12 p-3 text-sm text-danger">{error}</p>
        )}
      </header>

      {!assets && !error && <Skeleton className="mx-auto aspect-[9/16] w-full max-w-md flex-1" />}
      {assets && !feed.length && (
        <div className="px-4 pt-4">
          {assets.length ? (
            <EmptyState title="All done" action={
              <Link to="/calendar" className={buttonClass('primary')}>Open the Calendar</Link>}>
              Every video {tab === 'bench' ? 'you saved' : 'of this batch'} has a decision.
            </EmptyState>
          ) : (
            <EmptyState title={tab === 'bench' ? 'Nothing saved for later.' : 'No videos for this day.'} />
          )}
        </div>
      )}
      {feed.length > 0 && (
        <div ref={scroller} aria-label="Review feed"
          className="min-h-0 flex-1 snap-y snap-mandatory overflow-y-auto overscroll-contain scroll-smooth">
          {feed.map((a, i) => (
            <AssetCard
              key={a.id}
              asset={a}
              index={i}
              active={i === cur}
              preload={i === cur + 1}
              muted={muted}
              showBestBefore={tab === 'bench'}
              onToggleSound={() => setMuted((m) => !m)}
              onApprove={() => void approve(a)}
              onDecline={() => decline(a)}
              onChange={() => openChange(a)}
              onSave={tab === 'today' ? () => save(a) : undefined}
            />
          ))}
        </div>
      )}
      <p className="mt-2 hidden text-center text-xs text-muted lg:block">
        Keys: a approve, d decline, c change{tab === 'today' && ', s save for later'}, j / k next / previous, space play / pause, m sound
      </p>

      {why && taxonomy && (
        <div role="group" aria-label="Why decline? (optional)"
          className="fixed inset-x-0 bottom-[calc(9rem+env(safe-area-inset-bottom))] z-50 flex justify-center px-4 lg:bottom-24">
          <div className="flex w-full max-w-sm gap-2 overflow-x-auto rounded-card border border-line bg-surface-2 p-2 shadow-overlay">
            <span aria-hidden className="shrink-0 self-center pl-2 text-sm text-muted">Why?</span>
            {taxonomy.feedback_reasons.values.map((r) => (
              <Chip key={r.id} tone="danger" pressed={why.codes.includes(r.id)} onClick={() => toggleWhy(r.id)}
                className="shrink-0">
                {r.label}
              </Chip>
            ))}
          </div>
        </div>
      )}
      {changeFor && (
        <ReasonSheet
          reasons={taxonomy?.feedback_reasons.values ?? []}
          at={changeFor.at}
          onClose={() => setChangeFor(null)}
          onSave={(fb) => change(changeFor.asset, fb)}
        />
      )}
      {confirmFor && (
        <ConfirmSheet
          onClose={() => setConfirmFor(null)}
          onConfirm={() => {
            setConfirmFor(null)
            approveNow(confirmFor, true)
          }}
        />
      )}
    </section>
  )
}

/** Approving a commentary (reaction) video: the owner's per-video rights confirmation. */
function ConfirmSheet({ onConfirm, onClose }: { onConfirm: () => void; onClose: () => void }) {
  const [checked, setChecked] = useState(false)
  return (
    <Sheet title="Approve this reaction video?" onClose={onClose}>
      <label className="mt-3 flex items-start gap-2 text-sm">
        <input type="checkbox" checked={checked} onChange={(e) => setChecked(e.target.checked)}
          className="mt-0.5 size-5" />
        {COMMENTARY_CONFIRMATION}
      </label>
      <div className="mt-5 grid grid-cols-2 gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={!checked} onClick={onConfirm}>Approve</Button>
      </div>
    </Sheet>
  )
}
