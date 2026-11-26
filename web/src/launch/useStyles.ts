import { useEffect, useState } from 'react'
import { errorMessage, listStyles, type Style } from '../api/client'

/** GET /api/styles once per mount: the styles the owner can launch work in (step 138). */
export function useStyles() {
  const [styles, setStyles] = useState<Style[]>()
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    let live = true
    listStyles().then((s) => live && setStyles(s), (e: unknown) => live && setError(errorMessage(e)))
    return () => { live = false }
  }, [])
  return { styles, error }
}

/** lemo.REA_FILM: the « rea-video » route on Auto, a copy in no catalog style. */
export const REA_FILM = 'lemo:rea-video'

export const styleLabel = (styles: Style[] | undefined, id: string | null | undefined) =>
  id === REA_FILM ? 'Copie plan par plan (rea-video)'
    : id ? (styles?.find((s) => s.id === id)?.label ?? id) : "Auto (l'IA choisit)"
