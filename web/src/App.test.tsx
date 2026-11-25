import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, errorMessage, getAccount } from './api/client'
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

  it('says errors in French: the server message, else the status, else no connection', () => {
    expect(errorMessage(new ApiError(409, 'busy', { error: 'busy', message: 'Déjà en cours.' }))).toBe('Déjà en cours.')
    expect(errorMessage(new ApiError(502, 'http_error', null))).toBe('Le serveur a répondu 502 (http_error).')
    expect(errorMessage(new TypeError('Failed to fetch'))).toBe('Pas de connexion au studio : vérifie le réseau et réessaie.')
    expect(errorMessage(new Error('autre'))).toBe('autre')
  })
})

describe('App', () => {
  it('renders the sidebar, the phone tab bar and the setup-mode banner on Settings', async () => {
    const health = { status: 'ok', instagram_configured: false, version: '1.0' }
    // every route answers the health body, except the lists the Settings page maps over
    const objects: Record<string, unknown> = {
      '/api/settings': { version: 0, fields: [] }, '/api/ads/presets': { presets: [] },
      '/api/storage': { media_bytes: 0, db_bytes: 0, free_bytes: 1e10, last_backup: null },
    }
    vi.stubGlobal('fetch', vi.fn(async (url: string) =>
      new Response(JSON.stringify(
        ['/api/agent/schedule', '/api/reactions', '/api/pinned-accounts', '/api/dm-picks', '/api/permissions', '/api/styles'].includes(url) || url.startsWith('/api/sources')
          ? [] : objects[url] ?? health))))
    render(
      <MemoryRouter initialEntries={['/settings']}>
        <App />
      </MemoryRouter>,
    )
    const links = within(screen.getByRole('navigation', { name: 'Principal' })).getAllByRole('link')
    expect(links.map((l) => l.textContent)).toEqual([
      'Inbox', 'Créer', 'Planning', 'Trending', 'Calendrier', 'Statistiques', 'Apprentissages', 'Styles', 'Voix', 'Pubs', 'Agent', 'Réglages',
    ])
    expect(links.find((l) => l.textContent === 'Réglages')?.getAttribute('aria-current')).toBe('page')
    // phone: five tabs and "More", which is current for the pages behind it
    const tabs = within(screen.getByRole('navigation', { name: 'Onglets' })).getAllByRole('link')
    expect(tabs.map((l) => l.textContent)).toEqual(['Inbox', 'Créer', 'Planning', 'Trending', 'Calendrier', 'Plus'])
    expect(tabs.filter((l) => l.getAttribute('aria-current')).map((l) => l.textContent)).toEqual(['Plus'])
    expect(await screen.findByText('Mode configuration : ajoute ton token Instagram')).toBeTruthy()
  })

  it.each([['/planning', 'Planning'], ['/agent', 'Plus']])('marks the current tab on %s', (path, current) => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 500 })))
    render(
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>,
    )
    const tabs = within(screen.getByRole('navigation', { name: 'Onglets' })).getAllByRole('link')
    expect(tabs.filter((l) => l.getAttribute('aria-current')).map((l) => l.textContent)).toEqual([current])
  })

  it('links Tendances from the Statistiques page', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => new Response(JSON.stringify(
      url.startsWith('/api/trends') ? { accounts: [], hashtags: {}, generated_at: '' } : []))))
    render(
      <MemoryRouter initialEntries={['/analytics']}>
        <App />
      </MemoryRouter>,
    )
    fireEvent.click(within(screen.getByRole('main')).getByRole('link', { name: /^Tendances/ }))
    expect(await screen.findByRole('heading', { name: 'Tendances' })).toBeTruthy()
  })

  it('lists the pages without a tab on the More page', () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{}')))
    render(
      <MemoryRouter initialEntries={['/more']}>
        <App />
      </MemoryRouter>,
    )
    const list = within(screen.getByRole('main')).getAllByRole('link')
    expect(list.map((l) => l.textContent)).toEqual(['Statistiques', 'Apprentissages', 'Styles', 'Voix', 'Pubs', 'Agent', 'Réglages'])
  })

  it('routes /ads to the Ads page', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 500 })))
    render(
      <MemoryRouter initialEntries={['/ads']}>
        <App />
      </MemoryRouter>,
    )
    expect(within(screen.getByRole('main')).getByRole('heading', { name: 'Pubs', level: 1 })).toBeTruthy()
    expect(await within(screen.getByRole('main')).findByRole('button', { name: 'Proposer un test' })).toBeTruthy()
  })
})
