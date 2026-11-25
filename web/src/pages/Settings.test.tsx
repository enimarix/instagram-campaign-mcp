import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router'
import type { DownloaderStatus, WorkerStatus } from '../api/client'
import Settings from './Settings'

const WORKER: WorkerStatus = {
  heartbeat_at: new Date(Date.now() - 3 * 60_000).toISOString(),
  alive: true,
  paused: false,
  next_slot: '2026-11-18T18:10:00+00:00',
  last_result: { published: [{ id: 1 }], failed: [], retrying: [], replanned: [], paused: false },
}

const HOUR_AGO = new Date(Date.now() - 3600_000).toISOString()
function downloader(over: Partial<DownloaderStatus>): DownloaderStatus {
  return {
    set_up: true, host: '127.0.0.1', port: 3210, health_configured: true,
    health: { status: 'up', checked_at: HOUR_AGO }, ...over,
  }
}

const ROUTES: Record<string, [number, unknown]> = {
  'GET /api/health': [200, { status: 'ok', instagram_configured: true, version: '1.2' }],
  'GET /api/account': [200, {
    token_valid: true,
    profile: { username: 'macrobody' },
    publishing_limit: { quota_usage: 3, config: { quota_total: 100 } },
  }],
  'GET /api/worker/status': [200, WORKER],
  'GET /api/storage': [200, { media_bytes: 2_500_000_000, db_bytes: 12_000_000, free_bytes: 2e9, last_backup: null }],
  'GET /api/token': [200, {
    configured: true, valid: true, expires_at: '2027-01-10T12:00:00+00:00', days_left: 40,
    can_refresh: true, scopes: [],
  }],
  'POST /api/worker/pause': [200, { ...WORKER, paused: true }],
  'GET /api/agent/schedule': [200, [
    {
      playbook: 'daily-produce', time: '03:00', next_at: '2026-11-18T03:00:00+01:00', exists: true,
      last_run: { id: 4, status: 'failed', started_at: new Date(Date.now() - 2 * 3600_000).toISOString(), finished_at: null },
    },
    { playbook: 'review', time: '14:30', next_at: '2026-11-17T14:30:00+01:00', exists: false, last_run: null },
  ]],
  'GET /api/pinned-accounts': [200, []],
  'GET /api/dm-picks': [200, []],
  'GET /api/downloader/status': [200, downloader({})],
}

function stubApi(overrides: Record<string, [number, unknown]> = {}) {
  const calls: string[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method ?? 'GET'} ${url}`
    calls.push(key)
    const [status, body] = overrides[key] ?? ROUTES[key] ?? [404, { error: 'not_found' }]
    return new Response(JSON.stringify(body), { status })
  }))
  return calls
}

const section = (name: string) => screen.getByRole('region', { name })

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('Settings', () => {
  it('renders every section from the APIs', async () => {
    stubApi()
    render(<MemoryRouter><Settings /></MemoryRouter>)
    await screen.findByText('Running')
    const worker = section('Worker')
    expect(within(worker).getByText('3 minutes ago')).toBeTruthy()
    expect(within(worker).getByText('1 published')).toBeTruthy()

    const ig = section('Instagram')
    expect(within(ig).getByText('Valid')).toBeTruthy()
    expect(within(ig).getByText('macrobody')).toBeTruthy()
    expect(within(ig).getByText('3 / 100 in 24 h')).toBeTruthy()
    expect(await within(ig).findByText(/\(40 days left\)$/)).toBeTruthy()

    const storage = section('Storage')
    expect(within(storage).getByText('2.5 GB')).toBeTruthy()
    expect(within(storage).getByText('12.0 MB')).toBeTruthy()
    expect(within(storage).getByRole('alert').textContent).toMatch(/Low/)
    expect(within(section('Backups')).getByText('No backups yet')).toBeTruthy()

    const agent = section('Agent schedule')
    const next = new Date('2026-11-18T03:00:00+01:00').toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
    expect(within(agent).getByText('Vidéos du jour at 03:00')).toBeTruthy()
    expect(within(agent).getByText(`Next ${next} · last failed 2 hours ago`)).toBeTruthy()
    expect(within(agent).getByText('Playbook not written yet · never ran')).toBeTruthy()
    expect(screen.queryByText('Setup mode: add your Instagram token')).toBeNull()
  })

  it('indexes every section: each chip points at an id on the page, in page order', () => {
    stubApi()
    const { container } = render(<MemoryRouter><Settings /></MemoryRouter>)
    const chips = within(screen.getByRole('navigation', { name: 'Sections' })).getAllByRole('link')
    expect(chips.map((l) => l.textContent)).toEqual(['Apparence', 'Worker', 'Instagram', 'Stockage', 'Sauvegardes',
      "Planning de l'IA", 'Studio', 'Styles', 'Pubs', 'Clips', 'Autorisations', 'Reel réaction', 'DM', 'Téléchargeur', 'Serveur'])
    const ids = chips.map((l) => l.getAttribute('href')!.slice(1))
    const onPage = [...container.querySelectorAll('[id]')].map((el) => el.id).filter((id) => ids.includes(id))
    expect(onPage).toEqual(ids)
    for (const id of ids) expect(document.getElementById(id)!.className).toContain('scroll-mt-16 lg:scroll-mt-4')
    expect(document.getElementById('ads')!.getAttribute('aria-label')).toBe('Ads')
  })

  it('scrolls to the section of the URL hash', () => {
    stubApi()
    const scroll = vi.fn()
    Element.prototype.scrollIntoView = scroll
    render(<MemoryRouter initialEntries={['/settings#ads']}><Settings /></MemoryRouter>)
    expect(scroll).toHaveBeenCalledWith({ block: 'start' })
    expect(scroll.mock.contexts[0]).toBe(document.getElementById('ads'))
  })

  it('says so when no agent run is scheduled', async () => {
    stubApi({ 'GET /api/agent/schedule': [200, []] })
    render(<MemoryRouter><Settings /></MemoryRouter>)
    expect(await within(section('Agent schedule')).findByText('None (AGENT_SCHEDULE is empty)')).toBeTruthy()
  })

  it('pauses publishing after a confirm', async () => {
    const calls = stubApi()
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true)
    render(<MemoryRouter><Settings /></MemoryRouter>)
    fireEvent.click(await screen.findByRole('button', { name: 'Pause publishing' }))
    expect(calls).not.toContain('POST /api/worker/pause')
    fireEvent.click(screen.getByRole('button', { name: 'Pause publishing' }))
    expect(await screen.findByRole('button', { name: 'Resume publishing' })).toBeTruthy()
    expect(calls).toContain('POST /api/worker/pause')
    expect(confirm).toHaveBeenCalledTimes(2)
  })

  it.each([
    [downloader({}), 'up', ['1 hour ago']],
    [downloader({ health: { status: 'down', checked_at: HOUR_AGO } }), 'down', []],
    [downloader({ health: { status: 'broken', checked_at: HOUR_AGO, detail: 'HTTP 500' } }), 'broken', ['1 hour ago · HTTP 500']],
    [downloader({ health_configured: false, health: { status: 'not_configured', checked_at: HOUR_AGO } }), 'not configured',
      ['Off: set DOWNLOADER_HEALTH_URL in .env']],
    [downloader({ health: null }), 'not checked yet', []],
    [downloader({ set_up: false, health: null }), 'not set up', ['ig-campaign downloader setup']],
  ] as const)('shows the Reel downloader state %#', async (status, chip, texts) => {
    stubApi({ 'GET /api/downloader/status': [200, status] })
    render(<MemoryRouter><Settings /></MemoryRouter>)
    const dl = section('Reel downloader')
    expect(await within(dl).findByText(chip)).toBeTruthy()
    for (const t of texts) expect(within(dl).getByText((_, el) => el?.tagName === 'DD' && el.textContent?.includes(t) === true)).toBeTruthy()
    expect(within(dl).queryByText('Set it up') === null).toBe(status.set_up)
    expect(within(dl).queryByText('Health check') === null).toBe(status.health_configured)
  })

  it('shows the setup banner, not an error, in setup mode', async () => {
    stubApi({
      'GET /api/health': [200, { status: 'ok', instagram_configured: false, version: '1.2' }],
      'GET /api/account': [200, { configured: false }],
      'GET /api/token': [200, { configured: false, valid: null, expires_at: null, days_left: null, can_refresh: false, scopes: [] }],
    })
    render(<MemoryRouter><Settings /></MemoryRouter>)
    expect(await screen.findByText('Setup mode: add your Instagram token')).toBeTruthy()
    const ig = section('Instagram')
    expect(within(ig).getByText('No')).toBeTruthy()
    expect(within(ig).queryByRole('alert')).toBeNull()
    expect(await within(ig).findByText('No token')).toBeTruthy()
  })
})
