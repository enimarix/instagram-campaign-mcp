import { useEffect, useState, type FormEvent } from 'react'
import {
  errorMessage,
  fixTranscript,
  getReaction,
  nextReactionPiece,
  type Asset,
  type ReactionInfo,
} from '../api/client'
import { Button } from '../ui/Button'
import { Card } from '../ui/Card'
import { field, link } from '../ui/styles'
import { clock, safeUrl } from './ui'

const span = (a: number, b: number) => `${clock(a)}–${clock(b)}`

/** A reaction remix (069/072): the reel piece used, the clip's credit, and its speech.
 * `onRendered` gets the asset a re-render made (the same one, or a newer version). */
export default function ReactionCards({ assetId, onRendered }: { assetId: number; onRendered: (a: Asset) => void }) {
  const [info, setInfo] = useState<ReactionInfo | null>(null)
  const [texts, setTexts] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const [version, setVersion] = useState(0) // bumped when this video was re-rendered in place

  useEffect(() => {
    getReaction(assetId).then(
      (r) => {
        setInfo(r)
        setTexts(r.transcript.map((l) => l.text))
      },
      (e: unknown) => setMsg(`Could not load the reaction (${errorMessage(e)})`),
    )
  }, [assetId, version])

  async function rerender(run: () => Promise<{ asset: Asset }>, done: string) {
    setBusy(true)
    setMsg(null)
    try {
      const { asset } = await run()
      onRendered(asset)
      setMsg(asset.id === assetId ? done : `${done} New version: #${asset.id}.`)
      if (asset.id === assetId) setVersion((v) => v + 1)
    } catch (e) {
      setMsg(`Not done: ${errorMessage(e)}`)
    } finally {
      setBusy(false)
    }
  }

  function nextPiece() {
    if (!window.confirm('Render this video again with the next piece of your reaction reel?')) return
    rerender(() => nextReactionPiece(assetId), 'Rendering with the next reaction piece.')
  }

  function save(e: FormEvent) {
    e.preventDefault()
    rerender(() => fixTranscript(assetId, texts), 'Saved. Rendering with the new captions.')
  }

  if (!info) return msg ? <p role="alert" className="text-sm text-danger">{msg}</p> : null
  const { piece, source } = info
  const credit = source.attribution || source.author
  const href = safeUrl(source.url)

  return (
    <>
      <Card as="section" aria-label="Reaction" className="space-y-3">
        <h2 className="font-semibold">Reaction</h2>
        <div className="flex gap-3">
          {piece.url && (
            <video src={piece.url} controls muted playsInline preload="metadata"
              aria-label="Reaction piece" className="aspect-[9/16] w-24 rounded-card bg-black object-contain" />
          )}
          <dl className="space-y-2 text-sm">
            <div>
              <dt className="text-xs font-medium text-muted">Piece used</dt>
              <dd>Piece #{piece.id} of reel #{info.reel.id}, {span(piece.start_s, piece.end_s)}</dd>
            </div>
            <div>
              <dt className="text-xs font-medium text-muted">Clip used</dt>
              <dd>{span(info.trim.start_s, info.trim.end_s)}</dd>
            </div>
            <div>
              <dt className="text-xs font-medium text-muted">Credit</dt>
              <dd>
                {href ? (
                  <a href={href} target="_blank" rel="noopener noreferrer" className={link}>{credit ?? href}</a>
                ) : credit}
                {' · '}{source.rights_basis.replace('_', ' ')}
              </dd>
            </div>
          </dl>
        </div>
        <Button onClick={nextPiece} loading={busy}>Use the next reaction piece</Button>
      </Card>
      {info.transcript.length > 0 && (
        <Card as="section" aria-label="Clip speech">
          <form onSubmit={save} className="space-y-2">
            <h2 className="font-semibold">Clip speech</h2>
            <p className="text-sm text-muted">What the clip says, shown as captions. Fix a word, then save.</p>
            {info.transcript.map((line, i) => (
              <label key={line.index} className="block text-xs font-medium text-muted">
                {span(line.start_s, line.end_s)}
                <input value={texts[i] ?? ''} maxLength={80} required
                  onChange={(e) => setTexts((t) => t.map((x, j) => (j === i ? e.target.value : x)))}
                  className={`${field} mt-1 block w-full text-sm font-normal text-fg`} />
              </label>
            ))}
            <Button type="submit" variant="primary" loading={busy}>Save and re-render captions</Button>
          </form>
        </Card>
      )}
      {msg && <p role="status" className="text-sm text-muted">{msg}</p>}
    </>
  )
}
