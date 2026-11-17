import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { WorkerStatus } from '../api/client'
import Settings from './Settings'

const WORKER: WorkerStatus = {
  heartbeat_at: new Date(Date.now() - 3 * 60_000).toISOString(),
  alive: true,
  paused: false,
  next_slot: '2026-11-18T18:10:00+00:00',
  last_result: { published: [{ id: 1 }], failed: [], retrying: [], replanned: [], paused: false },
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
    render(<Settings />)
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
    const next = new Date('2026-11-18T03:00:00+01:00').toLocaleString()
    expect(within(agent).getByText('daily-produce at 03:00')).toBeTruthy()
    expect(within(agent).getByText(`Next ${next} · last failed 2 hours ago`)).toBeTruthy()
    expect(within(agent).getByText('Playbook not written yet · never ran')).toBeTruthy()
    expect(screen.queryByText('Setup mode: add your Instagram token')).toBeNull()
  })

  it('says so when no agent run is scheduled', async () => {
    stubApi({ 'GET /api/agent/schedule': [200, []] })
    render(<Settings />)
    expect(await within(section('Agent schedule')).findByText('None (AGENT_SCHEDULE is empty)')).toBeTruthy()
  })

  it('pauses publishing after a confirm', async () => {
    const calls = stubApi()
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true)
    render(<Settings />)
    fireEvent.click(await screen.findByRole('button', { name: 'Pause publishing' }))
    expect(calls).not.toContain('POST /api/worker/pause')
    fireEvent.click(screen.getByRole('button', { name: 'Pause publishing' }))
    expect(await screen.findByRole('button', { name: 'Resume publishing' })).toBeTruthy()
    expect(calls).toContain('POST /api/worker/pause')
    expect(confirm).toHaveBeenCalledTimes(2)
  })

  it('shows the setup banner, not an error, in setup mode', async () => {
    stubApi({
      'GET /api/health': [200, { status: 'ok', instagram_configured: false, version: '1.2' }],
      'GET /api/account': [503, { error: 'instagram_not_configured' }],
      'GET /api/token': [200, { configured: false, valid: null, expires_at: null, days_left: null, can_refresh: false, scopes: [] }],
    })
    render(<Settings />)
    expect(await screen.findByText('Setup mode: add your Instagram token')).toBeTruthy()
    const ig = section('Instagram')
    expect(within(ig).getByText('No')).toBeTruthy()
    expect(within(ig).queryByRole('alert')).toBeNull()
    expect(await within(ig).findByText('No token')).toBeTruthy()
  })
})
