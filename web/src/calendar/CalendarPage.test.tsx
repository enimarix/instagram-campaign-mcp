import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Calendar, CalendarPost, HotHours } from '../api/client'
import CalendarPage from './CalendarPage'
import { slotLabel } from './when'

const POST: CalendarPost = {
  id: 5, kind: 'reel', status: 'pending', attempts: 0, caption: 'pending one',
  publish_at: '2026-11-18T10:00:00+00:00', local: '2026-11-18T11:00:00+01:00',
  asset_id: 3, preview_url: null, permalink: null, error: null, replanned: false, moved_to: null,
}
const MOVED = { id: 15, publish_at: '2026-11-24T10:54:00+00:00', local: '2026-11-24T11:54:00+01:00' }
const DAYS = ['16', '17', '18', '19', '20', '21', '22'].map((d) => `2026-11-${d}`)

function week(): Calendar {
  const days = DAYS.map((date) => ({ date, posts: [] as CalendarPost[] }))
  days[2].posts = [
    POST,
    { ...POST, id: 6, status: 'published', asset_id: null, permalink: 'https://instagram.com/p/x' },
  ]
  days[3].posts = [
    { ...POST, id: 7, status: 'failed', error: 'boom', local: '2026-11-19T18:00:00+01:00' },
    { ...POST, id: 8, replanned: true, error: 'Re-planned: 40 min late' },
    { ...POST, id: 1, status: 'cancelled', moved_to: MOVED },
  ]
  return {
    days,
    publish_check: [{ id: 9, status: 'publish_check', verdict: 'liked',
      self_score_reason: null, caption: 'lost one', batch_date: '2026-11-17', preview_url: null,
      thumbnail_url: null }],
  }
}

type Call = { method: string; url: string; body: unknown }

function stubApi(routes: Record<string, [number, unknown][]> = {}) {
  const calls: Call[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET'
    calls.push({ method, url, body: init?.body ? JSON.parse(String(init.body)) : undefined })
    const key = `${method} ${url.split('?')[0]}`
    const answers = routes[key] ?? (key === 'GET /api/calendar' ? [[200, week()]] : [[200, { id: 1 }]])
    const [status, body] = answers.length > 1 ? answers.shift()! : answers[0]
    return new Response(JSON.stringify(body), { status })
  }))
  return calls
}

const posts = (calls: Call[]) => calls.filter((c) => c.method === 'POST')

async function page() {
  render(<CalendarPage />, { wrapper: MemoryRouter })
  return screen.findByRole('listitem', { name: 'Post 5' })
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date('2026-11-18T12:00:00')) // a Wednesday
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('CalendarPage', () => {
  it('renders the week with statuses and the right actions', async () => {
    const calls = stubApi()
    await page()
    expect(calls[0].url).toBe('/api/calendar?from=2026-11-16&to=2026-11-22')
    for (const d of DAYS) expect(screen.getByRole('listitem', { name: d })).toBeTruthy()

    const pending = screen.getByRole('listitem', { name: 'Post 5' })
    expect(within(pending).getByText('11:00')).toBeTruthy()
    expect(within(pending).getByRole('link', { name: 'Video 3' }).getAttribute('href')).toBe('/assets/3')
    expect(within(pending).getByRole('button', { name: 'Reschedule' })).toBeTruthy()

    const published = screen.getByRole('listitem', { name: 'Post 6' })
    expect(within(published).getByRole('link', { name: 'On Instagram' }).getAttribute('href'))
      .toBe('https://instagram.com/p/x')
    expect(within(published).queryByRole('button')).toBeNull()

    const failed = screen.getByRole('listitem', { name: 'Post 7' })
    expect(within(failed).getByText('boom')).toBeTruthy()
    expect(within(failed).getByRole('button', { name: 'Re-plan' })).toBeTruthy()

    const late = screen.getByRole('listitem', { name: 'Post 8' })
    expect(within(late).getByText('re-planned')).toBeTruthy()
    expect(within(late).getByText('Re-planned: 40 min late')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'Next week' }))
    await waitFor(() => expect(calls.at(-1)?.url).toBe('/api/calendar?from=2026-11-23&to=2026-11-29'))
  })

  it('cancels after a confirm and reloads', async () => {
    const calls = stubApi()
    const confirm = vi.fn(() => true)
    vi.stubGlobal('confirm', confirm)
    const card = await page()
    fireEvent.click(within(card).getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(calls.filter((c) => c.method === 'GET')).toHaveLength(2))
    expect(posts(calls)).toEqual([{ method: 'POST', url: '/api/posts/5/cancel', body: undefined }])
    expect(confirm).toHaveBeenCalledOnce()
  })

  it('a re-planned card says where the video went and shows that week', async () => {
    const calls = stubApi()
    await page()
    const card = screen.getByRole('listitem', { name: 'Post 1' })
    expect(card.textContent).toContain('Re-planned →')
    expect(within(card).queryByRole('button', { name: /Re-plan$|Reschedule|Cancel/ })).toBeNull()
    fireEvent.click(within(card).getByRole('button', { name: slotLabel(MOVED.local) }))
    expect(slotLabel(MOVED.local)).toMatch(/24.*11:54$/)
    await waitFor(() => expect(calls.at(-1)?.url).toBe('/api/calendar?from=2026-11-23&to=2026-11-29'))
  })

  it('reschedules from the hot-hours picker, minutes still editable', async () => {
    const hour = (h: number, extra: object) => ({
      hour: h, publish_at: new Date(`2026-11-20T${h}:00`).toISOString(), local: `2026-11-20T${h}:00:00+01:00`,
      followers: 10, score: 0.2, hot: false, taken: [] as number[], ...extra,
    })
    const grid: HotHours = { has_data: true, posting_windows: '11:00-13:00', days: [
      { date: '2026-11-20', hours: [hour(17, {}), hour(18, { score: 1, hot: true, followers: 90 }), hour(19, { taken: [99] }),
        hour(20, { taken: [5] })] },
    ] }
    HTMLDialogElement.prototype.showModal = function () { this.open = true }
    const calls = stubApi({ 'GET /api/calendar/hot-hours': [[200, grid]] })
    const card = await page()
    fireEvent.click(within(card).getByRole('button', { name: 'Reschedule' }))
    const dialog = await screen.findByRole('dialog', { name: 'Reschedule' })
    expect(calls.map((c) => c.url)).toContain('/api/calendar/hot-hours?days=14')
    expect(within(dialog).getByText(/most followers online/)).toBeTruthy()
    const hot = await within(dialog).findByRole('button', { name: '18:00 hot' })
    expect(hot.textContent).toContain('🔥')
    expect(within(dialog).getByRole('button', { name: '17:00' }).textContent).not.toContain('🔥')
    expect((within(dialog).getByRole('button', { name: '19:00 taken' }) as HTMLButtonElement).disabled).toBe(true)
    // its own slot is not "taken" for the post being moved
    expect((within(dialog).getByRole('button', { name: '20:00' }) as HTMLButtonElement).disabled).toBe(false)

    fireEvent.click(hot)
    const input = within(dialog).getByLabelText('New time') as HTMLInputElement
    expect(input.value).toBe('2026-11-20T18:00')
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(posts(calls)).toEqual([{ method: 'POST', url: '/api/posts/5/reschedule',
      body: { publish_at: new Date('2026-11-20T18:00').toISOString() } }]))

    fireEvent.click(within(card).getByRole('button', { name: 'Reschedule' }))
    const again = await screen.findByRole('dialog', { name: 'Reschedule' })
    fireEvent.change(within(again).getByLabelText('New time'), { target: { value: '2026-11-20T18:35' } })
    fireEvent.click(within(again).getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(posts(calls).at(-1)?.body).toEqual({ publish_at: new Date('2026-11-20T18:35').toISOString() }))
  })

  it('says when there is no audience data yet', async () => {
    HTMLDialogElement.prototype.showModal = function () { this.open = true }
    stubApi({ 'GET /api/calendar/hot-hours': [[200, { has_data: false, posting_windows: '11:00-13:00', days: [] }]] })
    const card = await page()
    fireEvent.click(within(card).getByRole('button', { name: 'Reschedule' }))
    expect(await screen.findByText(/No audience data yet.*11:00-13:00/)).toBeTruthy()
  })

  it('tells where a re-planned video went', async () => {
    stubApi({ 'POST /api/posts/7/replan': [[200, { status: 'pending', ...MOVED }]] })
    await page()
    fireEvent.click(screen.getByRole('button', { name: 'Re-plan' }))
    const status = await screen.findByRole('status')
    expect(status.textContent).toContain(`Re-planned for ${slotLabel(MOVED.local)}`)
    expect(status.textContent).toContain('to pick another time')
  })

  it('re-plans a commentary clip after the rights check', async () => {
    const calls = stubApi({
      'POST /api/posts/7/replan': [[409, { error: 'rights', message: 'needs your check' }], [200, { status: 'pending', ...MOVED }]],
    })
    vi.stubGlobal('confirm', vi.fn(() => true))
    await page()
    fireEvent.click(screen.getByRole('button', { name: 'Re-plan' }))
    await waitFor(() => expect(posts(calls).map((c) => c.body)).toEqual([{ confirmed: false }, { confirmed: true }]))
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('releases a publish_check video only after the confirm', async () => {
    const calls = stubApi()
    const confirm = vi.fn(() => false)
    vi.stubGlobal('confirm', confirm)
    await page()
    const row = screen.getByRole('listitem', { name: 'Video 9' })
    const release = within(row).getByRole('button', { name: 'Not on Instagram → release' })
    fireEvent.click(release)
    expect(confirm.mock.calls[0]).toEqual([expect.stringContaining('I checked: it is not on Instagram')])
    expect(posts(calls)).toEqual([])
    confirm.mockReturnValue(true)
    fireEvent.click(release)
    await waitFor(() => expect(posts(calls).map((c) => c.url)).toEqual(['/api/assets/9/release']))
  })

  it("shows the server's refusal", async () => {
    stubApi({ 'POST /api/posts/7/replan': [[409, { error: 'not_approved', message: 'asset 3 is publish_check' }]] })
    await page()
    fireEvent.click(screen.getByRole('button', { name: 'Re-plan' }))
    expect((await screen.findByRole('alert')).textContent).toBe('asset 3 is publish_check')
  })
})
