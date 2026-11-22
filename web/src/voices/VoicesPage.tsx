import { useEffect, useState } from 'react'
import { errorMessage, listVoices, setVoiceEnabled, type Voice } from '../api/client'
import { Card, EmptyState, Skeleton } from '../ui/Card'
import { Chip } from '../ui/Chip'
import { PageHeader } from '../ui/PageHeader'
import { useToast } from '../ui/useToast'

function VoiceCard({ voice: v, lastOn, onToggle }: { voice: Voice; lastOn: boolean; onToggle: () => void }) {
  return (
    <Card as="li" className={`space-y-3 ${v.enabled ? '' : 'opacity-70'}`}>
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <h2 className="font-semibold">{v.label}</h2>
          <p className="mt-1 flex flex-wrap gap-1">
            {v.default && <Chip tone="accent" title="Utilisée seulement si aucune voix ne convient à la vidéo">Secours</Chip>}
            {v.address.map((a) => <Chip key={a}>{a}</Chip>)}
          </p>
        </div>
        <label className="flex min-h-11 shrink-0 items-center gap-2 text-sm font-medium"
          title={lastOn ? 'Au moins une voix doit rester active' : undefined}>
          <input type="checkbox" role="switch" className="size-5 accent-accent" checked={v.enabled}
            disabled={lastOn} onChange={onToggle} aria-label={`Utiliser ${v.label} pour les vidéos`} />
          {v.enabled ? 'Active' : 'Désactivée'}
        </label>
      </div>
      {v.use_for && <p className="text-sm"><span className="font-medium">L'IA la choisit pour : </span>{v.use_for}</p>}
      {v.description && <p className="text-sm text-muted">{v.description}</p>}
      {v.sample ? <audio controls preload="none" src={v.sample} className="w-full" />
        : <p className="text-sm text-muted">Pas d'échantillon.</p>}
      {v.sample_text && <p className="text-sm italic text-muted">« {v.sample_text} »</p>}
    </Card>
  )
}

/** /voices: the voice-over voices, each with a sample to hear and an on / off switch. Only
 * the voices on are used when a video is made; the last one on cannot be turned off. */
export default function VoicesPage() {
  const [voices, setVoices] = useState<Voice[]>()
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
      toast({ message: `Voix non enregistrée : ${errorMessage(e)}` })
    })
  }

  const on = voices?.filter((v) => v.enabled) ?? []
  return (
    <>
      <PageHeader title="Voix">Écoutez les voix du studio. Pour chaque vidéo, l'IA choisit parmi les voix actives celle qui convient à la scène (récit, énergie, voix d'homme ou de femme).</PageHeader>
      {error ? <p role="alert" className="text-sm text-danger">Voix indisponibles : {error}</p>
        : !voices ? <Skeleton className="h-64" />
          : !voices.length ? <EmptyState title="Aucune voix">brand/voices/voices.json est vide.</EmptyState>
            : (
              <>
                <p className="mb-3 text-sm text-muted" role="status">{on.length} voix active{on.length > 1 ? 's' : ''} sur {voices.length}</p>
                <ul className="grid gap-3 md:grid-cols-2">
                  {voices.map((v) => (
                    <VoiceCard key={v.id} voice={v} lastOn={v.enabled && on.length === 1} onToggle={() => toggle(v)} />
                  ))}
                </ul>
              </>
            )}
    </>
  )
}
