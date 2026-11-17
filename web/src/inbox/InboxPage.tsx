import { useEffect, useLayoutEffect, useState } from 'react'
import {
  addFeedback,
  approveAsset,
  getBench,
  listAssets,
  setVerdict,
  getTaxonomy,
  type Asset,
  type Bench,
  type Taxonomy,
  type Verdict,
} from '../api/client'
import AssetCard from './AssetCard'
import ReasonSheet from './ReasonSheet'
import ScheduleSheet from './ScheduleSheet'
import { Button } from '../ui/Button'
import { EmptyState, Skeleton } from '../ui/Card'
import { PageHeader } from '../ui/PageHeader'
import { field } from '../ui/styles'
import { Tabs } from '../ui/Tabs'
import { wallClock } from './ui'

const STATUSES = ['ready', 'needs_reaction', 'revision_requested', 'approved', 'scheduled',
  'published', 'rendering', 'failed', 'archived']
const VERDICTS = [['none', 'Not reviewed'], ['liked', 'Liked'], ['disliked', 'Disliked']]

/** Today in the browser's time zone, YYYY-MM-DD (batches are dated in the owner's day). */
function localToday(d = new Date()) {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

const message = (e: unknown) => (e instanceof Error ? e.message : String(e))
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`
/** "9 liked videos = 3 days at 3 a day" */
const supply = (b: Bench) =>
  `${plural(b.assets.length, 'liked video')} = ${plural(b.supply_days, 'day')} at ${b.max_posts_per_day} a day`
// The banner stays dismissed for the browser session, per suggested video and slot.
const DISMISSED = 'inbox.benchBannerDismissed'
const bannerKey = (s: NonNullable<Bench['suggestion']>) => `${s.asset_id}@${s.publish_at}`

export default function InboxPage() {
  const [date, setDate] = useState(localToday)
  const [filters, setFilters] = useState({ track: '', status: '', verdict: '' })
  const [assets, setAssets] = useState<Asset[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [taxonomy, setTaxonomy] = useState<Taxonomy | null>(null)
  const [sheetFor, setSheetFor] = useState<number | null>(null)
  const [scheduleFor, setScheduleFor] = useState<number | null>(null)
  const [current, setCurrent] = useState(0)
  const [tab, setTab] = useState<'today' | 'bench'>('today')
  const [bench, setBench] = useState<Bench | null>(null)
  const [dismissed, setDismissed] = useState(() => sessionStorage.getItem(DISMISSED))

  useEffect(() => {
    getTaxonomy().then(setTaxonomy, () => {}) // no chips: the sheet still offers Skip
  }, [])

  // The bench feeds the tab count and the banner on both tabs, and the list on the Bench tab.
  useEffect(() => {
    let live = true
    const failed = (what: string) => (e: unknown) =>
      live && setError(`Could not load the ${what} (${message(e)})`)
    getBench().then(
      (b) => {
        if (!live) return
        setBench(b)
        if (tab === 'bench') setAssets(b.assets)
      },
      tab === 'bench' ? failed('bench') : () => {}, // Today still works without the banner
    )
    if (tab === 'today') {
      const query = Object.fromEntries(Object.entries(filters).filter(([, v]) => v))
      listAssets({ batch_date: date, ...query }).then(
        (list) => live && setAssets(list),
        failed('batch'),
      )
    }
    return () => {
      live = false
    }
  }, [date, filters, tab])

  // A new day or filter starts from a blank list (the effect above fetches it).
  function reload() {
    setAssets(null)
    setError(null)
    setCurrent(0)
  }

  const patch = (id: number, fields: Partial<Asset>) =>
    setAssets((list) => list && list.map((a) => (a.id === id ? { ...a, ...fields } : a)))

  // Optimistic: show the verdict at once, roll back if the server refuses it.
  async function verdict(a: Asset, v: Verdict) {
    setError(null)
    patch(a.id, { verdict: v })
    if (v === 'disliked') setSheetFor(a.id)
    try {
      patch(a.id, await setVerdict(a.id, v))
    } catch (e) {
      patch(a.id, { verdict: a.verdict })
      setSheetFor(null)
      setError(`Could not save the verdict (${message(e)})`)
    }
  }

  async function approve(a: Asset) {
    setError(null)
    try {
      patch(a.id, await approveAsset(a.id))
      setScheduleFor(a.id) // scheduling is the second, explicit step
    } catch (e) {
      setError(`Could not approve (${message(e)})`)
    }
  }

  // Desktop shortcuts: j/k move, l like, d dislike, a approve. A layout effect: the listener
  // with the fresh list is attached in the same commit that shows it (a passive effect runs
  // later, so a key pressed right after the batch appears hit the stale, empty list).
  useLayoutEffect(() => {
    function onKey(e: KeyboardEvent) {
      const t = e.target
      if (e.ctrlKey || e.metaKey || e.altKey || sheetFor !== null || scheduleFor !== null || !assets?.length) return
      if (t instanceof HTMLElement && (t.isContentEditable || t.closest('input, textarea, select')))
        return
      const a = assets[current]
      if (e.key === 'j' || e.key === 'k') {
        const next = Math.min(Math.max(current + (e.key === 'j' ? 1 : -1), 0), assets.length - 1)
        setCurrent(next)
        document.getElementById(`asset-${assets[next].id}`)?.scrollIntoView?.({ block: 'center' })
      } else if (e.key === 'l') void verdict(a, 'liked')
      else if (e.key === 'd') void verdict(a, 'disliked')
      else if (e.key === 'a' && a.status === 'ready') void approve(a)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  function showTab(next: typeof tab) {
    if (next === tab) return
    reload()
    setTab(next)
  }

  // The suggestion is the freshest bench video, so a fresh Bench tab starts on it (cursor 0).
  function review(id: number) {
    if (tab !== 'bench') return showTab('bench')
    const i = assets?.findIndex((a) => a.id === id) ?? -1
    if (i < 0) return
    setCurrent(i)
    document.getElementById(`asset-${id}`)?.scrollIntoView?.({ block: 'center' })
  }

  const reviewed = assets?.filter((a) => a.verdict !== 'none').length ?? 0
  const suggestion = bench?.suggestion
  const banner = suggestion && bannerKey(suggestion) !== dismissed ? suggestion : null
  const setFilter = (k: keyof typeof filters) => (e: { target: { value: string } }) => {
    reload()
    setFilters((f) => ({ ...f, [k]: e.target.value }))
  }

  return (
    <section className="mx-auto max-w-md">
      <PageHeader
        title="Inbox"
        actions={assets && tab === 'today' && (
          <p role="status" className="text-sm text-muted tabular-nums">
            {reviewed} of {assets.length} reviewed
          </p>
        )}
      />
      {banner && (
        <div
          role="region"
          aria-label="Bench suggestion"
          className="mb-3 rounded-card border border-warn/30 bg-warn/12 p-4 text-sm"
        >
          <p>
            Free slot at <strong>{wallClock(banner.local)}</strong> and nothing for it yet: the
            freshest video on the bench could take it.
          </p>
          <div className="mt-3 flex gap-2">
            <Button variant="primary" onClick={() => review(banner.asset_id)}>Review it</Button>
            <Button
              variant="ghost"
              onClick={() => {
                sessionStorage.setItem(DISMISSED, bannerKey(banner))
                setDismissed(bannerKey(banner))
              }}
            >
              Dismiss
            </Button>
          </div>
        </div>
      )}
      <Tabs
        label="Inbox view"
        value={tab}
        onChange={showTab}
        tabs={[
          { id: 'today', label: 'Today' },
          { id: 'bench', label: `Bench${bench ? ` (${bench.assets.length})` : ''}` },
        ]}
      />
      {tab === 'bench' && bench && <p className="mt-2 text-sm text-muted">{supply(bench)}</p>}
      {tab === 'today' && (
        <div className="mt-3 grid grid-cols-2 gap-2">
          <input
            type="date"
            aria-label="Batch date"
            value={date}
            onChange={(e) => {
              if (!e.target.value) return
              reload()
              setDate(e.target.value)
            }}
            className={field}
          />
          <select aria-label="Track" value={filters.track} onChange={setFilter('track')} className={field}>
            <option value="">All tracks</option>
            {taxonomy?.tracks?.values.map((t) => (
              <option key={t.id} value={t.id}>{t.label}</option>
            ))}
          </select>
          <select aria-label="Status" value={filters.status} onChange={setFilter('status')} className={field}>
            <option value="">All statuses</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>{s.replace('_', ' ')}</option>
            ))}
          </select>
          <select aria-label="Verdict" value={filters.verdict} onChange={setFilter('verdict')} className={field}>
            <option value="">All verdicts</option>
            {VERDICTS.map(([v, label]) => (
              <option key={v} value={v}>{label}</option>
            ))}
          </select>
        </div>
      )}
      {error && (
        <p role="alert" className="mt-3 rounded-card bg-danger/12 p-3 text-sm text-danger">
          {error}
        </p>
      )}
      {!assets && !error && <Skeleton className="mt-4 aspect-[9/16] max-h-[70dvh]" />}
      {assets?.length === 0 && (
        <div className="mt-4">
          <EmptyState
            title={tab === 'bench' ? 'The bench is empty: no liked videos waiting.' : 'No videos for this day.'}
          />
        </div>
      )}
      <div className="mt-4 space-y-6">
        {assets?.map((a, i) => (
          <AssetCard
            key={a.id}
            asset={a}
            current={i === current}
            showBestBefore={tab === 'bench'}
            onVerdict={(v) => void verdict(a, v)}
            onApprove={() => void approve(a)}
            onSchedule={() => setScheduleFor(a.id)}
            onChange={(next) => patch(a.id, next)}
            onFocus={() => setCurrent(i)}
          />
        ))}
      </div>
      <p className="mt-6 hidden text-xs text-muted md:block">
        Keys: j / k next / previous, l like, d dislike, a approve
      </p>
      {sheetFor !== null && (
        <ReasonSheet
          reasons={taxonomy?.feedback_reasons.values ?? []}
          onClose={() => setSheetFor(null)}
          onSave={async (codes) => {
            await addFeedback(sheetFor, { reason_codes: codes })
            setSheetFor(null)
          }}
        />
      )}
      {scheduleFor !== null && (
        <ScheduleSheet
          assetId={scheduleFor}
          onClose={() => setScheduleFor(null)}
          onScheduled={(next) => {
            patch(next.id, next)
            setScheduleFor(null)
            getBench().then(setBench, () => {}) // the slot is taken: fresh count and banner
          }}
        />
      )}
    </section>
  )
}
