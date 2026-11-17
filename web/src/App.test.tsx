import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, getAccount } from './api/client'
import App from './App'

function stubFetch(status: number, body: unknown) {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify(body), { status }))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('api client', () => {
  it('maps a 503 instagram_not_configured to an ApiError', async () => {
    const fetchMock = stubFetch(503, { error: 'instagram_not_configured' })
    const err = await getAccount().catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err).toMatchObject({ status: 503, code: 'instagram_not_configured' })
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/account',
      expect.objectContaining({ credentials: 'same-origin' }),
    )
  })

  it('falls back to http_error when the body has no error code', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('Bad Gateway', { status: 502 })))
    await expect(getAccount()).rejects.toMatchObject({ status: 502, code: 'http_error' })
  })
})

describe('App', () => {
  it('renders the seven tabs and the setup-mode banner on Settings', async () => {
    const health = { status: 'ok', instagram_configured: false, version: '1.0' }
    // every route answers the health body, except the list the Settings page maps over
    vi.stubGlobal('fetch', vi.fn(async (url: string) =>
      new Response(JSON.stringify(url === '/api/agent/schedule' ? [] : health))))
    render(
      <MemoryRouter initialEntries={['/settings']}>
        <App />
      </MemoryRouter>,
    )
    const links = within(screen.getByRole('navigation', { name: 'Main' })).getAllByRole('link')
    expect(links.map((l) => l.textContent)).toEqual([
      'Inbox', 'Calendar', 'Analytics', 'Learnings', 'Ads', 'Agent', 'Settings',
    ])
    expect(await screen.findByText('Setup mode: add your Instagram token')).toBeTruthy()
  })

  it('links Trends from the Analytics page', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => new Response(JSON.stringify(
      url.startsWith('/api/trends') ? { accounts: [], hashtags: {}, generated_at: '' } : []))))
    render(
      <MemoryRouter initialEntries={['/analytics']}>
        <App />
      </MemoryRouter>,
    )
    fireEvent.click(screen.getByRole('link', { name: /^Trends/ }))
    expect(await screen.findByRole('heading', { name: 'Trends' })).toBeTruthy()
  })
})
