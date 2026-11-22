import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router'
import type { FeedItem, RefreshResult, Style, SuggestedTopics, Watch, WorkOrder } from '../api/client'
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
/** A GET /api/research/feed answer (140: Reels within the window, older ones counted). */
const feed = (items: FeedItem[], hidden_old = 0) => ({ items, window_days: 21, hidden_old })
const WATCH: Watch[] = [{ id: 3, kind: 'hashtag', value: 'fitness', note: null }]
const BUDGET = { limit: 30, used: 2, left: 28 }
const SUGGESTED: SuggestedTopics = {
  topics: [{ tag: 'fitness', lang: 'intl', watched: true }, { tag: 'mealprep', lang: 'intl', watched: false }],
  accounts: [{ username: 'jeffnippard', watched: true }, { username: 'tiboinshape', watched: false }],
  hashtag_budget: BUDGET, note: '', accounts_note: '',
}
const REFRESH: RefreshResult = {
  hashtags_searched: ['fitness'], hashtags_skipped_budget: [], accounts: [], stored: 4, updated: 1,
  errors: {}, stopped: null, hashtag_budget: { limit: 30, used: 3, left: 27 },
}
const hoursAgo = (h: number) => new Date(Date.now() - h * 3600_000).toISOString()
// a real GET /api/work-orders?source=mine row (136, read from the owner's DB copy)
const order = (id: number, over: Partial<WorkOrder> = {}): WorkOrder => ({
  id, source_id: null, pick_id: id, mode: 'owner', instruction: null, own_reel: false, status: 'needs_instruction',
  skip_reason: null, blocked_reason: null, analysis: null, scheduled_at: null, idea_id: null, asset_id: null,
  created_at: hoursAgo(1), permalink: `https://www.instagram.com/reel/D${id}/`, sender_username: 'amine_xenima',
  received_at: hoursAgo(2), source: 'dm', embed_url: `https://www.instagram.com/reel/D${id}/embed`, topic: null,
  caption_quote: null, likes: null, comments: null, views: null, thumbnail_url: null, style: null,
  from_asset_id: null, updated_at: hoursAgo(1), idea_hook: null, video_status: null, ...over,
})

// GET /api/styles (138): one button per enabled style; a turned-off one shows no button
const style = (id: string, label: string, over: Partial<Style> = {}): Style => ({
  id, label, description: `Le style ${label}.`, templates: [], end_card: id, address: 'vous', enabled: true, share: null,
  preview: { still: null, clip: null }, ...over,
})
const STYLES: Style[] = [
  style('voxel', '3D 8-bit', { preview: { still: '/api/styles/voxel/preview/still', clip: '/api/styles/voxel/preview/clip' } }),
  style('paper', 'Papier'),
  style('blender', 'Blender', { enabled: false }),
]

type Route = [number, unknown]
function stubApi(overrides: Record<string, Route | Route[]> = {}) {
  const calls: { key: string; body?: unknown }[] = []
  const routes: Record<string, Route | Route[]> = {
    'GET /api/research/feed?limit=200': [200, feed([item(1), item(2)])],
    'GET /api/watchlist': [200, WATCH],
    'GET /api/research/suggested-topics': [200, SUGGESTED],
    'GET /api/dm-picks': [200, []],
    'GET /api/styles': [200, STYLES],
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
    stubApi({ 'GET /api/research/feed?limit=200': [200, feed([item(1), item(2, { permalink: 'javascript:alert(1)', embed_url: null })])] })
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
    stubApi({ 'GET /api/research/feed?limit=200': [200, feed([item(1, {
      media_url: 'https://scontent.cdninstagram.com/v.mp4', thumbnail_url: 'https://scontent.cdninstagram.com/t.jpg' })])] })
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

  it('shows Reels by default; Tout adds carousels and images with their picture', async () => {
    const carousel = item(2, { media_type: 'CAROUSEL_ALBUM', product_type: 'FEED', media_url: 'https://scontent.cdninstagram.com/c.jpg' })
    stubApi({ 'GET /api/research/feed?limit=200': [200, feed([item(1), carousel])] })
    renderPage()
    const kinds = await screen.findByRole('group', { name: 'Type de média' })
    expect(within(kinds).getByRole('button', { name: 'Reels (1)' }).getAttribute('aria-pressed')).toBe('true')
    expect(screen.queryByRole('listitem', { name: 'Reel 2' })).toBeNull()
    fireEvent.click(within(kinds).getByRole('button', { name: 'Tout (2)' }))
    expect(card(2).querySelector('img')!.getAttribute('src')).toBe('https://scontent.cdninstagram.com/c.jpg')
    expect(within(card(2)).getByRole('link', { name: 'Instagram' })).toBeTruthy()
  })

  it('without Reels, points to adding an account to watch', async () => {
    stubApi({ 'GET /api/research/feed?limit=200': [200, feed([item(1, { media_type: 'IMAGE', product_type: 'FEED' })])] })
    renderPage()
    expect(await screen.findByText('Pas encore de Reels : ajoute des comptes à suivre')).toBeTruthy()
    const topics = screen.getByText('Gérer les sujets').closest('details')!
    expect(topics.open).toBe(false)
    fireEvent.click(screen.getByRole('button', { name: 'Ajouter un compte' }))
    expect(topics.open).toBe(true)
    expect((screen.getByLabelText('Type') as HTMLSelectElement).value).toBe('account')
    expect(document.activeElement).toBe(screen.getByLabelText('Hashtag ou compte'))
  })

  it('refreshes: a toast says what was found, the budget updates and the feed reloads', async () => {
    const calls = stubApi({ 'POST /api/research/refresh': [200, { ...REFRESH, hashtags_skipped_budget: ['gym'], errors: { 'account:x': 'no' } }] })
    renderPage()
    await screen.findByRole('list', { name: 'Tendances' })
    fireEvent.click(screen.getByRole('button', { name: 'Actualiser' }))
    expect((await screen.findByRole('status')).textContent).toContain(
      'Trouvé : 4 nouveaux Reels, 1 mis à jour. 1 hashtag(s) en attente : limite de la semaine atteinte. 1 sujet(s) en erreur.')
    expect(screen.getByText('27/30 hashtags restants cette semaine')).toBeTruthy()
    await vi.waitFor(() => expect(calls.filter((c) => c.key === 'GET /api/research/feed?limit=200')).toHaveLength(2))
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
      'GET /api/research/feed?limit=200': [200, feed([item(1), item(2), item(3, { work_order: { id: 9, mode: 'react', instruction: null, status: 'in_production' } })])],
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
    fireEvent.click(await within(bar).findByRole('button', { name: 'Papier' }))
    expect(within(bar).queryByRole('button', { name: 'Blender' })).toBeNull() // turned off in Settings
    fireEvent.click(within(bar).getByRole('button', { name: 'Envoyer au travail (2)' }))
    expect((await screen.findByRole('status')).textContent).toContain('2 Reels envoyés au travail.')
    expect(calls.find((c) => c.key === 'POST /api/research/work-orders')?.body).toEqual({
      items: [{ source_id: 1, mode: 'react', style: 'paper' }, { source_id: 2, mode: 'react', style: 'paper' }] })
    expect(screen.queryByRole('region', { name: 'Envoyer la sélection' })).toBeNull()
  })

  it("tells the AI what to do with one Reel, and cancels a new order", async () => {
    const calls = stubApi({
      'GET /api/research/feed?limit=200': [[200, feed([item(1)])],
        [200, feed([item(1, { work_order: { id: 5, mode: 'inspired', instruction: 'version sans sucre', status: 'scheduled' } })])], [200, feed([item(1)])]],
      'POST /api/research/work-orders': [200, []],
      'DELETE /api/research/work-orders/5': [204, null],
    })
    renderPage()
    await screen.findByRole('list', { name: 'Tendances' })
    fireEvent.click(within(card(1)).getByRole('button', { name: "Dire à l'IA quoi faire" }))
    const sheet = screen.getByRole('dialog', { name: "Dire à l'IA quoi faire" })
    fireEvent.change(within(sheet).getByLabelText('Ta consigne'), { target: { value: ' version sans sucre ' } })
    const voxel = await within(sheet).findByRole('button', { name: '3D 8-bit' })
    expect(within(sheet).getByRole('button', { name: "Auto (l'IA choisit)" }).getAttribute('aria-pressed')).toBe('true')
    fireEvent.mouseEnter(voxel) // hover selects nothing and previews nothing
    expect(within(sheet).queryByLabelText('Aperçu 3D 8-bit')).toBeNull()
    fireEvent.click(voxel) // a click: chosen, and its preview shows
    expect(voxel.getAttribute('aria-pressed')).toBe('true')
    expect(within(sheet).getByLabelText('Aperçu 3D 8-bit').textContent).toContain('Le style 3D 8-bit.')
    fireEvent.click(within(sheet).getByRole('button', { name: "Envoyer à l'IA" }))
    expect(await within(card(1)).findByText('version sans sucre')).toBeTruthy()
    expect(within(card(1)).getByText('Programmé')).toBeTruthy()
    expect(within(card(1)).queryByRole('button', { name: "Dire à l'IA quoi faire" })).toBeNull()
    expect(calls.find((c) => c.key === 'POST /api/research/work-orders')?.body).toEqual({
      items: [{ source_id: 1, mode: 'inspired', instruction: 'version sans sucre', style: 'voxel' }] })

    fireEvent.click(within(card(1)).getByRole('button', { name: 'Annuler' }))
    expect(await within(card(1)).findByRole('button', { name: "Dire à l'IA quoi faire" })).toBeTruthy()
    expect(calls.map((c) => c.key)).toContain('DELETE /api/research/work-orders/5')
  })

  it('filters by topic, adds a suggested topic in one tap, removes one', async () => {
    const calls = stubApi({
      'GET /api/research/feed?topic=fitness&limit=200': [200, feed([item(1)])],
      'POST /api/watchlist': [200, { id: 4, kind: 'hashtag', value: 'mealprep', note: null }],
      'DELETE /api/watchlist/3': [204, null],
    })
    renderPage()
    await screen.findByRole('list', { name: 'Tendances' })
    const filter = screen.getByRole('group', { name: 'Filtrer par sujet' })
    fireEvent.click(within(filter).getByRole('button', { name: '#fitness' }))
    await vi.waitFor(() => expect(calls.map((c) => c.key)).toContain('GET /api/research/feed?topic=fitness&limit=200'))
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

  it('adds a suggested account in one tap: free, and it brings the Reels', async () => {
    const calls = stubApi({ 'POST /api/watchlist': [200, { id: 5, kind: 'account', value: 'tiboinshape', note: null }] })
    renderPage()
    await screen.findByRole('list', { name: 'Tendances' })
    const accounts = screen.getByRole('group', { name: 'Comptes suggérés' })
    expect(within(accounts).queryByRole('button', { name: '+ @jeffnippard' })).toBeNull() // watched already
    expect(screen.getByText(/apportent les Reels/)).toBeTruthy()
    fireEvent.click(within(accounts).getByRole('button', { name: '+ @tiboinshape' }))
    await vi.waitFor(() => expect(calls.find((c) => c.key === 'POST /api/watchlist')?.body)
      .toEqual({ kind: 'account', value: 'tiboinshape' }))
    await vi.waitFor(() => expect(calls.filter((c) => c.key === 'GET /api/research/suggested-topics')).toHaveLength(2))
  })

  it('hides Reels older than the window; one tap shows them too', async () => {
    const calls = stubApi({
      'GET /api/research/feed?limit=200': [200, feed([item(1)], 3)],
      'GET /api/research/feed?limit=200&include_old=1': [200, feed([item(1), item(2, { posted_at: '2020-01-05T10:00:00Z' })], 3)],
    })
    renderPage()
    await screen.findByRole('list', { name: 'Tendances' })
    expect(screen.getByText(/3 publications de plus de 21 jours masquées/)).toBeTruthy()
    expect(screen.queryByRole('listitem', { name: 'Reel 2' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Afficher les anciennes' }))
    expect(await screen.findByRole('listitem', { name: 'Reel 2' })).toBeTruthy()
    expect(calls.map((c) => c.key)).toContain('GET /api/research/feed?limit=200&include_old=1')
    expect(screen.getByRole('button', { name: 'Masquer les anciennes' }).getAttribute('aria-pressed')).toBe('true')
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
    stubApi({ 'GET /api/research/feed?limit=200': [200, feed([])], 'GET /api/watchlist': [200, []] })
    renderPage()
    expect(await screen.findByText("Aucune tendance pour l'instant")).toBeTruthy()
    expect(screen.getByText('Gérer les sujets').closest('details')!.open).toBe(true)
    expect(screen.getByRole('link', { name: 'Rapport' }).getAttribute('href')).toBe('/trends')
  })
})

describe('Mes envois', () => {
  it('shows the empty state, and the tab sits in the URL', async () => {
    stubApi({ 'GET /api/work-orders?source=mine': [200, []] })
    renderPage('/trending?tab=envois')
    expect(screen.getByRole('tab', { name: 'Mes envois' }).getAttribute('aria-selected')).toBe('true')
    expect(await screen.findByText(/Envoie un Reel en DM à @macrobody\.fr depuis ton compte, avec ou sans description\./)).toBeTruthy()
  })

  it('« Annuler » drops an envoi the AI has not started, after a confirm (183)', async () => {
    const calls = stubApi({
      'GET /api/work-orders?source=mine': [[200, [order(2), order(1, { status: 'in_production', instruction: 'fais-la' })]], [200, [order(1, { status: 'in_production', instruction: 'fais-la' })]]],
      'DELETE /api/research/work-orders/2': [204, null],
    })
    renderPage('/trending?tab=envois')
    const list = await screen.findByRole('list', { name: 'Mes envois' })
    expect(within(within(list).getByRole('listitem', { name: 'Envoi 1' })).queryByRole('button', { name: 'Annuler' })).toBeNull()
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true)
    const two = within(list).getByRole('listitem', { name: 'Envoi 2' })
    fireEvent.click(within(two).getByRole('button', { name: 'Annuler' }))
    expect(calls.some((c) => c.key.startsWith('DELETE'))).toBe(false) // said no
    fireEvent.click(within(two).getByRole('button', { name: 'Annuler' }))
    await waitFor(() => expect(screen.queryByRole('listitem', { name: 'Envoi 2' })).toBeNull())
    expect(calls.map((c) => c.key)).toContain('DELETE /api/research/work-orders/2')
    expect(confirm).toHaveBeenCalledTimes(2)
  })

  it('lists DM orders with sender, age, status, instruction and the feed link', async () => {
    stubApi({ 'GET /api/work-orders?source=mine': [200, [
      order(5, { status: 'analysed', analysis: { why: 'Le hook promet un résultat.', summary: 'Promesse claire en 2 s.',
        timeline: [{ t: 0, d: 4, e: 'Hook : la promesse' }] } }),
      order(4, { status: 'analysed', own_reel: true, instruction: 'ça a bien marché, analyse-la', analysis: 'Le hook tient 3 s.' }),
      order(3, { status: 'in_feed', asset_id: 42, instruction: 'analyse-la', mode: 'inspired' }),
      order(2, { status: 'skipped', skip_reason: 'pas un Reel' }),
      order(1, { status: 'in_production', blocked_reason: 'téléchargement refusé' }),
    ]] })
    renderPage('/trending?tab=envois')
    const list = await screen.findByRole('list', { name: 'Mes envois' })
    const [timed, analysed, feed, skipped, blocked] = within(list).getAllByRole('listitem')
    expect(within(analysed).getByText('Analysé')).toBeTruthy()
    expect(within(analysed).getByText('Ton Reel')).toBeTruthy()
    expect(within(analysed).getByText('Ta consigne · Mon instruction')).toBeTruthy()
    expect(within(analysed).getByText("Analyse de l'IA : Le hook tient 3 s.")).toBeTruthy()
    expect(within(timed).getByText("Analyse de l'IA : Promesse claire en 2 s.")).toBeTruthy() // 182: an object
    expect(within(timed).getByText('Le hook promet un résultat.')).toBeTruthy()
    expect(within(timed).getByText('Hook : la promesse', { exact: false })).toBeTruthy()
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
      'GET /api/work-orders?source=mine': [
        [200, [order(2, { status: 'scheduled', instruction: 'garde ça', mode: 'react', style: 'paper' }), order(1)]],
        [200, [order(2, { status: 'scheduled', instruction: 'garde ça', mode: 'react', style: 'paper' }), order(1, { status: 'scheduled', instruction: 'refais-la', mode: 'inspired' })]],
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
    expect(calls.find((c) => c.key === 'PATCH /api/work-orders/1')?.body).toEqual({ instruction: 'refais-la', mode: 'owner', style: null })

    const scheduled = within(list).getByRole('listitem', { name: 'Envoi 2' })
    fireEvent.click(within(scheduled).getByRole('button', { name: 'Modifier la consigne' }))
    expect(within(scheduled).getByRole('button', { name: 'Réaction' }).getAttribute('aria-pressed')).toBe('true')
    fireEvent.change(within(scheduled).getByLabelText("Que doit faire l'IA ?"), { target: { value: 'change ça' } })
    expect((await within(scheduled).findByRole('button', { name: 'Papier' })).getAttribute('aria-pressed')).toBe('true')
    fireEvent.click(within(scheduled).getByRole('button', { name: '3D 8-bit' }))
    fireEvent.click(within(scheduled).getByRole('button', { name: 'Envoyer' }))
    expect((await screen.findByRole('status')).textContent).toContain("Trop tard : l'IA a déjà commencé ce Reel")
    expect(await within(scheduled).findByText('En production')).toBeTruthy()
    expect(within(scheduled).queryByRole('button', { name: 'Modifier la consigne' })).toBeNull()
    expect(calls.find((c) => c.key === 'PATCH /api/work-orders/2')?.body).toEqual({ instruction: 'change ça', mode: 'react', style: 'voxel' })
  })

  it('shows what the owner created and the restyles, with their style (138)', async () => {
    stubApi({
      'GET /api/work-orders?source=mine': [200, [
        order(7, { source: 'change', pick_id: null, permalink: null, embed_url: null, sender_username: null, received_at: null,
          from_asset_id: 42, style: 'voxel', status: 'scheduled', instruction: 'Même vidéo, autre style : refais la vidéo 42' }),
        order(6, { source: 'create', pick_id: null, permalink: null, embed_url: null, sender_username: null, received_at: null,
          status: 'scheduled', instruction: 'Les protéines du soir' }),
        order(5, { source: 'create', pick_id: null, permalink: null, embed_url: null, sender_username: null, received_at: null,
          style: 'lemo:watercolor', status: 'scheduled', instruction: 'Le sommeil' }),
      ]],
      'GET /api/style-catalog?family=lemo': [200, [{ id: 'lemo:watercolor', family: 'lemo', label: 'Watercolor Brush',
        essence: null, category: null, tags: [], preview: { poster: null, clip: null }, favourite: false,
        selectable: true, why_not: null, credit: null }]],
    })
    renderPage('/trending?tab=envois')
    const list = await screen.findByRole('list', { name: 'Mes envois' })
    expect(await within(within(list).getByRole('listitem', { name: 'Envoi 5' })).findByText('Watercolor Brush')).toBeTruthy() // its name, not lemo:watercolor
    const change = within(list).getByRole('listitem', { name: 'Envoi 7' })
    expect(await within(change).findByText('3D 8-bit')).toBeTruthy()
    expect(within(change).getByText(/autre style de la vidéo 42/)).toBeTruthy()
    expect(within(change).getByRole('link', { name: "Vidéo d'origine" }).getAttribute('href')).toBe('/assets/42')
    const created = within(list).getByRole('listitem', { name: 'Envoi 6' })
    expect(within(created).getByText("Auto (l'IA choisit)")).toBeTruthy()
    expect(within(created).getByText(/créé dans l'app/)).toBeTruthy()
    expect(within(created).queryByText('Voir le Reel')).toBeNull()
    fireEvent.click(within(created).getByRole('button', { name: 'Modifier la consigne' }))
    expect(within(created).queryByRole('group', { name: 'Mode' })).toBeNull() // a DM order's choice only
  })

  it('Créer une vidéo: sends a topic with a style, then shows Mes envois', async () => {
    const calls = stubApi({
      'POST /api/work-orders': [200, order(8, { source: 'create', style: 'paper', status: 'scheduled' })],
      'GET /api/work-orders?source=mine': [200, []],
    })
    renderPage()
    await screen.findByRole('list', { name: 'Tendances' })
    fireEvent.click(screen.getByRole('button', { name: 'Créer une vidéo' }))
    const sheet = screen.getByRole('dialog', { name: 'Créer une vidéo' })
    const send = within(sheet).getByRole('button', { name: "Envoyer à l'IA" }) as HTMLButtonElement
    expect(send.disabled).toBe(true)
    fireEvent.change(within(sheet).getByLabelText('Le sujet ou ta consigne'), { target: { value: ' Pourquoi on a faim le soir ' } })
    fireEvent.click(await within(sheet).findByRole('button', { name: 'Papier' }))
    fireEvent.click(send)
    expect((await screen.findByRole('status')).textContent).toContain('dans Mes envois')
    expect(calls.find((c) => c.key === 'POST /api/work-orders')?.body).toEqual({ instruction: 'Pourquoi on a faim le soir', style: 'paper' })
    expect(await screen.findByRole('tabpanel', { name: 'Mes envois' })).toBeTruthy()
  })

  it('Créer une vidéo still offers Auto when the styles cannot load', async () => {
    stubApi({ 'GET /api/styles': [503, { error: 'styles_unavailable', message: 'Node.js not found' }] })
    renderPage()
    await screen.findByRole('list', { name: 'Tendances' })
    fireEvent.click(screen.getByRole('button', { name: 'Créer une vidéo' }))
    const sheet = screen.getByRole('dialog', { name: 'Créer une vidéo' })
    expect((await within(sheet).findByRole('alert')).textContent).toContain('Styles indisponibles')
    expect(within(sheet).getByRole('button', { name: "Auto (l'IA choisit)" })).toBeTruthy()
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
