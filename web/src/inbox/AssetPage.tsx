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
import ReactionCards from './ReactionCards'
import ScheduleSheet, { ScheduledSlot } from './ScheduleSheet'
import { Button } from '../ui/Button'
import { Card, Skeleton } from '../ui/Card'
import { Chip } from '../ui/Chip'
import { PageHeader } from '../ui/PageHeader'
import { field, link, verdictButton } from '../ui/styles'
import { AI_LABEL_LINE, safeUrl } from './ui'
import { VoiceBadge } from '../voices/VoiceBadge'

function ExternalLink({ url, children }: { url?: string | null; children: ReactNode }) {
  const href = safeUrl(url)
  if (!href) return <>{children}</>
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" className={`${link} inline-flex min-h-11 items-center`}>
      {children}
    </a>
  )
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  if (children == null || children === '') return null
  return (
    <div>
      <dt className="text-xs font-medium text-muted">{label}</dt>
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
  const [scheduling, setScheduling] = useState(false)

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
      return true
    } catch (e) {
      setError(errorMessage(e))
      return false
    }
  }

  async function approve() {
    // UI-002: a typed caption not saved yet goes first (a scheduled video refuses caption edits).
    if (caption !== (asset?.caption ?? '') && !(await act(() => editAsset(id, { caption })))) return
    if (await act(() => approveAsset(id))) setScheduling(true) // then the explicit second step
  }

  async function save(e: FormEvent) {
    e.preventDefault()
    setSaveMsg(null)
    try {
      // Only what changed: a scheduled asset refuses caption edits but not a best-before.
      const fields = {
        ...(caption !== (asset?.caption ?? '') && { caption }),
        ...(bestBefore !== (asset?.best_before ?? '') && { best_before: bestBefore || null }),
      }
      if (Object.keys(fields).length) setAsset(await editAsset(id, fields))
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
    return error ? <p role="alert" className="text-danger">{error}</p> : <Skeleton className="h-96" />

  const { idea, source } = ctx
  const qcReasons = asset.qc?.reasons ?? (asset.qc?.reason ? [asset.qc.reason] : [])

  return (
    <div className="mx-auto max-w-5xl">
      <PageHeader title={`Video ${id}`} back={{ to: '/inbox', label: 'Inbox' }} />
      <div className="grid gap-6 md:grid-cols-[minmax(0,22rem)_1fr]">
        <section className="space-y-4">
          <video
            ref={video}
            src={asset.preview_url ?? undefined}
            poster={asset.thumbnail_url ?? undefined}
            controls
            playsInline
            preload="metadata"
            className="aspect-[9/16] max-h-[70dvh] w-full rounded-card bg-black object-contain shadow-card"
          />
          <div className="flex flex-wrap gap-1.5">
            <Chip>{asset.status.replace('_', ' ')}</Chip>
            {asset.verdict !== 'none' && (
              <Chip tone={asset.verdict === 'liked' ? 'success' : 'danger'}>{asset.verdict}</Chip>
            )}
          </div>
          <div className="flex flex-wrap gap-2">
            <Button aria-pressed={asset.verdict === 'disliked'} onClick={() => act(() => setVerdict(id, 'disliked'))}
              className={verdictButton('danger', asset.verdict === 'disliked')}>
              Dislike
            </Button>
            <Button aria-pressed={asset.verdict === 'liked'} onClick={() => act(() => setVerdict(id, 'liked'))}
              className={verdictButton('success', asset.verdict === 'liked')}>
              Like
            </Button>
            {asset.status === 'ready' && (
              <>
                <Button variant="primary" onClick={approve}>Approve</Button>
                <Button variant="ghost" onClick={() => act(() => archiveAsset(id))}>Archive</Button>
              </>
            )}
            {asset.status === 'approved' && (
              <Button variant="primary" onClick={() => setScheduling(true)}>Schedule</Button>
            )}
            {(asset.status === 'approved' || asset.status === 'scheduled') && (
              <Button variant="ghost" onClick={() => act(() => unapproveAsset(id))}>Unapprove</Button>
            )}
          </div>
          {asset.status === 'scheduled' && <ScheduledSlot assetId={id} onUnscheduled={setAsset} />}
          {scheduling && (
            <ScheduleSheet
              assetId={id}
              onClose={() => setScheduling(false)}
              onScheduled={(a) => {
                setAsset(a)
                setScheduling(false)
              }}
            />
          )}
          {error && <p role="alert" className="text-sm text-danger">{error}</p>}
          <form onSubmit={save} className="space-y-3">
            <label className="block text-sm font-medium">
              Caption
              <textarea value={caption} onChange={(e) => setCaption(e.target.value)} rows={4}
                className={`${field} mt-1 block w-full py-2 font-normal`} />
            </label>
            <label className="block text-sm font-medium">
              Best before
              <input type="date" value={bestBefore} onChange={(e) => setBestBefore(e.target.value)}
                className={`${field} mt-1 block font-normal`} />
            </label>
            <Button type="submit" variant="primary">Save</Button>
            {saveMsg && <p role="status" className="text-sm text-muted">{saveMsg}</p>}
          </form>
        </section>

        <div className="space-y-4">
          <Card as="section" aria-label="About this video">
            <dl className="space-y-3">
              <Row label="Hook">{idea.hook}</Row>
              <Row label="Hook type">{label('hook_types', idea.hook_type)}</Row>
              <Row label="Hypothesis">{idea.hypothesis}</Row>
              <Row label="Track">
                {label('tracks', idea.track)}
                {idea.strategy === 'explore' && (
                  <Chip tone="explore" className="ml-2">Explore</Chip>
                )}
              </Row>
              <Row label="Pillar">{label('pillars', idea.pillar)}</Row>
              <Row label="Recipe">{recipeSummary(asset.recipe)}</Row>
              {asset.recipe?.voiced_by && (
                <Row label="Voice">
                  <VoiceBadge by={asset.recipe.voiced_by} />
                  {asset.recipe.voiced_by.voice && <span className="ml-2">{asset.recipe.voiced_by.voice}</span>}
                  {asset.recipe.voiced_by.fallback && (
                    <span className="mt-1 block text-warn">Fallback: {asset.recipe.voiced_by.fallback}</span>
                  )}
                </Row>
              )}
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
                  {asset.qc.warnings && asset.qc.warnings.length > 0 && (
                    <p className="text-warn">Check the wording: {asset.qc.warnings.join('; ')}</p>
                  )}
                </Row>
              )}
            </dl>
            {ctx.ai_label && <p className="mt-3 text-sm text-muted">{AI_LABEL_LINE}</p>}
            {(ctx.parent || ctx.children.length > 0) && (
              <nav aria-label="Versions" className="mt-3 flex flex-wrap gap-3 text-sm">
                {ctx.parent && (
                  <Link to={`/assets/${ctx.parent.id}`} className={link}>Older version</Link>
                )}
                {ctx.children.map((c) => (
                  <Link key={c.id} to={`/assets/${c.id}`} className={link}>
                    Newer version #{c.id} ({c.status.replace('_', ' ')})
                  </Link>
                ))}
              </nav>
            )}
          </Card>
          {asset.recipe?.inputs?.reaction && (
            <ReactionCards assetId={id} onRendered={(a) => {
              if (a.id === id) setAsset(a) // failed: re-rendered in place
              else setCtx((c) => c && { ...c, children: [...c.children, a] })
            }} />
          )}
          <CommentThread assetId={id} onSeek={seek} currentTime={() => video.current?.currentTime ?? 0}
            reasons={taxonomy?.feedback_reasons.values ?? []} onAsset={setAsset} />
        </div>
      </div>
    </div>
  )
}
