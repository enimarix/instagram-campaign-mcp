import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { Link, useParams } from 'react-router'
import {
  approveAsset,
  archiveAsset,
  editAsset,
  errorMessage,
  getAsset,
  getAssetContext,
  getTaxonomy,
  setVerdict,
  unapproveAsset,
  type Asset,
  type AssetContext,
  type Taxonomy,
} from '../api/client'
import CommentThread from './CommentThread'
import { button, chip } from './ui'

/** Only http(s) links are rendered: agent-written URLs could carry `javascript:`. */
const safeUrl = (url?: string | null) => (url && /^https?:\/\//i.test(url) ? url : null)

function ExternalLink({ url, children }: { url?: string | null; children: ReactNode }) {
  const href = safeUrl(url)
  if (!href) return <>{children}</>
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" className="text-blue-700 underline">
      {children}
    </a>
  )
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  if (children == null || children === '') return null
  return (
    <div>
      <dt className="text-xs font-medium text-gray-500">{label}</dt>
      <dd className="text-sm">{children}</dd>
    </div>
  )
}

function recipeSummary(r: Asset['recipe']) {
  if (r?.ops?.length) return r.ops.map((o) => o.op).join(' → ')
  return r?.template ?? r?.edit ?? null
}

// Keyed by id: a version link starts the page afresh instead of resetting state.
export default function AssetRoute() {
  const { id } = useParams()
  return <AssetPage key={id} id={Number(id)} />
}

// One asset: player, actions, caption, comments and what the agent based it on.
function AssetPage({ id }: { id: number }) {
  const video = useRef<HTMLVideoElement>(null)
  const [asset, setAsset] = useState<Asset | null>(null)
  const [ctx, setCtx] = useState<AssetContext | null>(null)
  const [taxonomy, setTaxonomy] = useState<Taxonomy | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [caption, setCaption] = useState('')
  const [bestBefore, setBestBefore] = useState('')
  const [saveMsg, setSaveMsg] = useState<string | null>(null)

  useEffect(() => {
    getTaxonomy().then(setTaxonomy, () => {}) // no labels: ids are shown instead
  }, [])

  useEffect(() => {
    let live = true
    Promise.all([getAsset(id), getAssetContext(id)]).then(
      ([a, c]) => {
        if (!live) return
        setAsset(a)
        setCtx(c)
        setCaption(a.caption ?? '')
        setBestBefore(a.best_before ?? '')
      },
      (e: unknown) => live && setError(`Could not load this video (${errorMessage(e)})`),
    )
    return () => {
      live = false
    }
  }, [id])

  async function act(fn: () => Promise<Asset>) {
    setError(null)
    try {
      setAsset(await fn())
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  async function save(e: FormEvent) {
    e.preventDefault()
    setSaveMsg(null)
    try {
      setAsset(await editAsset(id, { caption, best_before: bestBefore || null }))
      setSaveMsg('Saved.')
    } catch (err) {
      setSaveMsg(`Not saved: ${errorMessage(err)}`)
    }
  }

  function seek(t: number) {
    const v = video.current
    if (!v) return
    v.currentTime = t
    v.play().catch(() => {})
  }

  const label = (kind: keyof Taxonomy, value: string | null) =>
    value && (taxonomy?.[kind]?.values.find((v) => v.id === value)?.label ?? value)

  if (!asset || !ctx)
    return <p role={error ? 'alert' : 'status'}>{error ?? 'Loading…'}</p>

  const { idea, source } = ctx
  const qcReasons = asset.qc?.reasons ?? (asset.qc?.reason ? [asset.qc.reason] : [])

  return (
    <div className="mx-auto grid max-w-5xl gap-4 md:grid-cols-[minmax(0,22rem)_1fr]">
      <section className="space-y-3">
        <Link to="/inbox" className="text-sm text-blue-700 underline">← Inbox</Link>
        <video
          ref={video}
          src={asset.preview_url ?? undefined}
          poster={asset.thumbnail_url ?? undefined}
          controls
          playsInline
          preload="metadata"
          className="aspect-[9/16] max-h-[70dvh] w-full rounded-xl bg-black object-contain"
        />
        <div className="flex flex-wrap gap-1">
          <span className={`${chip} bg-gray-100 text-gray-700`}>{asset.status.replace('_', ' ')}</span>
          {asset.verdict !== 'none' && (
            <span className={`${chip} bg-gray-100 text-gray-700`}>{asset.verdict}</span>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" aria-pressed={asset.verdict === 'disliked'}
            onClick={() => act(() => setVerdict(id, 'disliked'))} className={`${button} bg-red-50 text-red-800`}>
            Dislike
          </button>
          <button type="button" aria-pressed={asset.verdict === 'liked'}
            onClick={() => act(() => setVerdict(id, 'liked'))} className={`${button} bg-green-50 text-green-800`}>
            Like
          </button>
          {asset.status === 'ready' && (
            <>
              <button type="button" onClick={() => act(() => approveAsset(id))} className={`${button} bg-blue-600 text-white`}>
                Approve
              </button>
              <button type="button" onClick={() => act(() => archiveAsset(id))} className={`${button} bg-gray-100`}>
                Archive
              </button>
            </>
          )}
          {asset.status === 'approved' && (
            <button type="button" onClick={() => act(() => unapproveAsset(id))} className={`${button} bg-gray-100`}>
              Unapprove
            </button>
          )}
        </div>
        {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
        <form onSubmit={save} className="space-y-2">
          <label className="block text-sm font-medium">
            Caption
            <textarea value={caption} onChange={(e) => setCaption(e.target.value)} rows={4}
              className="mt-1 block w-full rounded-lg border border-gray-300 p-2 font-normal" />
          </label>
          <label className="block text-sm font-medium">
            Best before
            <input type="date" value={bestBefore} onChange={(e) => setBestBefore(e.target.value)}
              className="mt-1 block min-h-11 rounded-lg border border-gray-300 px-2 font-normal" />
          </label>
          <button type="submit" className={`${button} bg-blue-600 text-white`}>Save</button>
          {saveMsg && <p role="status" className="text-sm">{saveMsg}</p>}
        </form>
      </section>

      <div className="space-y-4">
        <section aria-label="About this video" className="rounded-xl bg-white p-3 shadow-sm">
          <dl className="space-y-2">
            <Row label="Hook">{idea.hook}</Row>
            <Row label="Hook type">{label('hook_types', idea.hook_type)}</Row>
            <Row label="Hypothesis">{idea.hypothesis}</Row>
            <Row label="Track">
              {label('tracks', idea.track)}
              {idea.strategy === 'explore' && (
                <span className={`${chip} ml-2 bg-purple-100 text-purple-800`}>Explore</span>
              )}
            </Row>
            <Row label="Pillar">{label('pillars', idea.pillar)}</Row>
            <Row label="Recipe">{recipeSummary(asset.recipe)}</Row>
            {source && (
              <Row label="Rights">
                {source.rights_basis.replace('_', ' ')}
                {source.author && (
                  <> · credit: <ExternalLink url={source.url}>{source.author}</ExternalLink></>
                )}
              </Row>
            )}
            {idea.citations.length > 0 && (
              <Row label="Sources (check before approving)">
                <ul className="list-disc pl-5">
                  {idea.citations.map((c, i) => (
                    <li key={i}><ExternalLink url={c.url}>{c.title || c.url}</ExternalLink></li>
                  ))}
                </ul>
              </Row>
            )}
            {asset.qc && (
              <Row label="Quality check">
                {asset.qc.passed ? 'Passed' : 'Failed'}
                {qcReasons.length > 0 && `: ${qcReasons.join('; ')}`}
              </Row>
            )}
          </dl>
          {(ctx.parent || ctx.children.length > 0) && (
            <nav aria-label="Versions" className="mt-3 flex flex-wrap gap-3 text-sm">
              {ctx.parent && (
                <Link to={`/assets/${ctx.parent.id}`} className="text-blue-700 underline">Older version</Link>
              )}
              {ctx.children.map((c) => (
                <Link key={c.id} to={`/assets/${c.id}`} className="text-blue-700 underline">
                  Newer version #{c.id} ({c.status.replace('_', ' ')})
                </Link>
              ))}
            </nav>
          )}
        </section>
        <CommentThread assetId={id} onSeek={seek} currentTime={() => video.current?.currentTime ?? 0}
          reasons={taxonomy?.feedback_reasons.values ?? []} onAsset={setAsset} />
      </div>
    </div>
  )
}
