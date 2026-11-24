import { useEffect, useState } from 'react'
import { errorMessage, getEngine, listElevenModels, setEngine, type ElevenModel, type EngineStatus, type VoiceEngine } from '../api/client'
import { Card, Skeleton } from '../ui/Card'
import { Chip } from '../ui/Chip'
import { field } from '../ui/styles'
import { useToast } from '../ui/useToast'

/** Models that act on audio tags ([excited], [laughs]…): v3 and v4 (ElevenLabs' prompting guide). */
const hearsTags = (model: string) => /^eleven_v[34]/.test(model)

const when = (unix: number | null) =>
  unix ? new Date(unix * 1000).toLocaleDateString('fr-FR', { day: 'numeric', month: 'long' }) : null

/** Step 204: which engine speaks first, the ElevenLabs model and the credits left. */
export function EnginePanel({ onEngine }: { onEngine?: (e: EngineStatus) => void }) {
  const [engine, setState] = useState<EngineStatus>()
  const [models, setModels] = useState<ElevenModel[]>()
  const [error, setError] = useState<string | null>(null)
  const toast = useToast()

  useEffect(() => {
    let live = true
    getEngine().then((e) => {
      if (!live) return
      setState(e)
      onEngine?.(e)
      if (e.elevenlabs.configured) listElevenModels().then((m) => live && setModels(m), () => live && setModels([]))
    }, (e: unknown) => live && setError(errorMessage(e)))
    return () => { live = false }
  }, [onEngine])

  if (error) return <p role="alert" className="mb-4 text-sm text-danger">Moteurs indisponibles : {error}</p>
  if (!engine) return <Skeleton className="mb-4 h-32" />

  const save = (change: { priority?: VoiceEngine; model?: string }) => {
    const before = engine
    setState({ ...engine, ...change })
    setEngine(change).then(() => onEngine?.({ ...before, ...change }), (e: unknown) => {
      setState(before)
      toast({ message: `Réglage non enregistré : ${errorMessage(e)}` })
    })
  }
  const el = engine.elevenlabs
  const c = el.credits
  const known = models?.some((m) => m.id === engine.model)
  return (
    <Card as="section" aria-label="Moteurs de voix" className="mb-4 space-y-4">
      <div>
        <h2 className="font-semibold">Moteur prioritaire</h2>
        <p className="mt-1 text-sm text-muted">Le premier moteur fait la voix ; s'il échoue (crédits épuisés, panne), l'autre prend le relais avec la voix jumelle.</p>
        <div className="mt-2 flex flex-wrap gap-2" role="group" aria-label="Moteur prioritaire">
          <Chip pressed={engine.priority === 'elevenlabs'} onClick={() => save({ priority: 'elevenlabs' })}>ElevenLabs d'abord</Chip>
          <Chip pressed={engine.priority === 'local'} onClick={() => save({ priority: 'local' })}>Voix locale d'abord</Chip>
        </div>
        {!engine.local && <p className="mt-2 text-sm text-warn">La voix locale n'est pas configurée (TTS_PROVIDER) : pas de relais local.</p>}
      </div>

      {!el.configured ? (
        <p className="text-sm text-muted">ElevenLabs n'est pas branché : ajoutez <code>ELEVENLABS_API_KEY</code> dans <code>.env</code> puis relancez le studio.</p>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          <label className="block text-sm">
            <span className="font-semibold">Modèle ElevenLabs</span>
            <select className={`${field} mt-1 block w-full`} value={engine.model} aria-label="Modèle ElevenLabs"
              onChange={(e) => save({ model: e.target.value })} disabled={!models}>
              {!known && <option value={engine.model}>{engine.model}</option>}
              {models?.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name}{m.languages.includes('fr') ? ' · FR' : ''}{hearsTags(m.id) ? ' · émotions' : ''}{m.cost ? ` · ×${m.cost} crédit` : ''}
                </option>
              ))}
            </select>
            <span className="mt-1 block text-muted">
              {hearsTags(engine.model)
                ? 'Ce modèle joue les balises d\'émotion du script ([excited], [laughs], [whispers]…).'
                : 'Ce modèle ne joue pas les balises d\'émotion : elles sont retirées avant la voix.'}
            </span>
          </label>
          <div className="text-sm">
            <span className="font-semibold">Crédits ElevenLabs</span>
            {el.error ? <p role="alert" className="mt-1 text-danger">{el.error}</p> : c && (
              <>
                <div className="mt-2 h-2 overflow-hidden rounded-full bg-line" role="meter" aria-label="Crédits utilisés"
                  aria-valuemin={0} aria-valuemax={c.limit} aria-valuenow={c.used}>
                  <div className={`h-full ${c.left < c.limit * 0.1 ? 'bg-danger' : 'bg-accent'}`} style={{ width: `${c.limit ? Math.min(100, (c.used / c.limit) * 100) : 100}%` }} />
                </div>
                <p className="mt-1 text-muted">
                  {c.left.toLocaleString('fr-FR')} restants sur {c.limit.toLocaleString('fr-FR')}
                  {when(c.resets_at) ? `, renouvelés le ${when(c.resets_at)}` : ''}{c.tier ? ` (offre ${c.tier})` : ''}.
                  {' '}≈ 1 crédit par caractère avec eleven_v4.
                </p>
              </>
            )}
          </div>
        </div>
      )}
    </Card>
  )
}
