import type { Asset } from '../api/client'
import { Chip } from '../ui/Chip'

type By = NonNullable<NonNullable<Asset['recipe']>['voiced_by']>

/** Step 204: which engine spoke a video; warn-toned when it was the other engine's fallback. */
export function VoiceBadge({ by }: { by: By }) {
  const name = by.engine === 'elevenlabs' ? 'ElevenLabs' : by.engine === 'http' ? 'Voix locale' : by.engine
  return (
    <Chip tone={by.fallback ? 'warn' : by.engine === 'elevenlabs' ? 'info' : 'neutral'}
      title={by.fallback ? `Relais : ${by.fallback}` : undefined}>
      {name}{by.fallback ? ' (relais)' : ''}
    </Chip>
  )
}
