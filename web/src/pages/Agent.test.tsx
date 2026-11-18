import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { AgentRun } from '../api/client'
import Agent from './Agent'

const RUN: AgentRun = {
  id: 7, playbook: 'daily-produce', status: 'succeeded', started_at: '2026-11-17T06:00:00+00:00',
  finished_at: '2026-11-17T06:42:10+00:00', summary: 'Made 10 ideas, 8 renders ready.',
  duration_s: 2530, num_turns: 41, cost_usd: 1.234, permission_denials: 0, has_log: true,
}

const ROUTES: Record<string, [number, unknown]> = {
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
    expect(await within(runs).findByText('Daily videos')).toBeTruthy()
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

  it('confirms before Run now', async () => {
    const calls = stubApi()
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true)
    render(<Agent />)
    const run = await screen.findByRole('button', { name: 'Run daily videos now' })
    fireEvent.click(run)
    expect(confirm.mock.calls[0][0]).toMatch(/Starts a Claude Code run; it uses your plan's usage/)
    expect(calls).not.toContain('POST /api/agent/runs')
    fireEvent.click(run)
    await vi.waitFor(() => expect(calls).toContain('POST /api/agent/runs'))
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('shows 409 as already running', async () => {
    stubApi({ 'POST /api/agent/runs': [409, { error: 'already_running', message: 'run 8' }] })
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    render(<Agent />)
    fireEvent.click(await screen.findByRole('button', { name: 'Run daily videos now' }))
    expect((await screen.findByRole('alert')).textContent).toBe('Daily videos is already running')
  })

  it('disables Run now while that playbook runs', async () => {
    stubApi({ 'GET /api/agent/runs?limit=50': [200, [{ ...RUN, status: 'running', finished_at: null }]] })
    render(<Agent />)
    await screen.findByText('running')
    expect((screen.getByRole('button', { name: 'Run daily videos now' }) as HTMLButtonElement).disabled).toBe(true)
  })
})
