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
  'POST /api/worker/pause': [200, { ...WORKER, paused: true }],
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
    expect(within(ig).getByText('unknown until token care')).toBeTruthy()

    const storage = section('Storage')
    expect(within(storage).getByText('2.5 GB')).toBeTruthy()
    expect(within(storage).getByText('12.0 MB')).toBeTruthy()
    expect(within(storage).getByRole('alert').textContent).toMatch(/Low/)
    expect(within(section('Backups')).getByText('No backups yet')).toBeTruthy()
    expect(screen.queryByText('Setup mode: add your Instagram token')).toBeNull()
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
    })
    render(<Settings />)
    expect(await screen.findByText('Setup mode: add your Instagram token')).toBeTruthy()
    const ig = section('Instagram')
    expect(within(ig).getByText('No')).toBeTruthy()
    expect(within(ig).queryByRole('alert')).toBeNull()
  })
})
