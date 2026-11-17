import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Inspiration, TrendItem, TrendReport, Watch } from '../api/client'
import Trends from './Trends'

const ITEM: TrendItem = {
  source_id: 1, ranked_within: 'account', account: 'rival', url: 'https://www.instagram.com/reel/A/',
  posted_at: '2026-11-16T11:00:00+00:00', hour: 12, duration_s: null, outlier: 6, metric: 'views',
  median: 250, outlier_note: null, hook_quote: 'Stop doing this squat mistake', hashtags: ['fitness', 'gym'],
}
const REPORT: TrendReport = {
  accounts: [ITEM],
  hashtags: {
    gym: [{
      ...ITEM, source_id: 2, ranked_within: 'hashtag', account: undefined, hashtag: 'gym',
      url: 'javascript:alert(1)', outlier: null, metric: 'likes', median: null,
      outlier_note: 'only 1 hashtag posts with likes (need 5)', hook_quote: null, hashtags: [],
    }],
  },
  generated_at: '2026-11-17T12:00:00+00:00',
}
const WATCH: Watch[] = [{ id: 3, kind: 'hashtag', value: 'fitness', note: null }]
const INSP: Inspiration[] = [
  { id: 7, url: 'https://www.instagram.com/reel/C1/', note: 'this format is funny', status: 'new',
    created_at: '2026-11-17T08:00:00+00:00', used_at: null },
  { id: 6, url: 'javascript:alert(1)', note: null, status: 'dismissed',
    created_at: '2026-11-16T08:00:00+00:00', used_at: null },
]

function stubApi(overrides: Record<string, [number, unknown]> = {}) {
  const calls: { key: string; body?: unknown }[] = []
  const routes: Record<string, [number, unknown]> = {
    'GET /api/trends?days=14': [200, REPORT],
    'GET /api/watchlist': [200, WATCH],
    'POST /api/watchlist': [200, { id: 4, kind: 'account', value: 'rival', note: null }],
    'DELETE /api/watchlist/3': [204, null],
    'GET /api/inspirations': [200, INSP],
    'POST /api/inspirations': [200, INSP[0]],
    'PATCH /api/inspirations/7': [200, { ...INSP[0], status: 'dismissed' }],
    'DELETE /api/inspirations/6': [204, null],
    ...overrides,
  }
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method ?? 'GET'} ${url}`
    calls.push({ key, body: init?.body ? JSON.parse(init.body as string) : undefined })
    const [status, body] = routes[key] ?? [404, { error: 'not_found' }]
    return new Response(status === 204 ? null : JSON.stringify(body), { status })
  }))
  return calls
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('Trends', () => {
  it('shows ranked cards that open Instagram in a new tab', async () => {
    stubApi()
    render(<Trends />)
    const report = await screen.findByRole('region', { name: 'Trend report' })
    expect(await within(report).findByText('@rival')).toBeTruthy()
    expect(within(report).getByText('×6 views')).toBeTruthy()
    expect(within(report).getByText('Stop doing this squat mistake').tagName).toBe('Q')
    expect(within(report).getByText('#fitness #gym')).toBeTruthy()
    expect(within(report).getAllByText('posted 12:00')).toHaveLength(2)
    const links = within(report).getAllByRole('link', { name: 'Open on Instagram' })
    expect(links).toHaveLength(1) // the javascript: URL is not rendered
    expect(links[0].getAttribute('href')).toBe(ITEM.url)
    expect(links[0].getAttribute('target')).toBe('_blank')
    expect(links[0].getAttribute('rel')).toBe('noopener noreferrer')
    const gym = within(report).getByRole('region', { name: '#gym' })
    expect(within(gym).getByText('no score')).toBeTruthy()
    expect(within(gym).getByText('only 1 hashtag posts with likes (need 5)')).toBeTruthy()
  })

  it('shows the empty state', async () => {
    stubApi({ 'GET /api/trends?days=14': [200, { accounts: [], hashtags: {}, generated_at: '' }],
      'GET /api/watchlist': [200, []] })
    render(<Trends />)
    expect(await screen.findByText(/No trends yet/)).toBeTruthy()
    expect(await screen.findByText('Nothing watched yet')).toBeTruthy()
  })

  it('adds and removes watchlist entries', async () => {
    const calls = stubApi()
    render(<Trends />)
    const list = await screen.findByRole('region', { name: 'Watchlist' })
    fireEvent.click(await within(list).findByRole('button', { name: 'Remove #fitness' }))
    await vi.waitFor(() => expect(calls.map((c) => c.key)).toContain('DELETE /api/watchlist/3'))
    fireEvent.change(within(list).getByLabelText('Kind'), { target: { value: 'account' } })
    fireEvent.change(within(list).getByLabelText('Hashtag or username'), { target: { value: ' @Rival ' } })
    fireEvent.click(within(list).getByRole('button', { name: 'Add' }))
    await vi.waitFor(() => expect(calls.find((c) => c.key === 'POST /api/watchlist')?.body)
      .toEqual({ kind: 'account', value: '@Rival' }))
    await vi.waitFor(() => expect((within(list).getByLabelText('Hashtag or username') as HTMLInputElement).value).toBe(''))
    expect(calls.filter((c) => c.key === 'GET /api/watchlist')).toHaveLength(3) // reloaded after each
  })

  it('shows a refused entry', async () => {
    stubApi({ 'POST /api/watchlist': [422, { error: 'invalid', message: 'not a valid hashtag' }] })
    render(<Trends />)
    const list = await screen.findByRole('region', { name: 'Watchlist' })
    fireEvent.change(within(list).getByLabelText('Hashtag or username'), { target: { value: 'two words' } })
    fireEvent.click(within(list).getByRole('button', { name: 'Add' }))
    expect((await within(list).findByRole('alert')).textContent).toBe('not a valid hashtag')
  })

  it('lists inspirations with a safe Open link, dismiss and delete', async () => {
    const calls = stubApi()
    render(<Trends />)
    const box = await screen.findByRole('region', { name: 'Inspirations' })
    const [first, second] = await within(box).findAllByRole('listitem')
    expect(within(first).getByText('this format is funny')).toBeTruthy()
    expect(within(first).getByText('new')).toBeTruthy()
    const open = within(first).getByRole('link', { name: 'Open' })
    expect(open.getAttribute('href')).toBe(INSP[0].url)
    expect(open.getAttribute('target')).toBe('_blank')
    expect(open.getAttribute('rel')).toBe('noopener noreferrer')
    expect(within(second).queryByRole('link')).toBeNull() // javascript: is never a link
    expect(within(second).queryByRole('button', { name: 'Dismiss' })).toBeNull()
    fireEvent.click(within(first).getByRole('button', { name: 'Dismiss' }))
    await vi.waitFor(() => expect(calls.find((c) => c.key === 'PATCH /api/inspirations/7')?.body)
      .toEqual({ status: 'dismissed' }))
    fireEvent.click(within(second).getByRole('button', { name: 'Delete' }))
    await vi.waitFor(() => expect(calls.map((c) => c.key)).toContain('DELETE /api/inspirations/6'))
  })

  it('adds an inspiration', async () => {
    const calls = stubApi()
    render(<Trends />)
    const box = await screen.findByRole('region', { name: 'Inspirations' })
    fireEvent.change(within(box).getByLabelText('Reel link'), { target: { value: ' https://www.instagram.com/reel/C2/?igsh=x ' } })
    fireEvent.change(within(box).getByLabelText('Note'), { target: { value: 'react to this' } })
    fireEvent.click(within(box).getByRole('button', { name: 'Add' }))
    await vi.waitFor(() => expect(calls.find((c) => c.key === 'POST /api/inspirations')?.body)
      .toEqual({ url: 'https://www.instagram.com/reel/C2/?igsh=x', note: 'react to this' }))
    await vi.waitFor(() => expect((within(box).getByLabelText('Reel link') as HTMLInputElement).value).toBe(''))
    expect((within(box).getByLabelText('Note') as HTMLInputElement).value).toBe('')
  })

  it('shows a refused inspiration link', async () => {
    stubApi({ 'POST /api/inspirations': [422, { error: 'invalid', message: 'paste an Instagram Reel or post link' }] })
    render(<Trends />)
    const box = await screen.findByRole('region', { name: 'Inspirations' })
    fireEvent.change(within(box).getByLabelText('Reel link'), { target: { value: 'https://x.com/a' } })
    fireEvent.click(within(box).getByRole('button', { name: 'Add' }))
    expect((await within(box).findByRole('alert')).textContent).toBe('paste an Instagram Reel or post link')
  })
})
