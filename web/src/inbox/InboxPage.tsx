import { useEffect, useState } from 'react'
import {
  addFeedback,
  approveAsset,
  listAssets,
  setVerdict,
  getTaxonomy,
  type Asset,
  type Taxonomy,
  type Verdict,
} from '../api/client'
import AssetCard from './AssetCard'
import ReasonSheet from './ReasonSheet'

const STATUSES = ['ready', 'needs_reaction', 'revision_requested', 'approved', 'scheduled',
  'published', 'rendering', 'failed', 'archived']
const VERDICTS = [['none', 'Not reviewed'], ['liked', 'Liked'], ['disliked', 'Disliked']]

/** Today in the browser's time zone, YYYY-MM-DD (batches are dated in the owner's day). */
function localToday(d = new Date()) {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

const message = (e: unknown) => (e instanceof Error ? e.message : String(e))
const select = 'min-h-11 rounded-lg border border-gray-300 bg-white px-2 text-sm'

export default function InboxPage() {
  const [date, setDate] = useState(localToday)
  const [filters, setFilters] = useState({ track: '', status: '', verdict: '' })
  const [assets, setAssets] = useState<Asset[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [taxonomy, setTaxonomy] = useState<Taxonomy | null>(null)
  const [sheetFor, setSheetFor] = useState<number | null>(null)
  const [current, setCurrent] = useState(0)

  useEffect(() => {
    getTaxonomy().then(setTaxonomy, () => {}) // no chips: the sheet still offers Skip
  }, [])

  useEffect(() => {
    let live = true
    const query = Object.fromEntries(Object.entries(filters).filter(([, v]) => v))
    listAssets({ batch_date: date, ...query }).then(
      (list) => live && setAssets(list),
      (e: unknown) => live && setError(`Could not load the batch (${message(e)})`),
    )
    return () => {
      live = false
    }
  }, [date, filters])

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
    } catch (e) {
      setError(`Could not approve (${message(e)})`)
    }
  }

  // Desktop shortcuts: j/k move, l like, d dislike, a approve.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const t = e.target
      if (e.ctrlKey || e.metaKey || e.altKey || sheetFor !== null || !assets?.length) return
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

  const reviewed = assets?.filter((a) => a.verdict !== 'none').length ?? 0
  const setFilter = (k: keyof typeof filters) => (e: { target: { value: string } }) => {
    reload()
    setFilters((f) => ({ ...f, [k]: e.target.value }))
  }

  return (
    <section className="mx-auto max-w-md">
      <div className="flex items-baseline justify-between">
        <h2 className="text-2xl font-semibold">Inbox</h2>
        {assets && (
          <p role="status" className="text-sm text-gray-600">
            {reviewed} of {assets.length} reviewed
          </p>
        )}
      </div>
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
          className={select}
        />
        <select aria-label="Track" value={filters.track} onChange={setFilter('track')} className={select}>
          <option value="">All tracks</option>
          {taxonomy?.tracks?.values.map((t) => (
            <option key={t.id} value={t.id}>{t.label}</option>
          ))}
        </select>
        <select aria-label="Status" value={filters.status} onChange={setFilter('status')} className={select}>
          <option value="">All statuses</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>{s.replace('_', ' ')}</option>
          ))}
        </select>
        <select aria-label="Verdict" value={filters.verdict} onChange={setFilter('verdict')} className={select}>
          <option value="">All verdicts</option>
          {VERDICTS.map(([v, label]) => (
            <option key={v} value={v}>{label}</option>
          ))}
        </select>
      </div>
      {error && (
        <p role="alert" className="mt-3 rounded-lg bg-red-50 p-3 text-sm text-red-800">
          {error}
        </p>
      )}
      {!assets && !error && <p className="mt-6 text-gray-500">Loading…</p>}
      {assets?.length === 0 && <p className="mt-6 text-gray-500">No videos for this day.</p>}
      <div className="mt-4 space-y-6">
        {assets?.map((a, i) => (
          <AssetCard
            key={a.id}
            asset={a}
            current={i === current}
            onVerdict={(v) => void verdict(a, v)}
            onApprove={() => void approve(a)}
            onFocus={() => setCurrent(i)}
          />
        ))}
      </div>
      <p className="mt-6 hidden text-xs text-gray-400 md:block">
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
    </section>
  )
}
