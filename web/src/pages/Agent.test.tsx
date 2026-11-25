import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router'
import type { AgentRun, StyleRequest } from '../api/client'
import Agent from './Agent'

const RUN: AgentRun = {
  id: 7, playbook: 'daily-produce', status: 'succeeded', started_at: '2026-11-17T06:00:00+00:00',
  finished_at: '2026-11-17T06:42:10+00:00', summary: 'Made 10 ideas, 8 renders ready.',
  duration_s: 2530, num_turns: 41, cost_usd: 1.234, permission_denials: 0, has_log: true,
}

const REQUEST: StyleRequest = {
  id: 3, kind: 'invented', name: 'Néon nuit', status: 'proposed', owner_note: null, decided_at: null,
  created_at: '2026-11-20T02:10:00+00:00', unblocks: { asset_ids: [12], order_ids: [] },
  concept: {
    look: 'néon sur fond nuit', palette: 'noir, cyan, magenta', motion: 'coupes au rythme', typography: 'grotesk',
    sound: 'synthwave', reference: null, why: 'Les vidéos nettes gagnent', scenes: ['la balance', 'le plat', 'le total'],
  },
}

const ROUTES: Record<string, [number, unknown]> = {
  'GET /api/style-requests': [200, []],
  'GET /api/agent/playbooks': [200, ['daily-produce']],
  'GET /api/agent/runs?limit=50': [200, [RUN]],
  'GET /api/agent/runs/7/log': [200, { id: 7, lines: ['run 7 playbook daily-produce', '--- succeeded'] }],
  'POST /api/agent/runs': [200, { started: true, playbook: 'daily-produce' }],
}

function stubApi(overrides: Record<string, [number, unknown]> = {}) {
  const calls: string[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method ?? 'GET'} ${url}`
    calls.push(key)
    const [status, body] = overrides[key] ?? ROUTES[key] ?? [404, { error: 'not_found' }]
    if (init?.body) calls.push(String(init.body))
    return new Response(JSON.stringify(body), { status })
  }))
  return calls
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('Agent', () => {
  it('lists runs and shows a log tail on demand', async () => {
    stubApi()
    render(<Agent />)
    const runs = await screen.findByRole('region', { name: 'Runs' })
    expect(await within(runs).findByText('Vidéos du jour')).toBeTruthy()
    expect(within(runs).getByText('succeeded')).toBeTruthy()
    expect(within(runs).getByText('42 min 10 s · 41 turns · $1.23')).toBeTruthy()
    expect(within(runs).getByText('Made 10 ideas, 8 renders ready.')).toBeTruthy()
    fireEvent.click(within(runs).getByRole('button', { name: 'Log' }))
    expect((await within(runs).findByText(/--- succeeded/)).tagName).toBe('PRE')
  })

  it('shows the empty-playbooks state', async () => {
    stubApi({ 'GET /api/agent/playbooks': [200, []], 'GET /api/agent/runs?limit=50': [200, []] })
    render(<Agent />)
    expect(await screen.findByText('No playbooks yet')).toBeTruthy()
    expect(await screen.findByText('No runs yet')).toBeTruthy()
  })

  it('confirms before Lancer', async () => {
    const calls = stubApi()
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true)
    render(<Agent />)
    const run = await screen.findByRole('button', { name: 'Lancer\u00a0: Vidéos du jour' })
    fireEvent.click(run)
    expect(confirm.mock.calls[0][0]).toBe(
      'Lancer «\u00a0Vidéos du jour\u00a0» maintenant\u00a0? Ça démarre un run Claude Code, qui utilise le quota de ton abonnement.')
    expect(calls).not.toContain('POST /api/agent/runs')
    fireEvent.click(run)
    await vi.waitFor(() => expect(calls).toContain('POST /api/agent/runs'))
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('shows 409 as already running', async () => {
    stubApi({ 'POST /api/agent/runs': [409, { error: 'already_running', message: 'run 8' }] })
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    render(<Agent />)
    fireEvent.click(await screen.findByRole('button', { name: 'Lancer\u00a0: Vidéos du jour' }))
    expect((await screen.findByRole('alert')).textContent).toBe('Vidéos du jour is already running')
  })

  it('disables Run now while that playbook runs', async () => {
    stubApi({ 'GET /api/agent/runs?limit=50': [200, [{ ...RUN, status: 'running', finished_at: null }]] })
    render(<Agent />)
    await screen.findByText('running')
    expect((screen.getByRole('button', { name: 'Lancer\u00a0: Vidéos du jour' }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('lists the style requests and decides one with a note', async () => {
    const calls = stubApi({
      'GET /api/style-requests': [200, [REQUEST, { ...REQUEST, id: 2, name: 'Danse', kind: 'reference', status: 'live', unblocks: { asset_ids: [], order_ids: [] }, concept: { ...REQUEST.concept, sound: 'tambours' } }]],
      'PATCH /api/style-requests/3': [200, { ...REQUEST, status: 'accepted', owner_note: 'go' }],
    })
    render(<MemoryRouter><Agent /></MemoryRouter>)
    const box = await screen.findByRole('region', { name: 'Style requests' })
    expect(await within(box).findByText('Néon nuit')).toBeTruthy()
    expect(within(box).getByText('inventé')).toBeTruthy()
    expect(within(box).getByText('synthwave')).toBeTruthy()
    expect(within(box).getByRole('link', { name: 'vidéo 12' }).getAttribute('href')).toBe('/assets/12')
    expect(within(box).getAllByRole('button', { name: 'Construire' })).toHaveLength(1) // only the proposed one
    fireEvent.change(within(box).getByLabelText('Note pour Néon nuit'), { target: { value: ' go ' } })
    fireEvent.click(within(box).getByRole('button', { name: 'Construire' }))
    expect(await within(box).findByText('à construire')).toBeTruthy()
    expect(calls).toContain('PATCH /api/style-requests/3')
    expect(calls).toContain(JSON.stringify({ decision: 'accepted', note: 'go' }))
    expect(within(box).queryByRole('button', { name: 'Construire' })).toBeNull()
    expect(within(box).getByText('Ta note : « go »')).toBeTruthy()
  })
})
