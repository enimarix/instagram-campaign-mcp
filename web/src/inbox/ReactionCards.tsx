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
import { clock, rightsLabel, safeUrl } from './ui'

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
      (e: unknown) => setMsg(`Impossible de charger la réaction (${errorMessage(e)})`),
    )
  }, [assetId, version])

  async function rerender(run: () => Promise<{ asset: Asset }>, done: string) {
    setBusy(true)
    setMsg(null)
    try {
      const { asset } = await run()
      onRendered(asset)
      setMsg(asset.id === assetId ? done : `${done} Nouvelle version : #${asset.id}.`)
      if (asset.id === assetId) setVersion((v) => v + 1)
    } catch (e) {
      setMsg(`Pas fait : ${errorMessage(e)}`)
    } finally {
      setBusy(false)
    }
  }

  function nextPiece() {
    if (!window.confirm('Refaire cette vidéo avec le morceau suivant de ton Reel de réaction ?')) return
    rerender(() => nextReactionPiece(assetId), 'Rendu en cours avec le morceau de réaction suivant.')
  }

  function save(e: FormEvent) {
    e.preventDefault()
    rerender(() => fixTranscript(assetId, texts), 'Enregistré. Rendu en cours avec les nouveaux sous-titres.')
  }

  if (!info) return msg ? <p role="alert" className="text-sm text-danger">{msg}</p> : null
  const { piece, source } = info
  const credit = source.attribution || source.author
  const href = safeUrl(source.url)

  return (
    <>
      <Card as="section" aria-label="Réaction" className="space-y-3">
        <h2 className="font-semibold">Réaction</h2>
        <div className="flex gap-3">
          {piece.url && (
            <video src={piece.url} controls muted playsInline preload="metadata"
              aria-label="Morceau de réaction" className="aspect-[9/16] w-24 rounded-card bg-black object-contain" />
          )}
          <dl className="space-y-2 text-sm">
            <div>
              <dt className="text-xs font-medium text-muted">Morceau utilisé</dt>
              <dd>Morceau #{piece.id} du Reel #{info.reel.id}, {span(piece.start_s, piece.end_s)}</dd>
            </div>
            <div>
              <dt className="text-xs font-medium text-muted">Extrait utilisé</dt>
              <dd>{span(info.trim.start_s, info.trim.end_s)}</dd>
            </div>
            <div>
              <dt className="text-xs font-medium text-muted">Crédit</dt>
              <dd>
                {href ? (
                  <a href={href} target="_blank" rel="noopener noreferrer" className={link}>{credit ?? href}</a>
                ) : credit}
                {' · '}{rightsLabel(source.rights_basis)}
              </dd>
            </div>
          </dl>
        </div>
        <Button onClick={nextPiece} loading={busy}>Prendre le morceau de réaction suivant</Button>
      </Card>
      {info.transcript.length > 0 && (
        <Card as="section" aria-label="Paroles de l’extrait">
          <form onSubmit={save} className="space-y-2">
            <h2 className="font-semibold">Paroles de l’extrait</h2>
            <p className="text-sm text-muted">Ce que dit l’extrait, affiché en sous-titres. Corrige un mot, puis enregistre.</p>
            {info.transcript.map((line, i) => (
              <label key={line.index} className="block text-xs font-medium text-muted">
                {span(line.start_s, line.end_s)}
                <input value={texts[i] ?? ''} maxLength={80} required
                  onChange={(e) => setTexts((t) => t.map((x, j) => (j === i ? e.target.value : x)))}
                  className={`${field} mt-1 block w-full text-sm font-normal text-fg`} />
              </label>
            ))}
            <Button type="submit" variant="primary" loading={busy}>Enregistrer et refaire les sous-titres</Button>
          </form>
        </Card>
      )}
      {msg && <p role="status" className="text-sm text-muted">{msg}</p>}
    </>
  )
}
