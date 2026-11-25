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
  waste: { count: 2, render_minutes: 1.5 },
  reasons: [{ code: 'too_long', label: 'Too long', count: 4 }],
}
const EMPTY_TASTE: Taste = {
  like_rate: [{ date: '', reviewed: 0, liked: 0, like_rate: null, rolling_7d: null }],
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
    const kpis = screen.getByRole('region', { name: 'Cette semaine' })
    expect(await within(kpis).findByText('3 j')).toBeTruthy() // streak
    expect(within(kpis).getByText('1 080')).toBeTruthy()
    expect(within(kpis).getByText('+20 en 7 j')).toBeTruthy()
    expect(within(kpis).getByText('200')).toBeTruthy() // reach: two days in the last 7
    expect(within(kpis).getByText('60 %')).toBeTruthy()
    expect(within(kpis).getByText('1 gagnante')).toBeTruthy()
    expect(screen.getByRole('link', { name: /^Tendances/ }).getAttribute('href')).toBe('/trends')

    expect(screen.getByRole('img', { name: 'Abonnés : 1 080, +80 sur la période' })).toBeTruthy()

    const posts = screen.getByRole('region', { name: 'Publications de la semaine' })
    expect(within(posts).getAllByRole('listitem')).toHaveLength(3)
    expect(within(posts).getByText('gagnante')).toBeTruthy()
    expect(within(posts).getAllByRole('link', { name: 'Détails' })[0].getAttribute('href')).toBe('/analytics/posts/m0')
    // ours shows the row's thumbnail (no per-card asset fetch), the others link to Instagram
    expect(posts.querySelector('img')?.getAttribute('src')).toBe('/api/media/7/thumb.jpg')
    expect(within(posts).getAllByRole('link', { name: 'Ouvrir sur Instagram' })).toHaveLength(2)

    const funnel = within(screen.getByRole('list', { name: 'Entonnoir' })).getAllByRole('listitem')
    expect(funnel.map((li) => li.textContent)).toEqual(
      ['Produites12', 'Revues10', 'Gardées6', 'Approuvées3', 'Publiées2', 'Gagnantes1'])
    expect(screen.getByRole('img', { name: 'Taux de like sur 7 jours : 60 %, +20 % sur la période' })).toBeTruthy()
    expect(screen.queryByText('Calibration')).toBeNull() // 189: the agent no longer scores itself
    expect(screen.getByText('2 vidéos gardées expirées sans approbation · 1,5 minutes de rendu')).toBeTruthy()
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
    expect(await screen.findByText(/Pas encore de données du compte/)).toBeTruthy()
    expect(await screen.findByText('Aucune publication ces 7 derniers jours.')).toBeTruthy()
    expect(await screen.findByText('Pas encore de vidéos ces 30 derniers jours.')).toBeTruthy()
    expect(screen.getByText('Rien de revu ces 30 derniers jours.')).toBeTruthy()
    expect(screen.getByText('Pas encore de raisons de retour.')).toBeTruthy()
    expect(screen.getByText('0 j')).toBeTruthy()
    expect(await screen.findByText(/Pas encore de rapport : l’analyse de nuit tourne à 02:00/)).toBeTruthy()
  })

  it('shows an error line instead of crashing', async () => {
    stubApi({ '/api/analytics/funnel?days=30': undefined })
    show()
    expect(await screen.findByRole('alert')).toBeTruthy()
    expect(await screen.findByText('2 vidéos gardées expirées sans approbation · 1,5 minutes de rendu')).toBeTruthy()
  })

  it('refetches the account series when the range changes', async () => {
    const fetchMock = stubApi()
    show()
    await screen.findByRole('img', { name: /^Abonnés : 1 080/ })
    fireEvent.click(screen.getByRole('button', { name: '90 j' }))
    expect(fetchMock).toHaveBeenCalledWith('/api/analytics/account?days=90', expect.anything())
    expect(await screen.findByRole('img', { name: 'Abonnés : 1 080, +180 sur la période' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '90 j' }).getAttribute('aria-pressed')).toBe('true')
  })

  it('toggles the definitions', async () => {
    stubApi()
    show()
    const help = screen.getByRole('button', { name: 'Aide : Entonnoir du studio' })
    expect(screen.queryByText(/Taux de like = gardées \/ revues/)).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Aide : Taux de like' }))
    expect(screen.getByText(/Taux de like = gardées \/ revues/)).toBeTruthy()
    fireEvent.click(help)
    expect(help.getAttribute('aria-expanded')).toBe('true')
    expect(screen.getByText(/Produites : rendues et vérifiées/)).toBeTruthy()
    fireEvent.click(help)
    expect(screen.queryByText(/Produites : rendues et vérifiées/)).toBeNull()
    await screen.findByText('2 vidéos gardées expirées sans approbation · 1,5 minutes de rendu') // let the fetches settle
  })
})
