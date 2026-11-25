import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { ApiError, getSession, login, onLoggedOut } from './api/client'
import { buttonClass, card, field } from './ui/styles'

const ERRORS: Record<string, string> = {
  bad_password: 'Wrong password.',
  locked: 'Too many wrong passwords: wait a few minutes.',
}

/** Shows the sign-in form while UI_PASSWORD is set and this browser has no session (step 008). */
export default function Login({ children }: { children: ReactNode }) {
  const [state, setState] = useState<'checking' | 'in' | 'out'>('checking')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    getSession()
      .then((s) => setState(!s.password_required || s.authenticated ? 'in' : 'out'))
      .catch(() => setState('in')) // ponytail: server down → let the pages show their own errors
  }, [])

  useEffect(() => {
    // Any API call answered 401 brings the form back; signing in shows the app again, no reload.
    onLoggedOut(() => setState('out'))
    return () => onLoggedOut(null)
  }, [])

  async function submit(e: FormEvent) {
    e.preventDefault()
    setError('')
    try {
      await login(password)
      setState('in')
    } catch (err) {
      setError(ERRORS[err instanceof ApiError ? err.code : ''] ?? 'Could not sign in.')
    }
  }

  if (state === 'checking')
    return (
      <div role="status" aria-label="Chargement" className="grid min-h-dvh place-items-center">
        <span aria-hidden className="size-8 animate-spin rounded-full border-2 border-current border-r-transparent text-accent" />
      </div>
    )
  if (state === 'in') return <>{children}</>
  return (
    <main className="grid min-h-dvh place-items-center p-4">
      <form onSubmit={submit} className={`${card} flex w-full max-w-sm flex-col gap-4 p-6`}>
        <h1 className="text-lg font-bold">Growth Studio</h1>
        <label className="text-sm">Password
          <input type="password" value={password} required autoFocus autoComplete="current-password"
            onChange={(e) => setPassword(e.target.value)} className={`${field} mt-1 block w-full`} />
        </label>
        {error && <p role="alert" className="text-sm text-danger">{error}</p>}
        <button type="submit" className={buttonClass('primary')}>Sign in</button>
      </form>
    </main>
  )
}
