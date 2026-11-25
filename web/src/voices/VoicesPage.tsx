import { useEffect, useState } from 'react'
import { errorMessage, listVoices, removeVoice, setVoiceEnabled, type EngineStatus, type Voice } from '../api/client'
import { Button } from '../ui/Button'
import { Card, EmptyState, Skeleton } from '../ui/Card'
import { Chip } from '../ui/Chip'
import { PageHeader } from '../ui/PageHeader'
import { useToast } from '../ui/useToast'
import { ElevenLibrary } from './ElevenLibrary'
import { EnginePanel } from './EnginePanel'
import { Preview } from './Preview'

function VoiceCard({ voice: v, lastOn, relay, onToggle, onRemove }: {
  voice: Voice; lastOn: boolean; relay?: string; onToggle: () => void; onRemove?: () => void
}) {
  const eleven = v.engine === 'elevenlabs'
  return (
    <Card as="li" className={`space-y-3 ${v.enabled ? '' : 'border-dashed'}`}>
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <h2 className={`font-semibold ${v.enabled ? '' : 'text-muted'}`}>{v.label}</h2>
          <p className="mt-1 flex flex-wrap gap-1">
            <Chip tone={eleven ? 'info' : 'neutral'}>{eleven ? 'ElevenLabs' : 'Locale'}</Chip>
            {v.default && <Chip tone="accent" title="Utilisée seulement si aucune voix ne convient à la vidéo">Secours</Chip>}
            {v.address.map((a) => <Chip key={a}>{a}</Chip>)}
            {eleven && v.accent && <Chip>{v.accent}</Chip>}
          </p>
        </div>
        <label className="flex min-h-11 shrink-0 items-center gap-2 text-sm font-medium"
          title={lastOn ? 'Au moins une voix doit rester active' : undefined}>
          <input type="checkbox" role="switch" className="size-5 accent-accent" checked={v.enabled}
            disabled={lastOn} onChange={onToggle} aria-label={`Utiliser ${v.label} pour les vidéos`} />
          {v.enabled ? 'Active' : 'Désactivée'}
        </label>
      </div>
      {v.use_for && <p className="text-sm"><span className="font-medium">L'IA la choisit pour : </span>{v.use_for}</p>}
      {v.description && v.description !== v.use_for && <p className="text-sm text-muted">{v.description}</p>}
      {relay && <p className="text-sm"><span className="font-medium">{eleven ? 'Relais local : ' : 'Jumelle ElevenLabs : '}</span>{relay}</p>}
      {v.sample ? <Preview eager={eleven} src={v.sample} label={`Écouter ${v.label}`} />
        : <p className="text-sm text-muted">Pas d'échantillon.</p>}
      {v.sample_text && <p className="text-sm italic text-muted">« {v.sample_text} »</p>}
      {onRemove && <Button variant="ghost" size="sm" onClick={onRemove} disabled={lastOn}>Retirer cette carte</Button>}
    </Card>
  )
}

/** /voices: the voice engines (204: which speaks first, the ElevenLabs model and credits), then
 * the voices, each with a sample and an on / off switch: the ElevenLabs cards (added from the
 * Voice Library, each paired with a local relay voice) and the local voices. Only the voices
 * on are used when a video is made; the last one on cannot be turned off. */
export default function VoicesPage() {
  const [voices, setVoices] = useState<Voice[]>()
  const [engine, setEngine] = useState<EngineStatus>()
  const [adding, setAdding] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const toast = useToast()

  useEffect(() => {
    let live = true
    listVoices().then((v) => live && setVoices(v), (e: unknown) => live && setError(errorMessage(e)))
    return () => { live = false }
  }, [])
  // one sample at a time
  useEffect(() => {
    const only = (e: Event) => document.querySelectorAll('audio').forEach((a) => a !== e.target && a.pause())
    document.addEventListener('play', only, true)
    return () => document.removeEventListener('play', only, true)
  }, [])

  const toggle = (v: Voice) => {
    const flip = (on: boolean) => setVoices((list) => list?.map((x) => (x.id === v.id ? { ...x, enabled: on } : x)))
    flip(!v.enabled) // optimistic; put back if the server refuses
    setVoiceEnabled(v.id, !v.enabled).catch((e: unknown) => {
      flip(v.enabled)
      toast({ message: `Voix non enregistrée : ${errorMessage(e)}` })
    })
  }
  const remove = (v: Voice) => {
    if (!window.confirm(`Retirer la carte ${v.label} ? La voix reste dans ton compte ElevenLabs.`)) return
    removeVoice(v.id).then(() => setVoices((list) => list?.filter((x) => x.id !== v.id)),
      (e: unknown) => toast({ message: `Carte non retirée : ${errorMessage(e)}` }))
  }

  const on = voices?.filter((v) => v.enabled) ?? []
  const locals = voices?.filter((v) => v.engine !== 'elevenlabs') ?? []
  const cards = voices?.filter((v) => v.engine === 'elevenlabs') ?? []
  const labelOf = (id?: string | null) => voices?.find((x) => x.id === id)?.label
  const twin = (local: Voice) => cards.filter((c) => c.fallback === local.id).map((c) => c.label).join(', ') || undefined
  const card = (v: Voice) => (
    <VoiceCard key={v.id} voice={v} lastOn={v.enabled && on.length === 1} onToggle={() => toggle(v)}
      relay={v.engine === 'elevenlabs' ? labelOf(v.fallback) : twin(v)}
      onRemove={v.engine === 'elevenlabs' ? () => remove(v) : undefined} />
  )
  const canAdd = engine?.elevenlabs.configured
  const noKey = engine && !engine.elevenlabs.configured // not when the status failed to load
  return (
    <>
      <PageHeader title="Voix">Écoutez les voix du studio. Pour chaque vidéo, l'IA choisit parmi les voix actives celle qui convient à la scène (récit, énergie, voix d'homme ou de femme).</PageHeader>
      <EnginePanel onEngine={setEngine} />
      {error ? <p role="alert" className="text-sm text-danger">Voix indisponibles : {error}</p>
        : !voices ? <Skeleton className="h-64" />
          : (
            <>
              <p className="mb-3 text-sm text-muted" role="status">{on.length} voix active{on.length > 1 ? 's' : ''} sur {voices.length}</p>
              <section aria-label="Voix ElevenLabs" className="mb-6">
                <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                  <h2 className="text-lg font-semibold">Voix ElevenLabs</h2>
                  {canAdd && <Button variant="primary" onClick={() => setAdding(true)}>Ajouter une voix ElevenLabs</Button>}
                </div>
                {cards.length ? <ul className="grid gap-3 md:grid-cols-2">{cards.map(card)}</ul>
                  : <EmptyState title="Aucune voix ElevenLabs">{canAdd
                    ? 'Cherche une voix dans la bibliothèque ElevenLabs (langue, genre, âge, accent, usage), écoute-la, puis ajoute-la avec sa voix locale de relais.'
                    : noKey ? 'Branche ElevenLabs (ELEVENLABS_API_KEY) pour ajouter des voix.'
                      : 'Les réglages des moteurs ne sont pas chargés : recharge la page.'}</EmptyState>}
              </section>
              <section aria-label="Voix locales">
                <h2 className="mb-3 text-lg font-semibold">Voix locales</h2>
                {locals.length ? <ul className="grid gap-3 md:grid-cols-2">{locals.map(card)}</ul>
                  : <EmptyState title="Aucune voix">brand/voices/voices.json est vide.</EmptyState>}
              </section>
            </>
          )}
      {adding && <ElevenLibrary locals={locals} onClose={() => setAdding(false)}
        onAdded={() => listVoices().then(setVoices, (e: unknown) => setError(errorMessage(e)))} />}
    </>
  )
}
