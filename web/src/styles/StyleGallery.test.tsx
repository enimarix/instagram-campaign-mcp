import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import type { CatalogStyle } from '../api/client'
import { StyleGallery } from './StyleGallery'

const CREDIT = { text: 'Lemo-Opuscar by Lemomo (LemoLab)', url: 'https://x', licence: 'CC BY 4.0', licence_url: 'https://cc' }
const entry = (id: string, label: string, over: Partial<CatalogStyle> = {}): CatalogStyle => ({
  id, family: id.startsWith('lemo:') ? 'lemo' : 'studio', label, essence: null, category: null, tags: [],
  preview: { poster: null, clip: null }, favourite: false, selectable: true, why_not: null,
  credit: id.startsWith('lemo:') ? CREDIT : null, ...over,
})
const CATALOG = [
  entry('voxel', '3D 8-bit', { favourite: true }),
  entry('paper', 'Papier', { essence: 'Papier découpé' }),
  entry('lemo:watercolor', 'Watercolor Brush', { category: 'Painting', essence: 'Wet paint blooms.',
    preview: { poster: '/api/style-catalog/lemo:watercolor/preview/poster', clip: null } }),
  entry('lemo:manga-panels', 'Manga Panels', { category: 'Cartoons', selectable: false, why_not: 'Demande un générateur (✦)' }),
]

function stubApi(answers: Record<string, [number, unknown]>) {
  const calls: { key: string; body?: unknown }[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method ?? 'GET'} ${url}`
    calls.push({ key, body: init?.body ? JSON.parse(String(init.body)) : undefined })
    const [status, body] = answers[key] ?? [404, { error: 'not_found' }]
    return new Response(JSON.stringify(body), { status })
  }))
  return calls
}

const names = (region: HTMLElement) =>
  within(region).queryAllByRole('listitem').map((li) => within(li).getAllByRole('button')[0].getAttribute('aria-label'))

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

describe('StyleGallery (172)', () => {
  it('shows favourites first, then filters by family, category and search', async () => {
    stubApi({ 'GET /api/style-catalog': [200, CATALOG] })
    render(<StyleGallery />)
    expect(names(await screen.findByRole('region', { name: 'Favoris' }))).toEqual(['3D 8-bit'])
    const all = screen.getByRole('region', { name: 'Tous les styles' })
    expect(names(all)).toEqual(['Papier', 'Watercolor Brush', 'Manga Panels'])
    expect(within(all).getAllByText('Lemo')).toHaveLength(2)
    expect(within(all).getByText('Non disponible')).toBeTruthy()

    fireEvent.click(within(screen.getByRole('group', { name: 'Famille' })).getByRole('button', { name: 'Lemo' }))
    expect(screen.queryByRole('region', { name: 'Favoris' })).toBeNull()
    // desktop wraps both chip rows (all categories visible); the phone keeps the swipe row
    for (const g of ['Famille', 'Catégorie']) expect(screen.getByRole('group', { name: g }).className).toMatch(/overflow-x-auto.*lg:flex-wrap lg:overflow-visible/)
    fireEvent.click(within(screen.getByRole('group', { name: 'Catégorie' })).getByRole('button', { name: 'Cartoons' }))
    expect(names(screen.getByRole('region', { name: 'Tous les styles' }))).toEqual(['Manga Panels'])

    fireEvent.click(screen.getByRole('button', { name: 'Tous' }))
    fireEvent.change(screen.getByRole('searchbox', { name: 'Chercher un style' }), { target: { value: 'paint' } })
    expect(names(screen.getByRole('region', { name: 'Tous les styles' }))).toEqual(['Watercolor Brush'])
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'zzz' } })
    expect(screen.getByText('Aucun style')).toBeTruthy()
  })

  it('stars a style (and puts it back when the server refuses)', async () => {
    const calls = stubApi({
      'GET /api/style-catalog': [200, CATALOG],
      'PATCH /api/style-catalog/paper': [200, { ...CATALOG[1], favourite: true }],
    })
    render(<StyleGallery />)
    fireEvent.click(await screen.findByRole('button', { name: 'Favori : Papier' }))
    expect(names(screen.getByRole('region', { name: 'Favoris' }))).toEqual(['3D 8-bit', 'Papier'])
    expect(calls.at(-1)).toEqual({ key: 'PATCH /api/style-catalog/paper', body: { favourite: true } })

    fireEvent.click(screen.getByRole('button', { name: 'Favori : Watercolor Brush' }))  // no answer: 404
    expect(names(screen.getByRole('region', { name: 'Favoris' }))).toContain('Watercolor Brush')
    await vi.waitFor(() =>
      expect(names(screen.getByRole('region', { name: 'Favoris' }))).not.toContain('Watercolor Brush'))
  })

  it('opens the detail sheet with the credit, and selects only selectable styles', async () => {
    stubApi({ 'GET /api/style-catalog': [200, CATALOG] })
    const onSelect = vi.fn()
    render(<StyleGallery onSelect={onSelect} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Manga Panels' }))
    let sheet = screen.getByRole('dialog', { name: 'Manga Panels' })
    expect(within(sheet).getByText('Demande un générateur (✦)')).toBeTruthy()
    expect((within(sheet).getByRole('button', { name: 'Choisir ce style' }) as HTMLButtonElement).disabled).toBe(true)
    fireEvent.keyDown(sheet, { key: 'Escape' })

    fireEvent.click(screen.getByRole('button', { name: 'Watercolor Brush' }))
    sheet = screen.getByRole('dialog', { name: 'Watercolor Brush' })
    expect(within(sheet).getByRole('link', { name: 'Lemo-Opuscar by Lemomo (LemoLab)' })).toBeTruthy()
    expect(within(sheet).getByRole('link', { name: 'CC BY 4.0' })).toBeTruthy()
    fireEvent.click(within(sheet).getByRole('button', { name: 'Choisir ce style' }))
    expect(onSelect).toHaveBeenCalledWith('lemo:watercolor', expect.objectContaining({ id: 'lemo:watercolor' }))
  })

  it('says when the catalog is down', async () => {
    stubApi({ 'GET /api/style-catalog': [503, { error: 'styles_unavailable' }] })
    render(<StyleGallery />)
    expect((await screen.findByRole('alert')).textContent).toContain('Styles indisponibles')
  })
})
