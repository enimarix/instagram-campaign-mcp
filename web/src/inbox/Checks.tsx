import { Link } from 'react-router'
import type { Asset } from '../api/client'
import { link } from '../ui/styles'

/** The AI's check of finished renders (188c), for the batch on screen: how many videos it
 * has not looked at yet (they join the feed once submitted, or after a grace), and the ones
 * it dropped with its reason. Nothing shows when neither. */
export default function Checks({ assets }: { assets: Asset[] }) {
  const checking = assets.filter((a) => a.awaiting_check).length
  const dropped = assets.filter((a) => a.agent_decision?.kind === 'dropped')
  if (!checking && !dropped.length) return null
  return (
    <div className="mx-auto max-w-md space-y-1 text-sm">
      {checking > 0 && (
        <p role="note" className="text-muted">
          {checking === 1 ? "1 vidéo en vérification par l'IA" : `${checking} vidéos en vérification par l'IA`}
        </p>
      )}
      {dropped.length > 0 && (
        <ul aria-label="Dropped by the AI" className="space-y-1">
          {dropped.map((a) => (
            <li key={a.id}>
              <Link to={`/assets/${a.id}`} className={link}>Vidéo {a.id}</Link>{' '}
              <span className="text-muted">{a.agent_decision?.text}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
