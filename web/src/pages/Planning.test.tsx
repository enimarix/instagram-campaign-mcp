import { cleanup, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { PlanningItem } from '../api/client'
import Planning from './Planning'

const soon = (min: number) => new Date(Date.now() + min * 60_000).toISOString()
const item = (over: Partial<PlanningItem>): PlanningItem => ({
  section: 'next', kind: 'render', title: 'Pourquoi on a faim', source: 'create', ids: {}, style: null,
  engine: 'remotion', voice: null, est_start: soon(1), est_duration_s: 600, est_ready: soon(11), estimated: true,
  why_here: "File des rendus : le plus ancien d'abord.", waits_on: null, stage: null, progress: null, ...over,
})

function stub(items: PlanningItem[]) {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ now: soon(0), items }))))
}
const show = () => render(<MemoryRouter><Planning /></MemoryRouter>)

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
})
