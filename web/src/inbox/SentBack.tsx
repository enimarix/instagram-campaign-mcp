import { useEffect, useState } from 'react'
import { Link } from 'react-router'
import { listAssets, type Asset } from '../api/client'
import { link } from '../ui/styles'

/** The videos the owner sent back for changes and what the AI decided for each (156):
 * « Refaite en Macro 3D », « Nouveau style demandé : … », « En attente : … ». Never silence:
 * one it has not read yet says so. Nothing shows when none waits (or the list fails). */
export default function SentBack() {
  const [assets, setAssets] = useState<Asset[]>([])

  useEffect(() => {
    let live = true
    listAssets({ status: 'revision_requested' }).then(
      (list) => live && setAssets(list.filter((a) => a.status === 'revision_requested')),
      () => {},
    )
    return () => {
      live = false
    }
  }, [])

  if (!assets.length) return null
  return (
    <details className="mx-auto max-w-md rounded-card border border-line/60 bg-surface p-3 text-sm">
      <summary className="cursor-pointer font-medium">
        {assets.length} {assets.length === 1 ? 'vidéo renvoyée' : 'vidéos renvoyées'} pour changements
      </summary>
      <ul aria-label="Renvoyées" className="mt-2 max-h-48 space-y-2 overflow-y-auto">
        {assets.map((a) => (
          <li key={a.id} className="flex items-start gap-2">
            {a.thumbnail_url && <img src={a.thumbnail_url} alt="" className="h-12 w-7 shrink-0 rounded object-cover" />}
            <div className="min-w-0">
              <Link to={`/assets/${a.id}`} className={link}>Vidéo {a.id}</Link>
              <p className={a.agent_decision ? '' : 'text-muted'}>
                {a.agent_decision?.text ?? "Pas encore vue par l'IA"}
              </p>
              {a.agent_decision && a.agent_decision.kind !== 'waiting' && (
                <p className="line-clamp-2 text-muted">{a.agent_decision.why}</p>
              )}
            </div>
          </li>
        ))}
      </ul>
    </details>
  )
}
