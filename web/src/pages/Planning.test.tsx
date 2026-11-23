import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { PlanningItem } from '../api/client'
import { ToastProvider } from '../ui/Toast'
import Planning from './Planning'

const soon = (min: number) => new Date(Date.now() + min * 60_000).toISOString()
const item = (over: Partial<PlanningItem>): PlanningItem => ({
  section: 'next', kind: 'render', title: 'Pourquoi on a faim', source: 'create', ids: {}, style: null,
  engine: 'remotion', voice: null, est_start: soon(1), est_duration_s: 600, est_ready: soon(11), estimated: true,
  why_here: "File des rendus : le plus ancien d'abord.", waits_on: null, not_before: null, stage: null, progress: null, ...over,
})

function stub(items: PlanningItem[]) {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ now: soon(0), items }))))
}
type Call = { method: string; url: string; body: unknown }
function stubCalls(items: PlanningItem[]) {
  const calls: Call[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET'
    calls.push({ method, url, body: init?.body ? JSON.parse(String(init.body)) : undefined })
    if (method === 'GET') return new Response(JSON.stringify({ now: soon(0), items }))
    return new Response(JSON.stringify({ not_before: null }))
  }))
  return calls
}
const show = () => render(<MemoryRouter><ToastProvider><Planning /></ToastProvider></MemoryRouter>)

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('Planning', () => {
  it('shows the chain in its three sections, linked to the video and the Inbox', async () => {
    stub([
      item({ section: 'running', title: 'Le rendu actuel', ids: { asset_id: 17 }, stage: 'rendu', progress: 0.5 }),
      item({ title: 'Ma commande', kind: 'work_order', ids: { order_id: 4 }, waits_on: 'gpu_busy', style: 'blender', engine: 'blender' }),
      item({ section: 'planned', kind: 'agent_run', title: 'Run daily-produce', source: 'schedule',
        picks_up: { orders: 2, change_requests: 1, dm_picks: 0, ideas_left: 7 } }),
    ])
    show()
    const running = await screen.findByRole('region', { name: 'En cours' })
    expect(within(running).getByRole('link', { name: 'vidéo 17' }).getAttribute('href')).toBe('/assets/17')
    expect(within(running).getByRole('progressbar').getAttribute('aria-valuenow')).toBe('50')
    const next = screen.getByRole('region', { name: 'Ensuite' })
    expect(within(next).getByText('attend le GPU')).toBeTruthy()
    expect(within(next).getByText('style blender · moteur blender')).toBeTruthy()
    expect(within(next).getByText(/10 min/)).toBeTruthy()
    const planned = screen.getByRole('region', { name: "Runs prévus de l'IA" })
    expect(within(planned).getByText(/place\(s\) pour les idées de Claude/).textContent).toContain('7')
    expect(screen.getAllByRole('link', { name: 'Inbox' })).toHaveLength(3)
    expect(screen.getAllByRole('link', { name: 'créneau' })[0].getAttribute('href')).toBe('/calendar')
  })

  it('says when nothing is planned', async () => {
    stub([])
    show()
    expect(await screen.findByText('Rien de prévu')).toBeTruthy()
  })

  it('an order that waits for the owner has no time', async () => {
    stub([item({ kind: 'work_order', waits_on: 'needs_instruction', est_start: null, est_ready: null, est_duration_s: null })])
    show()
    expect(await screen.findByText('attend ta consigne')).toBeTruthy()
    expect(screen.getByText("Pas d'heure : rien ne part sans toi.")).toBeTruthy()
  })

  it('a waiting render starts now; the running card and an order have no such button', async () => {
    const calls = stubCalls([
      item({ section: 'running', title: 'Le rendu actuel', ids: { asset_id: 17, job_id: 5 }, progress: 0.5 }),
      item({ title: 'Le suivant', ids: { asset_id: 18, job_id: 6 }, waits_on: 'gpu_busy' }),
      item({ kind: 'work_order', title: 'Ma commande', ids: { order_id: 4 } }),
    ])
    show()
    const running = await screen.findByRole('region', { name: 'En cours' })
    expect(within(running).queryByRole('button', { name: 'Lancer maintenant' })).toBeNull()
    const [button] = within(screen.getByRole('region', { name: 'Ensuite' })).getAllByRole('button', { name: 'Lancer maintenant' })
    expect(screen.getAllByRole('button', { name: 'Lancer maintenant' })).toHaveLength(1) // not on the order
    fireEvent.click(button)
    expect(await screen.findByText('Passe en tête de la file.')).toBeTruthy()
    expect(calls).toContainEqual({ method: 'POST', url: '/api/planning/render/6/start-now', body: undefined })
    await waitFor(() => expect(calls.filter((c) => c.method === 'GET').length).toBeGreaterThan(1)) // reloaded
  })

  it("a film's timer is set in owner-local time, shown on the card, and cleared", async () => {
    const calls = stubCalls([item({ kind: 'film', title: 'Un film', ids: { order_id: 4 }, waits_on: 'timer', not_before: soon(120) })])
    show()
    expect(await screen.findByText(/Minuteur : pas avant/)).toBeTruthy()
    expect(screen.getByText('attend son minuteur')).toBeTruthy()
    const input = screen.getByLabelText('Minuteur') as HTMLInputElement
    expect(input.type).toBe('datetime-local')
    fireEvent.change(input, { target: { value: '2026-11-30T14:30' } })
    fireEvent.click(screen.getByRole('button', { name: 'Régler' }))
    expect(await screen.findByText(/Minuteur réglé : pas avant/)).toBeTruthy()
    expect(calls).toContainEqual({ method: 'PUT', url: '/api/planning/film/4/timer', body: { at: new Date('2026-11-30T14:30').toISOString() } })
    fireEvent.click(screen.getByRole('button', { name: 'Retirer le minuteur' }))
    expect(await screen.findByText('Minuteur retiré.')).toBeTruthy()
    expect(calls).toContainEqual({ method: 'PUT', url: '/api/planning/film/4/timer', body: { at: null } })
  })

  it('a refused start says why', async () => {
    vi.stubGlobal('fetch', vi.fn(async (_url: string, init?: RequestInit) => init?.method
      ? new Response(JSON.stringify({ error: 'invalid', message: 'Ce rendu est en cours' }), { status: 422 })
      : new Response(JSON.stringify({ now: soon(0), items: [item({ ids: { job_id: 6 } })] }))))
    show()
    fireEvent.click(await screen.findByRole('button', { name: 'Lancer maintenant' }))
    expect(await screen.findByText('Pas fait : Ce rendu est en cours')).toBeTruthy()
  })

  it('moves a waiting render up / down and holds or releases a film (187)', async () => {
    const calls = stubCalls([
      item({ title: 'Le suivant', ids: { job_id: 6 } }),
      item({ kind: 'film', title: 'Un film', ids: { order_id: 4 }, waits_on: 'held', est_start: null, est_ready: null }),
    ])
    show()
    const [render, film] = await screen.findAllByRole('article')
    fireEvent.click(within(render).getByRole('button', { name: 'Monter' }))
    expect(await screen.findByText('Monté d’une place.')).toBeTruthy()
    fireEvent.click(within(render).getByRole('button', { name: 'Descendre' }))
    await waitFor(() => expect(calls).toContainEqual({ method: 'POST', url: '/api/planning/render/6/move', body: { by: 1 } }))
    expect(calls).toContainEqual({ method: 'POST', url: '/api/planning/render/6/move', body: { by: -1 } })
    fireEvent.click(within(render).getByRole('button', { name: 'Mettre en pause' }))
    await waitFor(() => expect(calls).toContainEqual({ method: 'PUT', url: '/api/planning/render/6/hold', body: { held: true } }))
    expect(within(film).getByText('En pause')).toBeTruthy()
    fireEvent.click(within(film).getByRole('button', { name: 'Reprendre' }))
    await waitFor(() => expect(calls).toContainEqual({ method: 'PUT', url: '/api/planning/film/4/hold', body: { held: false } }))
  })

  it('removes with a 5 s undo: nothing is sent before it closes', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      const calls = stubCalls([
        item({ title: 'Le suivant', ids: { job_id: 6 } }),
        item({ kind: 'work_order', title: 'Ma commande', ids: { order_id: 4 } }),
        item({ kind: 'work_order', title: 'Sans consigne', ids: { order_id: 5 }, waits_on: 'needs_instruction' }),
      ])
      show()
      const titles = () => screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent)
      const buttons = await screen.findAllByRole('button', { name: 'Retirer' })
      expect(buttons).toHaveLength(2) // not on the order that waits for its instruction
      fireEvent.click(buttons[0])
      expect(screen.queryByText('Le suivant')).toBeNull() // out at once
      fireEvent.click(screen.getByRole('button', { name: 'Annuler' }))
      expect(titles()).toEqual(['Le suivant', 'Ma commande', 'Sans consigne']) // back in its place
      vi.advanceTimersByTime(6000)
      expect(calls.filter((c) => c.url.endsWith('/remove'))).toEqual([])
      fireEvent.click(screen.getAllByRole('button', { name: 'Retirer' })[1])
      expect(screen.queryByText('Ma commande')).toBeNull()
      expect(calls.filter((c) => c.url.endsWith('/remove'))).toEqual([])
      vi.advanceTimersByTime(5000)
      await waitFor(() => expect(calls).toContainEqual({ method: 'POST', url: '/api/planning/order/4/remove', body: undefined }))
    } finally {
      vi.useRealTimers()
    }
  })

  it('leaving the page sends a removal still in its undo window', async () => {
    const calls = stubCalls([item({ kind: 'film', title: 'Un film', ids: { order_id: 4 } })])
    show()
    fireEvent.click(await screen.findByRole('button', { name: 'Retirer' }))
    cleanup()
    await waitFor(() => expect(calls).toContainEqual({ method: 'POST', url: '/api/planning/film/4/remove', body: undefined }))
  })

  it('the pause switch pauses and resumes the whole studio', async () => {
    let paused: string | null = null
    const calls: Call[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      const body = init?.body ? JSON.parse(String(init.body)) : undefined
      calls.push({ method: init?.method ?? 'GET', url, body })
      if (init?.method === 'PUT') paused = body.paused ? soon(0) : null
      return new Response(JSON.stringify(init?.method ? { paused } : { now: soon(0), items: [item({})], paused }))
    }))
    show()
    const toggle = await screen.findByRole('switch', { name: 'Tout mettre en pause' }) as HTMLInputElement
    expect(toggle.checked).toBe(false)
    fireEvent.click(toggle)
    expect(await screen.findByText('Studio en pause : rien ne démarre, ce qui tourne finit.')).toBeTruthy()
    expect(calls).toContainEqual({ method: 'PUT', url: '/api/planning/pause', body: { paused: true } })
    expect(toggle.checked).toBe(true)
    expect(screen.getByText(/Studio en pause depuis/)).toBeTruthy()
    fireEvent.click(toggle)
    expect(await screen.findByText('Studio repris : la file repart.')).toBeTruthy()
    expect(toggle.checked).toBe(false)
    expect(screen.queryByText(/Studio en pause depuis/)).toBeNull()
  })
})
