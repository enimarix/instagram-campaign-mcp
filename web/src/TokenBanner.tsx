import { useEffect, useState } from 'react'
import { getToken, type TokenStatus } from './api/client'

const WARN_DAYS = 10 // step 029: warn from 10 days before expiry

/** Shown on every page when the Instagram token is invalid or expires within WARN_DAYS. */
export default function TokenBanner() {
  const [t, setT] = useState<TokenStatus | null>(null)
  useEffect(() => {
    getToken().then(setT, () => setT(null)) // the Settings page shows the error
  }, [])
  if (!t?.configured || t.valid === null) return null
  const days = t.days_left
  if (t.valid && (days === null || days > WARN_DAYS)) return null
  const what = !t.valid || (days !== null && days < 0)
    ? 'a expiré ou n’est pas valide : la publication est arrêtée.'
    : `expire ${days === 0 ? 'aujourd’hui' : `dans ${days} jour${days === 1 ? '' : 's'}`} : la publication s’arrêtera alors.`
  return (
    <p role="alert"
      className="border-b border-warn/30 bg-warn/12 px-4 py-2 text-sm font-medium text-warn lg:px-8">
      Le token Instagram {what}{' '}
      {t.can_refresh && t.valid ? 'Lance ig-campaign token refresh.' : 'Colle un nouveau token dans .env (voir README, Token).'}
    </p>
  )
}
