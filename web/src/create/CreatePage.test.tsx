import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import type { CatalogStyle, WorkOrder } from '../api/client'
import CreatePage from './CreatePage'
import { planOrders, stage, toggleStyle } from './prompt'

const entry = (id: string, label: string, over: Partial<CatalogStyle> = {}): CatalogStyle => ({
  id, family: id.startsWith('lemo:') ? 'lemo' : 'studio', label, essence: null, category: null, tags: [],
  preview: { poster: null, clip: null }, favourite: false, selectable: true, why_not: null, credit: null, ...over,
})
const CATALOG = [
  entry('voxel', '3D 8-bit', { favourite: true }),
  entry('lemo:watercolor', 'Watercolor Brush', { favourite: true }),
  entry('paper', 'Papier'),
]
const hoursAgo = (h: number) => new Date(Date.now() - h * 3600_000).toISOString()
const order = (id: number, over: Partial<WorkOrder> = {}): WorkOrder => ({
  id, source: 'create', style: null, from_asset_id: null, source_id: null, pick_id: null, sender_username: null,
  received_at: null, created_at: hoursAgo(2), scheduled_at: hoursAgo(2), permalink: null, embed_url: null,
  own_reel: false, instruction: 'Pourquoi on a faim le soir', mode: 'owner', status: 'scheduled', skip_reason: null,
  blocked_reason: null, analysis: null, idea_id: null, asset_id: null, updated_at: hoursAgo(1), idea_hook: null,
  video_status: null, topic: null, caption_quote: null, thumbnail_url: null, likes: null, comments: null, views: null,
  ...over,
})
const ASSET = { id: 17, status: 'ready', caption: 'Les protéines du matin', thumbnail_url: '/media/t17.jpg' }

type Answer = [number, unknown] | ((body: unknown) => [number, unknown])
function stubApi(answers: Record<string, Answer>) {
  const calls: { key: string; body?: unknown }[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method ?? 'GET'} ${url}`
    calls.push({ key, body: init?.body ? JSON.parse(String(init.body)) : undefined })
    const answer = answers[key] ?? [404, { error: 'not_found' }]
    const [status, body] = typeof answer === 'function' ? answer(calls.at(-1)?.body) : answer
    return new Response(status === 204 ? null : JSON.stringify(body), { status })
  }))
  return calls
}
const sent = (calls: { key: string; body?: unknown }[], prefix: string) => calls.filter((c) => c.key.startsWith(prefix))

function renderPage() {
  render(<MemoryRouter><CreatePage /></MemoryRouter>)
}
const prompt = () => screen.getByRole('textbox', { name: 'Quelle vidéo ?' })
const styleGroup = () => screen.getByRole('group', { name: 'Style' })

beforeAll(() => {
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

describe('prompt (174)', () => {
  it('plans one order per style; video IDs alone are restyles, with words a new video naming them', () => {
    expect(planOrders({ text: 'Le petit-déj', styles: ['voxel', null], address: 'tu', length: 'court' })).toEqual([
      { kind: 'create', style: 'voxel', instruction: 'Le petit-déj Tutoiement (tu). Durée visée : environ 20 s.' },
      { kind: 'create', style: null, instruction: 'Le petit-déj Tutoiement (tu). Durée visée : environ 20 s.' },
    ])
    expect(planOrders({ text: '#17 http://studio.local/assets/18', styles: ['paper'], address: null, length: null })).toEqual([
      { kind: 'restyle', assetId: 17, style: 'paper', note: undefined },
      { kind: 'restyle', assetId: 18, style: 'paper', note: undefined },
    ])
    const [one] = planOrders({ text: 'comme #17 mais plus drôle', styles: [null], address: null, length: null })
    expect(one).toMatchObject({ kind: 'create', style: null })
    expect(one.kind === 'create' && one.instruction).toContain("#17 : vidéo du studio, id d'asset")
    // a hashtag is not a video id
    expect(planOrders({ text: '#musculation', styles: [null], address: null, length: null })[0].kind).toBe('create')
  })

  it('keeps Auto alone until a style is picked, and at most 4 styles', () => {
    expect(toggleStyle([null], 'voxel')).toEqual(['voxel'])
    expect(toggleStyle(['voxel'], 'voxel')).toEqual([null])
    expect(toggleStyle(['voxel'], null)).toEqual(['voxel', null])
    expect(toggleStyle(['a', 'b', 'c', 'd'], 'e')).toEqual(['a', 'b', 'c', 'd'])
  })
})

describe('CreatePage (174)', () => {
  it('shows the videos the prompt names as chips; an unknown one blocks the send', async () => {
    stubApi({
      'GET /api/style-catalog': [200, CATALOG],
      'GET /api/work-orders?source=mine': [200, []],
      'GET /api/assets/17': [200, ASSET],
    })
    renderPage()
    fireEvent.change(prompt(), { target: { value: 'refais #17 et #99 en plus court' } })
    const refs = await screen.findByRole('list', { name: 'Références' })
    expect(await within(refs).findByText('Les protéines du matin')).toBeTruthy()
    expect(await within(refs).findByText('introuvable')).toBeTruthy()
    expect(screen.getByText('Pas de vidéo #99 dans le studio.')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Envoyer' }).hasAttribute('disabled')).toBe(true)
  })

  it('sends one order per picked style (favourites and the gallery), with the address', async () => {
    const calls = stubApi({
      'GET /api/style-catalog': [200, CATALOG],
      'GET /api/work-orders?source=mine': [200, []],
      'POST /api/work-orders': [200, order(1)],
    })
    renderPage()
    fireEvent.change(prompt(), { target: { value: 'Pourquoi on a faim le soir' } })
    fireEvent.click(await within(styleGroup()).findByRole('button', { name: '3D 8-bit' }))
    fireEvent.click(within(styleGroup()).getByRole('button', { name: 'Watercolor Brush' }))
    // a style that is not a favourite, from « Tous les styles »
    fireEvent.click(within(styleGroup()).getByRole('button', { name: 'Tous les styles' }))
    const sheet = screen.getByRole('dialog', { name: 'Tous les styles' })
    fireEvent.click((await within(sheet).findAllByRole('button', { name: 'Papier' }))[0])
    fireEvent.click(screen.getByRole('button', { name: 'Choisir ce style' }))
    expect(screen.queryByRole('dialog', { name: 'Tous les styles' })).toBeNull()
    expect(within(styleGroup()).getByRole('button', { name: 'Papier' }).getAttribute('aria-pressed')).toBe('true')
    expect(within(styleGroup()).getByRole('button', { name: "Auto (l'IA choisit)" }).getAttribute('aria-pressed')).toBe('false')
    fireEvent.click(within(screen.getByRole('group', { name: 'Adresse' })).getByRole('button', { name: 'Vous' }))

    fireEvent.click(screen.getByRole('button', { name: 'Envoyer (3 vidéos)' }))
    await waitFor(() => expect(sent(calls, 'POST /api/work-orders')).toHaveLength(3))
    const instruction = 'Pourquoi on a faim le soir Vouvoiement (vous).'
    expect(sent(calls, 'POST').map((c) => c.body)).toEqual([
      { instruction, style: 'voxel' }, { instruction, style: 'lemo:watercolor' }, { instruction, style: 'paper' },
    ])
    await waitFor(() => expect((prompt() as HTMLTextAreaElement).value).toBe(''))
    expect(sent(calls, 'GET /api/work-orders').length).toBeGreaterThan(1) // the pile reloaded
  })

  it('restyles a video named alone; a failed style stays picked, the sent one does not', async () => {
    const calls = stubApi({
      'GET /api/style-catalog': [200, CATALOG],
      'GET /api/work-orders?source=mine': [200, []],
      'GET /api/assets/17': [200, ASSET],
      'POST /api/assets/17/restyle': (body) => ((body as { style: string }).style === 'paper'
        ? [422, { error: 'invalid', message: "video 17 is already in style 'paper'" }]
        : [200, order(2, { source: 'change', from_asset_id: 17 })]),
    })
    renderPage()
    fireEvent.change(prompt(), { target: { value: '#17' } })
    fireEvent.click(await within(styleGroup()).findByRole('button', { name: '3D 8-bit' }))
    fireEvent.click(within(styleGroup()).getByRole('button', { name: 'Tous les styles' }))
    fireEvent.click((await within(screen.getByRole('dialog', { name: 'Tous les styles' })).findAllByRole('button', { name: 'Papier' }))[0])
    fireEvent.click(screen.getByRole('button', { name: 'Choisir ce style' }))
    await screen.findByText('Les protéines du matin')
    fireEvent.click(screen.getByRole('button', { name: 'Envoyer (2 vidéos)' }))
    expect((await screen.findByRole('alert')).textContent).toBe("#17, Papier : video 17 is already in style 'paper'")
    expect(sent(calls, 'POST').map((c) => c.body)).toEqual([{ style: 'voxel' }, { style: 'paper' }])
    expect(within(styleGroup()).getByRole('button', { name: '3D 8-bit' }).getAttribute('aria-pressed')).toBe('false')
    expect(within(styleGroup()).getByRole('button', { name: 'Papier' }).getAttribute('aria-pressed')).toBe('true')
    expect((prompt() as HTMLTextAreaElement).value).toBe('#17')
  })

  it('lists la pile with each stage, the AI reply, and cancels or adds a note to a waiting order', async () => {
    const orders = [
      order(6, { status: 'scheduled', blocked_reason: 'trois films faits aujourd’hui', style: 'lemo:watercolor' }),
      order(5, { status: 'in_production', idea_id: 9, idea_hook: 'Ton estomac a une horloge', style: 'voxel' }),
      order(4, { status: 'in_feed', asset_id: 40 }),
      order(3, { status: 'skipped', skip_reason: 'le film n’a pas abouti : timed out', style: 'lemo:watercolor' }),
    ]
    const calls = stubApi({
      'GET /api/style-catalog': [200, CATALOG],
      'GET /api/work-orders?source=mine': [200, orders],
      'DELETE /api/research/work-orders/6': [204, null],
      'PATCH /api/work-orders/6': [200, orders[0]],
    })
    vi.stubGlobal('confirm', () => true)
    renderPage()
    const pile = await screen.findByRole('list', { name: 'La pile' })
    const card = (id: number) => within(pile).getByRole('listitem', { name: `Commande ${id}` })
    expect(within(card(6)).getByText('En attente (bloqué)')).toBeTruthy()
    expect(within(card(6)).getByText('En attente : trois films faits aujourd’hui')).toBeTruthy()
    expect(within(card(6)).getByText('Watercolor Brush')).toBeTruthy()
    expect(within(card(5)).getByText("L'IA écrit")).toBeTruthy()
    expect(within(card(5)).getByText("L'IA : Ton estomac a une horloge")).toBeTruthy()
    expect(within(card(4)).getByRole('link', { name: "Voir dans l'Inbox" }).getAttribute('href')).toBe('/assets/40')
    expect(within(card(3)).getByText('Échoué')).toBeTruthy()
    expect(within(card(5)).queryByRole('button', { name: 'Annuler' })).toBeNull() // started: too late

    fireEvent.click(within(card(6)).getByRole('button', { name: 'Ajouter une note' }))
    fireEvent.change(within(card(6)).getByRole('textbox', { name: "Ta note pour l'IA" }), { target: { value: 'cite une source' } })
    fireEvent.click(within(card(6)).getByRole('button', { name: 'Ajouter' }))
    await waitFor(() => expect(sent(calls, 'PATCH')).toHaveLength(1))
    expect(sent(calls, 'PATCH')[0].body).toEqual({ instruction: 'Pourquoi on a faim le soir\nNote : cite une source' })

    fireEvent.click(await within(card(6)).findByRole('button', { name: 'Annuler' }))
    await waitFor(() => expect(sent(calls, 'DELETE /api/research/work-orders/6')).toHaveLength(1))
  })

  it('names every stage, Lemo films and renders included', () => {
    const label = (over: Partial<WorkOrder>) => stage(order(1, over))[0]
    expect(label({ status: 'needs_instruction' })).toBe('En attente de ta consigne')
    expect(label({ status: 'scheduled' })).toBe('En attente')
    expect(label({ status: 'in_production', style: 'lemo:watercolor' })).toBe('Le film se fabrique')
    expect(label({ status: 'in_production', video_status: 'rendering' })).toBe('Rendu en cours')
    expect(label({ status: 'in_production', video_status: 'failed' })).toBe('Rendu échoué')
    expect(label({ status: 'skipped' })).toBe("Refusé par l'IA")
  })
})
