import { useState } from 'react'

/** A voice sample to listen to. ElevenLabs samples load their length at once (a working
 * one shows « 0:08 », not « 0:00 »); one the browser refuses says so instead of a silent
 * player: usually the page is older than the studio (its security rules let ElevenLabs
 * audio in since 204), and a reload fixes it. */
export function Preview({ src, label, eager }: { src: string; label: string; eager?: boolean }) {
  const [failed, setFailed] = useState(false)
  if (failed)
    return (
      <p role="alert" className="mt-2 text-sm text-warn">
        Aperçu impossible à charger. Recharge la page (Ctrl+F5) ; si ça persiste, l'aperçu n'est plus disponible chez ElevenLabs.
      </p>
    )
  return <audio controls preload={eager ? 'metadata' : 'none'} src={src} className="mt-2 w-full" aria-label={label} onError={() => setFailed(true)} />
}
