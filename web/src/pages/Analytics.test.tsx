import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { AccountDay, AnalyticsPost, Funnel, Taste } from '../api/client'
import { localDate } from '../inbox/ui'
import Analytics from './Analytics'

const ago = (n: number, hour = 12) => {
  const d = new Date()
  d.setDate(d.getDate() - n)
  d.setHours(hour, 0, 0, 0)
  return d
}
const day = (n: number, followers: number): AccountDay => ({
  date: localDate(ago(n)), followers, reach: 100, views: 200,
  deltas: { followers: 10, reach: null, views: null },
})
const post = (n: number, extra: Partial<AnalyticsPost> = {}): AnalyticsPost => ({
  media_id: `m${n}`, permalink: `https://www.instagram.com/reel/${n}/`, posted_at: ago(n).toISOString(),
  group: 'REELS', metrics: { views: 1500, likes: 80 }, caption: `Post ${n}`, deleted: false,
  verdict: 'average', why: null, asset_id: null, ...extra,
})
const ACCOUNT = { since: '', until: '', days: [day(8, 1000), day(1, 1070), day(0, 1080)] }
// today, yesterday, two days ago: a 3-day streak; 9 days ago is not this week
const POSTS = { total: 4, posts: [post(0, { verdict: 'winner', asset_id: 7, thumbnail_url: '/api/media/7/thumb.jpg' }), post(1), post(2), post(9)] }
const FUNNEL: Funnel = {
  since: '', until: '', approval_rate_note: 'capped by MAX_POSTS_PER_DAY',
  totals: { produced: 12, reviewed: 10, liked: 6, approved: 3, published: 2, winner: 1, like_rate: 0.6, approval_rate: 0.3 },
}
const TASTE: Taste = {
  like_rate: [
    { date: '', reviewed: 5, liked: 2, like_rate: 0.4, rolling_7d: 0.4 },
    { date: '', reviewed: 5, liked: 4, like_rate: 0.8, rolling_7d: 0.6 },
  ],
  calibration: {
    days: [{ date: '', scored: 6, top_liked: 3, top_n: 5 }, { date: '', scored: 5, top_liked: 4, top_n: 5 }],
    mean_self_score: { liked: 7.5, disliked: 5.25 },
  },
  waste: { count: 2, render_minutes: 1.5 },
  reasons: [{ code: 'too_long', label: 'Too long', count: 4 }],
}
const EMPTY_TASTE: Taste = {
  like_rate: [{ date: '', reviewed: 0, liked: 0, like_rate: null, rolling_7d: null }],
  calibration: { days: [], mean_self_score: { liked: null, disliked: null } },
  waste: { count: 0, render_minutes: 0 },
  reasons: [],
}

function stubApi(overrides: Record<string, unknown> = {}) {
  const routes: Record<string, unknown> = {
    '/api/analytics/account?days=30': ACCOUNT,
    '/api/analytics/account?days=90': { ...ACCOUNT, days: [day(60, 900), ...ACCOUNT.days] },
    '/api/analytics/posts?limit=100': POSTS,
    '/api/analytics/funnel?days=30': FUNNEL,
    '/api/analytics/taste?days=30': TASTE,
    ...overrides,
  }
  const fetchMock = vi.fn(async (url: string) =>
    routes[url] !== undefined ? new Response(JSON.stringify(routes[url])) : new Response('{"error":"not_found"}', { status: 404 }))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

const show = () => render(<MemoryRouter><Analytics /></MemoryRouter>)

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('Analytics', () => {
  it('renders the KPIs, trends, posts and studio numbers', async () => {
    stubApi()
    show()
    const kpis = screen.getByRole('region', { name: 'This week' })
    expect(await within(kpis).findByText('3 d')).toBeTruthy() // streak
    expect(within(kpis).getByText('1,080')).toBeTruthy()
    expect(within(kpis).getByText('+20 in 7 d')).toBeTruthy()
    expect(within(kpis).getByText('200')).toBeTruthy() // reach: two days in the last 7
    expect(within(kpis).getByText('60 %')).toBeTruthy()
    expect(within(kpis).getByText('1 winner')).toBeTruthy()
    expect(screen.getByRole('link', { name: /^Trends/ }).getAttribute('href')).toBe('/trends')

    expect(screen.getByRole('img', { name: 'Followers: 1,080, +80 over the range' })).toBeTruthy()

    const posts = screen.getByRole('region', { name: "This week's posts" })
    expect(within(posts).getAllByRole('listitem')).toHaveLength(3)
    expect(within(posts).getByText('winner')).toBeTruthy()
    expect(within(posts).getAllByRole('link', { name: 'Details' })[0].getAttribute('href')).toBe('/analytics/posts/m0')
    // ours shows the row's thumbnail (no per-card asset fetch), the others link to Instagram
    expect(posts.querySelector('img')?.getAttribute('src')).toBe('/api/media/7/thumb.jpg')
    expect(within(posts).getAllByRole('link', { name: 'Open on Instagram' })).toHaveLength(2)

    const funnel = within(screen.getByRole('list', { name: 'Funnel' })).getAllByRole('listitem')
    expect(funnel.map((li) => li.textContent)).toEqual(
      ['produced12', 'reviewed10', 'liked6', 'approved3', 'published2', 'winner1'])
    expect(screen.getByRole('img', { name: 'Like-rate, 7-day: 60 %, +20 % over the range' })).toBeTruthy()
    expect(screen.getByText('3.5/5')).toBeTruthy()
    expect(screen.getByText('2 liked videos expired unapproved · 1.5 render minutes')).toBeTruthy()
    expect(screen.getByText('Too long ×4')).toBeTruthy()
  })

  it('shows friendly lines when there is no data', async () => {
    stubApi({
      '/api/analytics/account?days=30': { since: '', until: '', days: [] },
      '/api/analytics/posts?limit=100': { total: 0, posts: [] },
      '/api/analytics/funnel?days=30': { ...FUNNEL, totals: { ...FUNNEL.totals, produced: 0, reviewed: 0, liked: 0, approved: 0, published: 0, winner: 0 } },
      '/api/analytics/taste?days=30': EMPTY_TASTE,
    })
    show()
    expect(await screen.findByText(/No account data yet/)).toBeTruthy()
    expect(await screen.findByText('No posts in the last 7 days.')).toBeTruthy()
    expect(await screen.findByText('No videos in the last 30 days yet.')).toBeTruthy()
    expect(screen.getByText('Nothing reviewed in the last 30 days yet.')).toBeTruthy()
    expect(screen.getByText(/Not enough scored reviews yet/)).toBeTruthy()
    expect(screen.getByText('No feedback reasons yet.')).toBeTruthy()
    expect(screen.getByText('0 d')).toBeTruthy()
    expect(await screen.findByText(/No report yet: the nightly analysis runs at 02:00/)).toBeTruthy()
  })

  it('shows an error line instead of crashing', async () => {
    stubApi({ '/api/analytics/funnel?days=30': undefined })
    show()
    expect(await screen.findByRole('alert')).toBeTruthy()
    expect(await screen.findByText('3.5/5')).toBeTruthy()
  })

  it('refetches the account series when the range changes', async () => {
    const fetchMock = stubApi()
    show()
    await screen.findByRole('img', { name: /^Followers: 1,080/ })
    fireEvent.click(screen.getByRole('button', { name: '90 d' }))
    expect(fetchMock).toHaveBeenCalledWith('/api/analytics/account?days=90', expect.anything())
    expect(await screen.findByRole('img', { name: 'Followers: 1,080, +180 over the range' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '90 d' }).getAttribute('aria-pressed')).toBe('true')
  })

  it('toggles the definitions', async () => {
    stubApi()
    show()
    const help = screen.getByRole('button', { name: 'About Studio funnel' })
    expect(screen.queryByText(/Like-rate = liked \/ reviewed/)).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'About Like-rate' }))
    expect(screen.getByText(/Like-rate = liked \/ reviewed/)).toBeTruthy()
    fireEvent.click(help)
    expect(help.getAttribute('aria-expanded')).toBe('true')
    expect(screen.getByText(/Produced: rendered and checked/)).toBeTruthy()
    fireEvent.click(help)
    expect(screen.queryByText(/Produced: rendered and checked/)).toBeNull()
    await screen.findByText('3.5/5') // let the fetches settle
  })
})
