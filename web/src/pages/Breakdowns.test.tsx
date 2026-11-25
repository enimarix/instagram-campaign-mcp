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
const rows = async () => within(await screen.findByRole('list', { name: 'Groupes' })).getAllByRole('listitem')

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('Breakdowns', () => {
  it('shows one bar per group with n, and greys small samples', async () => {
    stubApi()
    show()
    const items = await rows()
    expect(items.map((li) => li.firstElementChild?.textContent)).toEqual(['Question1,5×', 'Bold claim1,25×', 'Sans tag0,75×'])
    expect(within(items[0]).getByText('n = 5 · moitié centrale 1,25×–1,75×')).toBeTruthy()
    expect(within(items[1]).getByText(/n = 2, trop peu pour s’y fier/)).toBeTruthy()
    expect(items[1].className).toContain('text-muted')
    expect(items[0].className).not.toContain('text-muted')
  })

  it('refetches when the tag or post type changes', async () => {
    const fetchMock = stubApi()
    show()
    await rows()
    fireEvent.change(screen.getByRole('combobox', { name: 'Tag' }), { target: { value: 'hour' } })
    expect(fetchMock).toHaveBeenCalledWith('/api/analytics/breakdown?tag=hour&type=REELS&days=90', expect.anything())
    expect(await screen.findByText('18:00')).toBeTruthy()
    fireEvent.change(screen.getByRole('combobox', { name: 'Type de publication' }), { target: { value: 'FEED' } })
    expect(await screen.findByText(/Pas encore de publications mûres de ce type/)).toBeTruthy()
  })

  it('switches the metric, watch ratio only when present', async () => {
    stubApi()
    show()
    await rows()
    fireEvent.click(screen.getByRole('button', { name: 'Portée' }))
    expect(screen.getByRole('button', { name: 'Portée' }).getAttribute('aria-pressed')).toBe('true')
    expect((await rows()).map((li) => li.firstElementChild?.textContent)).toEqual(['Question5 000', 'Bold claim2 000', 'Sans tag4 000'])
    fireEvent.click(screen.getByRole('button', { name: 'Taux de visionnage' }))
    expect((await rows()).map((li) => li.firstElementChild?.textContent)).toEqual(['Question42 %', 'Bold claim–', 'Sans tag–'])
    fireEvent.change(screen.getByRole('combobox', { name: 'Tag' }), { target: { value: 'hour' } })
    expect(await screen.findByText('18:00')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Taux de visionnage' })).toBeNull()
    expect(screen.getByRole('button', { name: 'Indice d’engagement' }).getAttribute('aria-pressed')).toBe('true')
  })

  it('renders an A/B result and switches campaign', async () => {
    stubApi()
    show()
    const ab = screen.getByRole('region', { name: 'Tests A/B' })
    expect(await within(ab).findByText(' : une avance nette.', { exact: false })).toBeTruthy()
    expect(within(ab).getByText('50 %')).toBeTruthy()
    expect(within(ab).getByText('Variante A · en tête')).toBeTruthy()
    expect(within(ab).getByText('Hypothèse : Questions hook better')).toBeTruthy()
    fireEvent.change(within(ab).getByRole('combobox', { name: 'Campagne' }), { target: { value: 'colours' } })
    expect(await within(ab).findByText(/Fewer than 3 matured posts/)).toBeTruthy()
    expect(within(ab).getByText(/pas encore un résultat/)).toBeTruthy()
    expect(within(ab).queryByText(/en tête$/)).toBeNull()
  })

  it('shows the empty state without campaigns', async () => {
    stubApi({ '/api/analytics/campaigns': [] })
    show()
    expect(await screen.findByText('Pas encore de campagnes : marque des publications avec une campagne et une variante.')).toBeTruthy()
  })
})
