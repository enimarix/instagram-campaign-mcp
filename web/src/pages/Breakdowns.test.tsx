import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { AbResult, Breakdown, BreakdownGroup } from '../api/client'
import Breakdowns from './Breakdowns'

const group = (tag_value: string | number, n: number, median: number, extra: Partial<BreakdownGroup> = {}): BreakdownGroup => ({
  tag_value, n, small_sample: n < 3, engagement_index: { median, p25: median - 0.25, p75: median + 0.25 },
  reach: { median: n * 1000 }, views: { median: n * 2000 }, ...extra,
})
const breakdown = (tag: string, post_type: string, groups: BreakdownGroup[]): Breakdown => ({ tag, post_type, days: 90, since: '', groups })
const HOOKS = breakdown('hook_type', 'REELS', [
  group('question', 5, 1.5, { watch_ratio: { median: 0.42 } }), group('bold_claim', 2, 1.25), group('untagged', 4, 0.75),
])
const AB: AbResult = {
  campaign: 'hooks', leader: 'A', note: null,
  variants: [
    { variant: 'A', posts: 4, avg_engagement_index: 1.5, avg_reach: 1200, winners: 2, hypothesis: 'Questions hook better' },
    { variant: 'B', posts: 3, avg_engagement_index: 1, avg_reach: 900, winners: 0, hypothesis: null },
  ],
}
const THIN: AbResult = {
  campaign: 'colours', leader: null, note: 'Fewer than 3 matured posts in some variant: treat the leader as a hint.',
  variants: [AB.variants[0], { ...AB.variants[1], posts: 1 }],
}

function stubApi(overrides: Record<string, unknown> = {}) {
  const routes: Record<string, unknown> = {
    '/api/analytics/breakdown?tag=hook_type&type=REELS&days=90': HOOKS,
    '/api/analytics/breakdown?tag=hour&type=REELS&days=90': breakdown('hour', 'REELS', [group(18, 6, 1.1)]),
    '/api/analytics/breakdown?tag=hour&type=FEED&days=90': breakdown('hour', 'FEED', []),
    '/api/analytics/campaigns': ['hooks', 'colours'],
    '/api/analytics/ab?campaign=hooks': AB,
    '/api/analytics/ab?campaign=colours': THIN,
    ...overrides,
  }
  const fetchMock = vi.fn(async (url: string) =>
    routes[url] !== undefined ? new Response(JSON.stringify(routes[url])) : new Response('{"error":"not_found"}', { status: 404 }))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

const show = () => render(<MemoryRouter><Breakdowns /></MemoryRouter>)
const rows = async () => within(await screen.findByRole('list', { name: 'Groups' })).getAllByRole('listitem')

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('Breakdowns', () => {
  it('shows one bar per group with n, and greys small samples', async () => {
    stubApi()
    show()
    const items = await rows()
    expect(items.map((li) => li.firstElementChild?.textContent)).toEqual(['question1.5×', 'bold_claim1.25×', 'untagged0.75×'])
    expect(within(items[0]).getByText('n = 5 · middle half 1.25×–1.75×')).toBeTruthy()
    expect(within(items[1]).getByText(/n = 2, too few to trust/)).toBeTruthy()
    expect(items[1].className).toContain('text-gray-500')
    expect(items[0].className).not.toContain('text-gray-500')
  })

  it('refetches when the tag or post type changes', async () => {
    const fetchMock = stubApi()
    show()
    await rows()
    fireEvent.change(screen.getByRole('combobox', { name: 'Tag' }), { target: { value: 'hour' } })
    expect(fetchMock).toHaveBeenCalledWith('/api/analytics/breakdown?tag=hour&type=REELS&days=90', expect.anything())
    expect(await screen.findByText('18:00')).toBeTruthy()
    fireEvent.change(screen.getByRole('combobox', { name: 'Post type' }), { target: { value: 'FEED' } })
    expect(await screen.findByText(/No matured posts of this type/)).toBeTruthy()
  })

  it('switches the metric, watch ratio only when present', async () => {
    stubApi()
    show()
    await rows()
    fireEvent.click(screen.getByRole('button', { name: 'Reach' }))
    expect(screen.getByRole('button', { name: 'Reach' }).getAttribute('aria-pressed')).toBe('true')
    expect((await rows()).map((li) => li.firstElementChild?.textContent)).toEqual(['question5,000', 'bold_claim2,000', 'untagged4,000'])
    fireEvent.click(screen.getByRole('button', { name: 'Watch ratio' }))
    expect((await rows()).map((li) => li.firstElementChild?.textContent)).toEqual(['question42 %', 'bold_claim–', 'untagged–'])
    fireEvent.change(screen.getByRole('combobox', { name: 'Tag' }), { target: { value: 'hour' } })
    expect(await screen.findByText('18:00')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Watch ratio' })).toBeNull()
    expect(screen.getByRole('button', { name: 'Engagement index' }).getAttribute('aria-pressed')).toBe('true')
  })

  it('renders an A/B result and switches campaign', async () => {
    stubApi()
    show()
    const ab = screen.getByRole('region', { name: 'A/B tests' })
    expect(await within(ab).findByText(': a clear lead.', { exact: false })).toBeTruthy()
    expect(within(ab).getByText('50 %')).toBeTruthy()
    expect(within(ab).getByText('Variant A · leader')).toBeTruthy()
    expect(within(ab).getByText('Hypothesis: Questions hook better')).toBeTruthy()
    fireEvent.change(within(ab).getByRole('combobox', { name: 'Campaign' }), { target: { value: 'colours' } })
    expect(await within(ab).findByText(/Fewer than 3 matured posts/)).toBeTruthy()
    expect(within(ab).getByText(/not yet a result/)).toBeTruthy()
    expect(within(ab).queryByText(/leader$/)).toBeNull()
  })

  it('shows the empty state without campaigns', async () => {
    stubApi({ '/api/analytics/campaigns': [] })
    show()
    expect(await screen.findByText('No campaigns yet: label posts with a campaign and variant.')).toBeTruthy()
  })
})
