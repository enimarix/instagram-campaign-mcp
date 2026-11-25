import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { TokenStatus } from './api/client'
import TokenBanner from './TokenBanner'

const OK: TokenStatus = {
  configured: true, valid: true, expires_at: '2027-01-10T12:00:00+00:00', days_left: 30,
  can_refresh: true, scopes: [],
}

function show(t: Partial<TokenStatus>) {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ ...OK, ...t }), { status: 200 })))
  render(<TokenBanner />)
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('TokenBanner', () => {
  it('warns from 10 days before expiry', async () => {
    show({ days_left: 10 })
    expect((await screen.findByRole('alert')).textContent).toMatch(/expire dans 10 jours.*token refresh/)
  })

  it('says when the token is expired and refresh cannot help', async () => {
    show({ valid: false, days_left: -1 })
    expect((await screen.findByRole('alert')).textContent).toMatch(/a expiré ou n’est pas valide.*Colle un nouveau token/)
  })

  it.each([{ days_left: 11 }, { expires_at: null, days_left: null }, { configured: false }])(
    'stays hidden for %o', async (t) => {
      show(t)
      await new Promise((r) => setTimeout(r, 20))
      expect(screen.queryByRole('alert')).toBeNull()
    })
})
