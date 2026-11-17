import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { DmPick, PinnedAccount } from '../api/client'
import DmPicksSection from './DmPicks'

const ACCOUNT: PinnedAccount = { id: 3, username: 'friend', ig_user_id: null, note: 'my sister', created_at: '2026-11-17T10:00:00Z' }
const pick = (over: Partial<DmPick>): DmPick => ({
  id: 1, pinned_account_id: 3, sender_username: 'friend', reel_url: 'https://www.instagram.com/reel/abc/',
  reel_media_id: null, sender_note: null, received_at: '2026-11-16T10:00:00Z', status: 'new', skip_reason: null,
  source_id: null, created_at: '2026-11-16T10:00:00Z', updated_at: '2026-11-16T10:00:00Z', ...over,
})

type Route = [number, unknown]
function stubApi(routes: Record<string, Route | Route[]>) {
  const calls: { key: string; body: unknown }[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method ?? 'GET'} ${url}`
    calls.push({ key, body: init?.body ? JSON.parse(String(init.body)) : undefined })
    const r = routes[key] ?? [404, { error: 'not_found' }]
    // a list of answers: one per call, the last one repeats
    const [status, body] = Array.isArray(r[0]) ? ((r as Route[]).length > 1 ? (r as Route[]).shift()! : (r as Route[])[0]) : (r as Route)
    return new Response(status === 204 ? null : JSON.stringify(body), { status })
  }))
  return calls
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('DmPicksSection', () => {
  it('shows empty states and the DM permission line', async () => {
    stubApi({ 'GET /api/pinned-accounts': [200, []], 'GET /api/dm-picks': [200, []] })
    render(<DmPicksSection />)
    expect(await screen.findByText('No pinned accounts yet: pin one below.')).toBeTruthy()
    expect(screen.getByText('No picks yet')).toBeTruthy()
    expect(screen.getByText('instagram_manage_messages')).toBeTruthy()
  })

  it('pins an account and shows the server error', async () => {
    const calls = stubApi({
      'GET /api/pinned-accounts': [[200, []], [200, [ACCOUNT]]],
      'GET /api/dm-picks': [200, []],
      'POST /api/pinned-accounts': [[422, { error: 'invalid', message: "not an Instagram username: 'bad name'" }], [200, ACCOUNT]],
    })
    render(<DmPicksSection />)
    const form = await screen.findByRole('form', { name: 'Pin an account' })
    fireEvent.change(within(form).getByLabelText('Instagram username'), { target: { value: 'bad name' } })
    fireEvent.click(within(form).getByRole('button', { name: 'Pin' }))
    expect((await screen.findByRole('alert')).textContent).toBe("not an Instagram username: 'bad name'")

    fireEvent.change(within(form).getByLabelText('Instagram username'), { target: { value: '@Friend' } })
    fireEvent.change(within(form).getByLabelText('Note (optional)'), { target: { value: 'my sister' } })
    fireEvent.click(within(form).getByRole('button', { name: 'Pin' }))
    const list = await screen.findByRole('list', { name: 'Pinned accounts' })
    expect(list.textContent).toBe('@friend · my sister')
    expect(calls.filter((c) => c.key === 'POST /api/pinned-accounts').at(-1)?.body).toEqual({ username: '@Friend', note: 'my sister' })
    expect(screen.queryByRole('alert')).toBeNull()
    expect((within(form).getByLabelText('Instagram username') as HTMLInputElement).value).toBe('')
  })

  it('unpins only after the confirm', async () => {
    const calls = stubApi({
      'GET /api/pinned-accounts': [[200, [ACCOUNT]], [200, []]],
      'GET /api/dm-picks': [200, []],
      'DELETE /api/pinned-accounts/3': [204, null],
    })
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true)
    render(<DmPicksSection />)
    const unpin = await screen.findByRole('button', { name: 'Unpin @friend' })
    fireEvent.click(unpin)
    expect(calls.some((c) => c.key.startsWith('DELETE'))).toBe(false)
    fireEvent.click(unpin)
    expect(await screen.findByText('No pinned accounts yet: pin one below.')).toBeTruthy()
    expect(confirm).toHaveBeenCalledTimes(2)
    expect(calls.map((c) => c.key)).toContain('DELETE /api/pinned-accounts/3')
  })

  it('lists picks as the API orders them (newest first) and skips a new one with a reason', async () => {
    const older = pick({ id: 1, sender_note: 'so funny', received_at: '2026-11-15T10:00:00Z' })
    const skipped = pick({ id: 2, status: 'skipped', skip_reason: 'not a Reel', received_at: '2026-11-16T10:00:00Z' })
    const calls = stubApi({
      'GET /api/pinned-accounts': [200, [ACCOUNT]],
      'GET /api/dm-picks': [[200, [skipped, older]], [200, [skipped, { ...older, status: 'skipped', skip_reason: 'too long' }]]],
      'POST /api/dm-picks/1/skip': [200, { ...older, status: 'skipped' }],
    })
    render(<DmPicksSection />)
    const list = await screen.findByRole('list', { name: 'Picks' })
    const rows = within(list).getAllByRole('listitem')
    expect(within(rows[0]).getByText('Skipped: not a Reel')).toBeTruthy()
    expect(within(rows[1]).getByText('so funny').tagName).toBe('Q')
    expect(within(rows[1]).getByRole('link', { name: 'Open Reel' }).getAttribute('href')).toBe('https://www.instagram.com/reel/abc/')
    expect(within(rows[0]).queryByRole('button', { name: 'Skip' })).toBeNull()

    fireEvent.click(within(rows[1]).getByRole('button', { name: 'Skip' }))
    const form = screen.getByRole('form', { name: 'Skip pick from @friend' })
    fireEvent.change(within(form).getByLabelText('Why skip it?'), { target: { value: 'too long' } })
    fireEvent.click(within(form).getByRole('button', { name: 'Skip pick' }))
    expect(await screen.findByText('Skipped: too long')).toBeTruthy()
    expect(calls.find((c) => c.key === 'POST /api/dm-picks/1/skip')?.body).toEqual({ reason: 'too long' })
    expect(screen.queryByRole('button', { name: 'Skip' })).toBeNull()
  })
})
