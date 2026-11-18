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
    ? 'has expired or is invalid: publishing is stopped.'
    : `expires ${days === 0 ? 'today' : `in ${days} day${days === 1 ? '' : 's'}`}: publishing stops then.`
  return (
    <p role="alert"
      className="border-b border-warn/30 bg-warn/12 px-4 py-2 text-sm font-medium text-warn lg:px-8">
      Instagram token {what}{' '}
      {t.can_refresh && t.valid ? 'Run ig-campaign token refresh.' : 'Paste a new token in .env (see README, Token).'}
    </p>
  )
}
