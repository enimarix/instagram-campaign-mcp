import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { AnalyticsPost, PostDetail } from '../api/client'
import Posts, { PostPage } from './Posts'

const post = (i: number, extra: Partial<AnalyticsPost> = {}): AnalyticsPost => ({
  media_id: `m${i}`, permalink: `https://www.instagram.com/reel/${i}/`, posted_at: '2026-11-10T12:00:00Z',
  group: 'REELS', metrics: { views: 1000 + i, reach: 500 }, caption: `Post ${i}`, deleted: false,
  verdict: 'average', why: null, asset_id: null, engagement_index: 1.2, watch_ratio: 0.35, view_rate: 2, ...extra,
})
const ALL = Array.from({ length: 25 }, (_, i) => post(i, i === 0 ? { asset_id: 7, thumbnail_url: '/api/media/7/thumb.jpg' } : i === 1 ? { group: 'TRIAL' } : {}))

const DETAIL: PostDetail = {
  ...post(0, { asset_id: 7, preview_url: '/api/media/7/preview.mp4', thumbnail_url: '/api/media/7/thumb.jpg' }),
  tags: { track: 'motion', pillar: 'myths', hook_type: 'question', strategy: null, template: 'FactQuest' },
  hypothesis: 'questions hook better',
  feedback: [{ id: 1, text: 'love the ending', reason_codes: [], video_time_s: null, wants_changes: 0, created_at: '2026-11-11T09:00:00Z' }],
  series: [1, 24, 72].map((h, i) => ({ captured_at: `t${h}`, age_hours: h, metrics: { views: 100 * (i + 1), reach: 50 * (i + 1) } })),
  description: 'A pixel knight busts three water myths.',
  timeline: [{ t: 0, d: 3, e: 'hook: myth card' }, { t: 3, d: 12, e: 'fact 1' }, { t: 15, d: 15, e: 'fact 2: water' }, { e: '+2 more' }],
  duration: 30,
  retention: [
    { kind: 'hook', at_s: 0, event: 'hook: myth card', evidence: { n: 6 }, confidence: 'medium', text: '60% skipped in the first 3 s.' },
    { kind: 'exit', at_s: 15.2, event: 'fact 2: water', evidence: { n: 6 }, confidence: 'low', text: 'The average viewer leaves around 0:15.' },
    { kind: 'payoff', evidence: { n: 6 }, confidence: 'high', text: 'Viewers stay but do not share.' },
  ],
}
const EXTERNAL: PostDetail = {
  ...DETAIL, media_id: 'm1', permalink: 'https://www.instagram.com/reel/1/', asset_id: null, preview_url: null, thumbnail_url: null,
  tags: null, hypothesis: null, feedback: [], description: null, timeline: null, duration: null, retention: [],
  group: 'TRIAL',
}

function stubApi() {
  const fetchMock = vi.fn(async (url: string) => {
    const u = new URL(url, 'http://x')
    if (u.pathname === '/api/analytics/posts') {
      const [offset, limit] = ['offset', 'limit'].map((k) => Number(u.searchParams.get(k)))
      const rows = u.searchParams.get('verdict') ? [] : ALL
      return new Response(JSON.stringify({ total: rows.length, posts: rows.slice(offset, offset + limit) }))
    }
    const detail = { '/api/analytics/posts/m0': DETAIL, '/api/analytics/posts/m1': EXTERNAL }[u.pathname]
    return detail ? new Response(JSON.stringify(detail)) : new Response('{"error":"not_found"}', { status: 404 })
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}
const lastUrl = (m: ReturnType<typeof stubApi>) => m.mock.calls.at(-1)?.[0]

const show = (path: string) => render(
  <MemoryRouter initialEntries={[path]}>
    <Routes>
      <Route path="/analytics/posts" element={<Posts />} />
      <Route path="/analytics/posts/:id" element={<PostPage />} />
    </Routes>
  </MemoryRouter>)

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('Posts', () => {
  it('lists posts as cards and a table, and refetches on sort and filters', async () => {
    const fetchMock = stubApi()
    show('/analytics/posts')
    const cards = await screen.findByRole('list', { name: 'Publications' })
    expect(within(cards).getAllByRole('listitem')).toHaveLength(20)
    expect(lastUrl(fetchMock)).toBe('/api/analytics/posts?sort=-posted_at&offset=0&limit=20')
    const row = within(screen.getByRole('table')).getAllByRole('row')[1]
    expect(within(row).getByRole('link', { name: 'Post 0' }).getAttribute('href')).toBe('/analytics/posts/m0')
    expect(row.querySelector('img')?.getAttribute('src')).toBe('/api/media/7/thumb.jpg')
    expect(within(row).getByText('35 %')).toBeTruthy()

    fireEvent.change(screen.getByRole('combobox', { name: 'Trier par' }), { target: { value: 'watch_ratio' } })
    expect(lastUrl(fetchMock)).toBe('/api/analytics/posts?sort=-watch_ratio&offset=0&limit=20')
    fireEvent.click(screen.getByRole('button', { name: 'Du plus haut au plus bas' }))
    expect(lastUrl(fetchMock)).toBe('/api/analytics/posts?sort=watch_ratio&offset=0&limit=20')
    fireEvent.change(screen.getByRole('combobox', { name: 'Tags' }), { target: { value: 'false' } })
    expect(lastUrl(fetchMock)).toBe('/api/analytics/posts?sort=watch_ratio&tagged=false&offset=0&limit=20')
    fireEvent.change(screen.getByRole('combobox', { name: 'Verdict' }), { target: { value: 'winner' } })
    expect(lastUrl(fetchMock)).toBe('/api/analytics/posts?sort=watch_ratio&verdict=winner&tagged=false&offset=0&limit=20')
    expect(await screen.findByText('Aucune publication ne correspond.')).toBeTruthy()
  })

  it('marks trial Reels with a chip in the cards and the table', async () => {
    stubApi()
    show('/analytics/posts')
    const cards = within(await screen.findByRole('list', { name: 'Publications' })).getAllByRole('listitem')
    expect(within(cards[1]).getByText('essai')).toBeTruthy()
    expect(within(cards[0]).queryByText('essai')).toBeNull()
    const rows = within(screen.getByRole('table')).getAllByRole('row')
    expect(within(rows[2]).getByText('essai')).toBeTruthy()
    expect(within(rows[1]).queryByText('essai')).toBeNull()
    expect(within(screen.getByRole('combobox', { name: 'Type' })).getByRole('option', { name: 'Reels d’essai' })).toBeTruthy()
  })

  it('loads more with the next offset', async () => {
    const fetchMock = stubApi()
    show('/analytics/posts')
    await screen.findByText('20 sur 25')
    fireEvent.click(screen.getByRole('button', { name: 'Charger plus' }))
    expect(lastUrl(fetchMock)).toBe('/api/analytics/posts?sort=-posted_at&offset=20&limit=20')
    expect(await screen.findByText('25 sur 25')).toBeTruthy()
    expect(within(screen.getByRole('list', { name: 'Publications' })).getAllByRole('listitem')).toHaveLength(25)
    expect(screen.queryByRole('button', { name: 'Charger plus' })).toBeNull()
  })
})

describe('PostPage', () => {
  it('renders the growth series, tags, feedback and the studio video', async () => {
    stubApi()
    show('/analytics/posts/m0')
    expect(await screen.findByRole('img', { name: 'Vues : 300, +200 sur la période' })).toBeTruthy()
    expect(screen.getByRole('img', { name: 'Portée : 150, +100 sur la période' })).toBeTruthy()
    const snaps = within(screen.getByRole('table', { name: 'Relevés' })).getAllByRole('row')
    expect(snaps.slice(1).map((r) => r.textContent)).toEqual(['1 h10050', '24 h200100', '3 j300150'])
    expect(within(screen.getByRole('list', { name: 'Tags' })).getAllByRole('listitem').map((li) => li.textContent))
      .toEqual(['Piste : Motion', 'Pilier : Myths', 'Type d’accroche : Question', 'Modèle : FactQuest'])
    expect(screen.getByText('Hypothèse : questions hook better')).toBeTruthy()
    expect(screen.getByText('love the ending')).toBeTruthy()
    expect(screen.getByLabelText('Vidéo du studio').getAttribute('src')).toBe('/api/media/7/preview.mp4')
    expect(screen.getByRole('link', { name: 'Ouvrir dans le studio' }).getAttribute('href')).toBe('/assets/7')
    expect(screen.queryByRole('link', { name: 'Ouvrir sur Instagram' })).toBeNull()
  })

  it('links a post made outside the studio to Instagram', async () => {
    stubApi()
    show('/analytics/posts/m1')
    const ig = await screen.findByRole('link', { name: 'Ouvrir sur Instagram' })
    expect(ig.getAttribute('href')).toBe('https://www.instagram.com/reel/1/')
    expect(ig.getAttribute('target')).toBe('_blank')
    expect(ig.getAttribute('rel')).toBe('noopener noreferrer')
    expect(screen.queryByLabelText('Vidéo du studio')).toBeNull()
    expect(screen.getByText('Pas de tags : faite hors du studio.')).toBeTruthy()
    expect(screen.getByText('Pas de retours.')).toBeTruthy()
    expect(screen.getByText('essai')).toBeTruthy() // a trial Reel
  })

  it('shows why viewers left on the timeline, with confidence chips', async () => {
    stubApi()
    show('/analytics/posts/m0')
    const card = await screen.findByRole('region', { name: 'Pourquoi les spectateurs sont partis' })
    expect(within(card).getByText('A pixel knight busts three water myths.')).toBeTruthy()
    expect(within(card).getAllByRole('listitem').length).toBe(7) // 4 events + 3 findings
    expect(within(within(card).getByRole('list', { name: 'Moments de la vidéo' })).getAllByRole('listitem').map((li) => li.textContent))
      .toEqual(['0:00–0:03 hook: myth card', '0:03–0:15 fact 1', '0:15–0:30 fact 2: water', '+2 more'])
    // a capped timeline's untimed tail is listed but not drawn
    expect(within(card).queryByTitle('+2 more')).toBeNull()
    expect(within(card).getByTitle('fact 1')).toBeTruthy()
    // markers sit at at_s / duration; a finding without at_s has none
    expect((within(card).getByTitle('Accroche à 0:00') as HTMLElement).style.left).toBe('0%')
    expect(parseFloat((within(card).getByTitle('Sortie à 0:15') as HTMLElement).style.left)).toBeCloseTo(50.67, 1)
    expect(within(card).queryByTitle(/^Chute/)).toBeNull()
    const rows = within(within(card).getByRole('list', { name: 'Constats' })).getAllByRole('listitem')
    expect(rows.map((r) => r.textContent)).toEqual([
      'Accroche · 0:00confiance moyenne60% skipped in the first 3 s.',
      'Sortie · 0:15confiance faibleThe average viewer leaves around 0:15.',
      'Chuteconfiance forteViewers stay but do not share.',
    ])
  })

  it('says no findings yet and draws no bar without a timeline', async () => {
    stubApi()
    show('/analytics/posts/m1')
    const card = await screen.findByRole('region', { name: 'Pourquoi les spectateurs sont partis' })
    expect(within(card).getByText('Pas encore de constats : ils arrivent quand le Reel a mûri.')).toBeTruthy()
    expect(within(card).queryByRole('list', { name: 'Moments de la vidéo' })).toBeNull()
  })

  it('says not found on a 404', async () => {
    stubApi()
    show('/analytics/posts/gone')
    expect(await screen.findByText('Publication introuvable.')).toBeTruthy()
  })
})
