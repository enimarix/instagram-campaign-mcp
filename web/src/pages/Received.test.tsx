import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, expect, it, vi } from 'vitest'
import type { WorkOrder } from '../api/client'
import { ToastProvider } from '../ui/Toast'
import Received from './Received'

const now = new Date().toISOString()
const order = (id: number, over: Partial<WorkOrder> = {}): WorkOrder => ({
  id, source: 'dm', style: null, method: 'rea', from_asset_id: null, source_id: null, pick_id: id, sender_username: 'amine',
  received_at: now, created_at: now, scheduled_at: null, permalink: null, embed_url: null,
  own_reel: false, instruction: 'garde la chute', mode: 'owner', status: 'received', skip_reason: null,
  blocked_reason: null, analysis: null, idea_id: null, asset_id: null, updated_at: now, idea_hook: null,
  video_status: null, topic: null, caption_quote: null, thumbnail_url: null, likes: null, comments: null, views: null,
  ...over,
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

it('keeps every Reel in the order it came until its video is in the Inbox', async () => {
  const byStatus: Record<string, WorkOrder[]> = {
    received: [order(9)],
    confirmed: [order(4, { status: 'confirmed' })],
    scheduled: [order(2, { status: 'scheduled', style: 'lemo:pictogram' })],
    in_production: [order(6, { status: 'scheduled', style: 'lemo:rea-video', waits_for_style: 'Phone UI 3D' })],
    skipped: [order(7, { status: 'skipped', skip_reason: 'le rendu a échoué' }),
      order(5, { status: 'skipped', skip_reason: 'annulée par le propriétaire' }), // « Retirer »
      order(3, { status: 'skipped', method: null, skip_reason: 'vieux' })], // never confirmed here
  }
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    const status = new URL(url, 'http://x').searchParams.get('status')
    if (url.startsWith('/api/style-catalog')) {
      return new Response(JSON.stringify([{ id: 'lemo:pictogram', label: 'Pictogram Motion' }]))
    }
    return new Response(JSON.stringify(status ? byStatus[status] : []))
  }))
  render(<MemoryRouter><ToastProvider><Received /></ToastProvider></MemoryRouter>)
  await waitFor(() => expect(screen.getAllByRole('listitem')).toHaveLength(5))
  expect(screen.getAllByRole('listitem').map((li) => li.getAttribute('aria-label')))
    .toEqual(['Reel reçu 2', 'Reel reçu 4', 'Reel reçu 6', 'Reel reçu 7', 'Reel reçu 9'])
  expect(screen.getByText('Attend son nouveau style')).toBeTruthy() // never a silent « Lancé »
  expect(screen.getByText('Copie plan par plan (rea-video)')).toBeTruthy() // a copy: its name, not its id
  expect(screen.getByText(/l'IA a demandé le style « Phone UI 3D »/)).toBeTruthy()
  expect(await screen.findByText('Pictogram Motion')).toBeTruthy() // a launched film: its name
  expect(screen.getByText('le rendu a échoué')).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Relancer → Planning' })).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Retirer' })).toBeTruthy()
})
