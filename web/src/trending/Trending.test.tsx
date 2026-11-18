import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router'
import type { FeedItem, RefreshResult, SuggestedTopics, Watch, WorkOrder } from '../api/client'
import { ToastProvider } from '../ui/Toast'
import { ago, orderStatus } from './format'
import TrendingPage from './TrendingPage'

const item = (id: number, over: Partial<FeedItem> = {}): FeedItem => ({
  id, permalink: `https://www.instagram.com/reel/R${id}/`, embed_url: `https://www.instagram.com/reel/R${id}/embed`,
  media_url: null, thumbnail_url: null, media_type: 'VIDEO', product_type: 'REELS',
  caption_quote: `Squat mistake ${id}\nmore text`, likes: 1200, comments: 45, views: 12300,
  posted_at: '2026-11-17T10:00:00Z', topic: 'fitness', topic_kind: 'hashtag', outlier: 6, outlier_metric: 'likes',
  reaction: null, work_order: null, ...over,
})
const WATCH: Watch[] = [{ id: 3, kind: 'hashtag', value: 'fitness', note: null }]
const BUDGET = { limit: 30, used: 2, left: 28 }
const SUGGESTED: SuggestedTopics = {
  topics: [{ tag: 'fitness', lang: 'intl', watched: true }, { tag: 'mealprep', lang: 'intl', watched: false }],
  hashtag_budget: BUDGET, note: '',
}
const REFRESH: RefreshResult = {
  hashtags_searched: ['fitness'], hashtags_skipped_budget: [], accounts: [], stored: 4, updated: 1,
  errors: {}, stopped: null, hashtag_budget: { limit: 30, used: 3, left: 27 },
}
const hoursAgo = (h: number) => new Date(Date.now() - h * 3600_000).toISOString()
// a real GET /api/work-orders?source=dm row (136, read from the owner's DB copy)
const order = (id: number, over: Partial<WorkOrder> = {}): WorkOrder => ({
  id, source_id: null, pick_id: id, mode: 'owner', instruction: null, own_reel: false, status: 'needs_instruction',
  skip_reason: null, blocked_reason: null, analysis: null, scheduled_at: null, idea_id: null, asset_id: null,
  created_at: hoursAgo(1), permalink: `https://www.instagram.com/reel/D${id}/`, sender_username: 'amine_xenima',
  received_at: hoursAgo(2), source: 'dm', embed_url: `https://www.instagram.com/reel/D${id}/embed`, topic: null,
  caption_quote: null, likes: null, comments: null, views: null, thumbnail_url: null, ...over,
})

type Route = [number, unknown]
function stubApi(overrides: Record<string, Route | Route[]> = {}) {
  const calls: { key: string; body?: unknown }[] = []
  const routes: Record<string, Route | Route[]> = {
    'GET /api/research/feed?limit=50': [200, [item(1), item(2)]],
    'GET /api/watchlist': [200, WATCH],
    'GET /api/research/suggested-topics': [200, SUGGESTED],
    'GET /api/dm-picks': [200, []],
    ...overrides,
  }
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

const renderPage = (path = '/trending') => render(
  <ToastProvider><MemoryRouter initialEntries={[path]}><TrendingPage /></MemoryRouter></ToastProvider>)
const card = (id: number) => screen.getByRole('listitem', { name: `Reel ${id}` })

beforeEach(() => {
  // jsdom has no modal dialogs
  HTMLDialogElement.prototype.showModal = function () { this.open = true }
  HTMLDialogElement.prototype.close = function () {
    this.open = false
    this.dispatchEvent(new Event('close'))
  }
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('Tendances', () => {
  it('shows the feed: topic, outlier, French stats, the caption first line, a safe link', async () => {
    stubApi({ 'GET /api/research/feed?limit=50': [200, [item(1), item(2, { permalink: 'javascript:alert(1)', embed_url: null })]] })
    renderPage()
    await screen.findByRole('list', { name: 'Tendances' })
    expect(within(card(1)).getByText('#fitness')).toBeTruthy()
    expect(within(card(1)).getByText("×6 j'aime")).toBeTruthy()
    expect(within(card(1)).getByText(/12,3\sk vues · 1,2\sk j'aime · 45 commentaires/)).toBeTruthy()
    expect(within(card(1)).getByText('Squat mistake 1').tagName).toBe('Q')
    expect(within(card(1)).getByTitle('Reel fitness').getAttribute('src')).toBe('https://www.instagram.com/reel/R1/embed')
    expect(within(card(1)).getByRole('link', { name: 'Instagram' }).getAttribute('href')).toBe('https://www.instagram.com/reel/R1/')
    expect(within(card(2)).queryByRole('link', { name: 'Instagram' })).toBeNull()
    expect(within(card(2)).queryByTitle('Reel fitness')).toBeNull()
    expect(screen.getByText('28/30 hashtags restants cette semaine')).toBeTruthy()
  })

  it('plays a Reel with media inline, muted, with its poster', async () => {
    stubApi({ 'GET /api/research/feed?limit=50': [200, [item(1, {
      media_url: 'https://scontent.cdninstagram.com/v.mp4', thumbnail_url: 'https://scontent.cdninstagram.com/t.jpg' })]] })
    renderPage()
    await screen.findByRole('list', { name: 'Tendances' })
    const video = card(1).querySelector('video')!
    expect(video.getAttribute('src')).toBe('https://scontent.cdninstagram.com/v.mp4')
    expect(video.getAttribute('poster')).toBe('https://scontent.cdninstagram.com/t.jpg')
    expect(video.muted).toBe(true)
    expect(video.hasAttribute('playsinline')).toBe(true)
    fireEvent.click(within(card(1)).getByRole('button', { name: 'Activer le son' }))
    expect(video.muted).toBe(false)
  })

  it('refreshes: a toast says what was found, the budget updates and the feed reloads', async () => {
    const calls = stubApi({ 'POST /api/research/refresh': [200, { ...REFRESH, hashtags_skipped_budget: ['gym'], errors: { 'account:x': 'no' } }] })
    renderPage()
    await screen.findByRole('list', { name: 'Tendances' })
    fireEvent.click(screen.getByRole('button', { name: 'Actualiser' }))
    expect((await screen.findByRole('status')).textContent).toContain(
      'Trouvé : 4 nouveaux Reels, 1 mis à jour. 1 hashtag(s) en attente : limite de la semaine atteinte. 1 sujet(s) en erreur.')
    expect(screen.getByText('27/30 hashtags restants cette semaine')).toBeTruthy()
    await vi.waitFor(() => expect(calls.filter((c) => c.key === 'GET /api/research/feed?limit=50')).toHaveLength(2))
  })

  it.each([
    [409, { error: 'already_running', message: 'a refresh is already running' }, 'Une actualisation est déjà en cours'],
    [503, { error: 'instagram_not_configured' }, "Instagram n'est pas encore connecté"],
  ])('refresh answered %i: says why', async (status, body, text) => {
    stubApi({ 'POST /api/research/refresh': [status, body] })
    renderPage()
    await screen.findByRole('list', { name: 'Tendances' })
    fireEvent.click(screen.getByRole('button', { name: 'Actualiser' }))
    expect((await screen.findByRole('status')).textContent).toContain(text)
  })

  it('likes, clears and dislikes; a refused reaction rolls back', async () => {
    const calls = stubApi({
      'POST /api/research/feed/1/reaction': [[200, { id: 1, reaction: 'like' }], [200, { id: 1, reaction: null }], [500, { error: 'boom' }]],
    })
    renderPage()
    await screen.findByRole('list', { name: 'Tendances' })
    const like = within(card(1)).getByRole('button', { name: "J'aime" })
    fireEvent.click(like)
    expect(like.getAttribute('aria-pressed')).toBe('true')
    fireEvent.click(like)
    await vi.waitFor(() => expect(like.getAttribute('aria-pressed')).toBe('false'))
    const dislike = within(card(1)).getByRole('button', { name: "Je n'aime pas" })
    fireEvent.click(dislike)
    await vi.waitFor(() => expect(screen.getByRole('status').textContent).toContain('Non enregistré'))
    expect(dislike.getAttribute('aria-pressed')).toBe('false')
    expect(calls.filter((c) => c.key === 'POST /api/research/feed/1/reaction').map((c) => c.body)).toEqual([
      { reaction: 'like' }, { reaction: 'none' }, { reaction: 'dislike' }])
  })

  it('selects several Reels and sends them to work in the chosen mode', async () => {
    const calls = stubApi({
      'GET /api/research/feed?limit=50': [200, [item(1), item(2), item(3, { work_order: { id: 9, mode: 'react', instruction: null, status: 'in_production' } })]],
      'POST /api/research/work-orders': [200, []],
    })
    renderPage()
    await screen.findByRole('list', { name: 'Tendances' })
    expect(within(card(3)).getByText('En production')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Sélectionner' }))
    const bar = screen.getByRole('region', { name: 'Envoyer la sélection' })
    expect((within(bar).getByRole('button', { name: 'Envoyer au travail (0)' }) as HTMLButtonElement).disabled).toBe(true)
    expect((within(card(3)).getByLabelText('Choisir ce Reel') as HTMLInputElement).disabled).toBe(true)
    fireEvent.click(within(card(1)).getByLabelText('Choisir ce Reel'))
    fireEvent.click(within(card(2)).getByLabelText('Choisir ce Reel'))
    fireEvent.click(within(bar).getByRole('button', { name: 'Réaction' }))
    fireEvent.click(within(bar).getByRole('button', { name: 'Envoyer au travail (2)' }))
    expect((await screen.findByRole('status')).textContent).toContain('2 Reels envoyés au travail.')
    expect(calls.find((c) => c.key === 'POST /api/research/work-orders')?.body).toEqual({
      items: [{ source_id: 1, mode: 'react' }, { source_id: 2, mode: 'react' }] })
    expect(screen.queryByRole('region', { name: 'Envoyer la sélection' })).toBeNull()
  })

  it("tells the AI what to do with one Reel, and cancels a new order", async () => {
    const calls = stubApi({
      'GET /api/research/feed?limit=50': [[200, [item(1)]],
        [200, [item(1, { work_order: { id: 5, mode: 'inspired', instruction: 'version sans sucre', status: 'scheduled' } })]], [200, [item(1)]]],
      'POST /api/research/work-orders': [200, []],
      'DELETE /api/research/work-orders/5': [204, null],
    })
    renderPage()
    await screen.findByRole('list', { name: 'Tendances' })
    fireEvent.click(within(card(1)).getByRole('button', { name: "Dire à l'IA quoi faire" }))
    const sheet = screen.getByRole('dialog', { name: "Dire à l'IA quoi faire" })
    fireEvent.change(within(sheet).getByLabelText('Ta consigne'), { target: { value: ' version sans sucre ' } })
    fireEvent.click(within(sheet).getByRole('button', { name: "Envoyer à l'IA" }))
    expect(await within(card(1)).findByText('version sans sucre')).toBeTruthy()
    expect(within(card(1)).getByText('Programmé')).toBeTruthy()
    expect(within(card(1)).queryByRole('button', { name: "Dire à l'IA quoi faire" })).toBeNull()
    expect(calls.find((c) => c.key === 'POST /api/research/work-orders')?.body).toEqual({
      items: [{ source_id: 1, mode: 'inspired', instruction: 'version sans sucre' }] })

    fireEvent.click(within(card(1)).getByRole('button', { name: 'Annuler' }))
    expect(await within(card(1)).findByRole('button', { name: "Dire à l'IA quoi faire" })).toBeTruthy()
    expect(calls.map((c) => c.key)).toContain('DELETE /api/research/work-orders/5')
  })

  it('filters by topic, adds a suggested topic in one tap, removes one', async () => {
    const calls = stubApi({
      'GET /api/research/feed?topic=fitness&limit=50': [200, [item(1)]],
      'POST /api/watchlist': [200, { id: 4, kind: 'hashtag', value: 'mealprep', note: null }],
      'DELETE /api/watchlist/3': [204, null],
    })
    renderPage()
    await screen.findByRole('list', { name: 'Tendances' })
    const filter = screen.getByRole('group', { name: 'Filtrer par sujet' })
    fireEvent.click(within(filter).getByRole('button', { name: '#fitness' }))
    await vi.waitFor(() => expect(calls.map((c) => c.key)).toContain('GET /api/research/feed?topic=fitness&limit=50'))
    expect(screen.getByText(/Chaque nouveau hashtag utilise 1 des 30 recherches/).textContent).toContain('il en reste 28')

    const suggestions = screen.getByRole('group', { name: 'Suggestions' })
    expect(within(suggestions).queryByRole('button', { name: '+ #fitness' })).toBeNull() // watched already
    fireEvent.click(within(suggestions).getByRole('button', { name: '+ #mealprep' }))
    await vi.waitFor(() => expect(calls.find((c) => c.key === 'POST /api/watchlist')?.body)
      .toEqual({ kind: 'hashtag', value: 'mealprep' }))
    await vi.waitFor(() => expect(calls.filter((c) => c.key === 'GET /api/watchlist')).toHaveLength(2))

    fireEvent.click(screen.getByRole('button', { name: 'Retirer #fitness' }))
    await vi.waitFor(() => expect(calls.map((c) => c.key)).toContain('DELETE /api/watchlist/3'))
  })

  it('shows a refused topic', async () => {
    stubApi({ 'POST /api/watchlist': [422, { error: 'invalid', message: 'not a valid hashtag' }] })
    renderPage()
    const form = await screen.findByRole('form', { name: 'Ajouter un sujet' })
    fireEvent.change(within(form).getByLabelText('Hashtag ou compte'), { target: { value: 'two words' } })
    fireEvent.click(within(form).getByRole('button', { name: 'Ajouter' }))
    expect((await screen.findByRole('alert')).textContent).toBe('not a valid hashtag')
  })

  it('opens the topics editor and an empty state when nothing is watched', async () => {
    stubApi({ 'GET /api/research/feed?limit=50': [200, []], 'GET /api/watchlist': [200, []] })
    renderPage()
    expect(await screen.findByText("Aucune tendance pour l'instant")).toBeTruthy()
    expect(screen.getByText('Gérer les sujets').closest('details')!.open).toBe(true)
    expect(screen.getByRole('link', { name: 'Rapport' }).getAttribute('href')).toBe('/trends')
  })
})

describe('Mes envois', () => {
  it('shows the empty state, and the tab sits in the URL', async () => {
    stubApi({ 'GET /api/work-orders?source=dm': [200, []] })
    renderPage('/trending?tab=envois')
    expect(screen.getByRole('tab', { name: 'Mes envois' }).getAttribute('aria-selected')).toBe('true')
    expect(await screen.findByText(/Envoie un Reel en DM à @macrobody\.fr depuis ton compte, avec ou sans description\./)).toBeTruthy()
  })

  it('lists DM orders with sender, age, status, instruction and the feed link', async () => {
    stubApi({ 'GET /api/work-orders?source=dm': [200, [
      order(4, { status: 'analysed', own_reel: true, instruction: 'ça a bien marché, analyse-la', analysis: 'Le hook tient 3 s.' }),
      order(3, { status: 'in_feed', asset_id: 42, instruction: 'analyse-la', mode: 'inspired' }),
      order(2, { status: 'skipped', skip_reason: 'pas un Reel' }),
      order(1, { status: 'in_production', blocked_reason: 'téléchargement refusé' }),
    ]] })
    renderPage('/trending?tab=envois')
    const list = await screen.findByRole('list', { name: 'Mes envois' })
    const [analysed, feed, skipped, blocked] = within(list).getAllByRole('listitem')
    expect(within(analysed).getByText('Analysé')).toBeTruthy()
    expect(within(analysed).getByText('Ton Reel')).toBeTruthy()
    expect(within(analysed).getByText('Ta consigne · Mon instruction')).toBeTruthy()
    expect(within(analysed).getByText("Analyse de l'IA : Le hook tient 3 s.")).toBeTruthy()
    expect(within(feed).queryByText('Ton Reel')).toBeNull()
    expect(within(feed).getByText('Dans ton feed')).toBeTruthy()
    expect(within(feed).getByText('envoyé par @amine_xenima, il y a 2 h')).toBeTruthy()
    expect(within(feed).getByText('analyse-la').tagName).toBe('Q')
    expect(within(feed).getByText('Ta consigne · Inspiré')).toBeTruthy()
    expect(within(feed).getByRole('link', { name: 'Voir dans ton feed' }).getAttribute('href')).toBe('/assets/42')
    expect(within(feed).getByTitle('Reel envoyé par @amine_xenima').getAttribute('src')).toBe('https://www.instagram.com/reel/D3/embed')
    expect(within(skipped).getByText('Ignoré')).toBeTruthy()
    expect(within(skipped).getByText('Ignoré : pas un Reel')).toBeTruthy()
    expect(within(blocked).getByText('Bloqué')).toBeTruthy()
    expect(within(blocked).getByText('Bloqué : téléchargement refusé')).toBeTruthy()
  })

  it('writes the missing instruction, edits a scheduled one, and says when it is too late (409)', async () => {
    const calls = stubApi({
      'GET /api/work-orders?source=dm': [
        [200, [order(2, { status: 'scheduled', instruction: 'garde ça', mode: 'react' }), order(1)]],
        [200, [order(2, { status: 'scheduled', instruction: 'garde ça', mode: 'react' }), order(1, { status: 'scheduled', instruction: 'refais-la', mode: 'inspired' })]],
        [200, [order(2, { status: 'in_production', instruction: 'garde ça', mode: 'react' }), order(1, { status: 'scheduled', instruction: 'refais-la', mode: 'inspired' })]],
      ],
      'PATCH /api/work-orders/1': [200, order(1, { status: 'scheduled', instruction: 'refais-la' })],
      'PATCH /api/work-orders/2': [409, { error: 'conflict', message: 'work order 2 is in_production' }],
    })
    renderPage('/trending?tab=envois')
    const list = await screen.findByRole('list', { name: 'Mes envois' })
    const waiting = within(list).getByRole('listitem', { name: 'Envoi 1' })
    expect(within(waiting).getByText("En attente d'instruction")).toBeTruthy()
    expect(within(waiting).getByRole('button', { name: 'Mon instruction' }).getAttribute('aria-pressed')).toBe('true')
    fireEvent.change(within(waiting).getByLabelText("Que doit faire l'IA ?"), { target: { value: 'refais-la' } })
    fireEvent.click(within(waiting).getByRole('button', { name: 'Envoyer' }))
    expect(await within(waiting).findByText('Programmé')).toBeTruthy()
    expect(within(waiting).getByText('refais-la')).toBeTruthy()
    expect(calls.find((c) => c.key === 'PATCH /api/work-orders/1')?.body).toEqual({ instruction: 'refais-la', mode: 'owner' })

    const scheduled = within(list).getByRole('listitem', { name: 'Envoi 2' })
    fireEvent.click(within(scheduled).getByRole('button', { name: 'Modifier la consigne' }))
    expect(within(scheduled).getByRole('button', { name: 'Réaction' }).getAttribute('aria-pressed')).toBe('true')
    fireEvent.change(within(scheduled).getByLabelText("Que doit faire l'IA ?"), { target: { value: 'change ça' } })
    fireEvent.click(within(scheduled).getByRole('button', { name: 'Envoyer' }))
    expect((await screen.findByRole('status')).textContent).toContain("Trop tard : l'IA a déjà commencé ce Reel")
    expect(await within(scheduled).findByText('En production')).toBeTruthy()
    expect(within(scheduled).queryByRole('button', { name: 'Modifier la consigne' })).toBeNull()
    expect(calls.find((c) => c.key === 'PATCH /api/work-orders/2')?.body).toEqual({ instruction: 'change ça', mode: 'react' })
  })

  it('names every status in French', () => {
    const label = (status: WorkOrder['status'], blocked_reason: string | null = null) => orderStatus({ status, blocked_reason })[0]
    expect(['needs_instruction', 'scheduled', 'in_production', 'in_feed', 'analysed', 'skipped'].map((s) => label(s as WorkOrder['status'])))
      .toEqual(["En attente d'instruction", 'Programmé', 'En production', 'Dans ton feed', 'Analysé', 'Ignoré'])
    expect(label('scheduled', 'x')).toBe('Bloqué')
    expect(label('in_feed', 'x')).toBe('Dans ton feed') // done: the old block no longer matters
    const now = Date.parse('2026-11-18T12:00:00Z')
    expect(ago('2026-11-18T10:00:00Z', now)).toMatch(/^il y a 2\sh$/) // Intl puts a no-break space
    expect(ago('2026-11-17T12:00:00Z', now)).toBe('hier')
    expect(ago('2026-11-18T12:00:00Z', now)).toBe("à l'instant")
  })
})
