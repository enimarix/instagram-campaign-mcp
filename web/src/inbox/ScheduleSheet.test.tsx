import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import type { Asset } from '../api/client'
import ScheduleSheet, { ScheduledSlot } from './ScheduleSheet'

const ASSET: Asset = {
  id: 3, status: 'approved', verdict: 'liked', self_score_reason: 'ok',
  caption: 'c', batch_date: '2026-11-17', preview_url: null, thumbnail_url: null,
}
const SLOT = { publish_at: '2030-11-19T10:00:00+00:00', local: '2030-11-19T11:00:00+01:00' }

type Call = { method: string; url: string; body: unknown }

function stubApi(routes: Record<string, [number, unknown]> = {}) {
  const calls: Call[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET'
    calls.push({ method, url, body: init?.body ? JSON.parse(String(init.body)) : undefined })
    const all: Record<string, [number, unknown]> = {
      'GET /api/assets/3/proposed-slot': [200, { ...SLOT, needs_confirmation: false, ai_label: true }],
      'POST /api/assets/3/schedule': [200, { asset: { ...ASSET, status: 'scheduled' } }],
      ...routes,
    }
    const [status, body] = all[`${method} ${url.split('?')[0]}`] ?? [404, { error: 'not_found' }]
    return new Response(JSON.stringify(body), { status })
  }))
  return calls
}

const scheduled = (calls: Call[]) => calls.filter((c) => c.method === 'POST')

function sheet() {
  const onScheduled = vi.fn()
  render(<ScheduleSheet assetId={3} onScheduled={onScheduled} onClose={() => {}} />)
  return onScheduled
}

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

describe('ScheduleSheet', () => {
  it('shows the proposed local time and accept posts it', async () => {
    const calls = stubApi()
    const onScheduled = sheet()
    expect((await screen.findByText('mar. 19 nov. 11:00')).tagName).toBe('STRONG')
    expect(screen.getByText('Publiée avec l’étiquette IA d’Instagram')).toBeTruthy()
    expect(screen.queryByRole('checkbox')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Accepter' }))
    await waitFor(() => expect(onScheduled).toHaveBeenCalledWith({ ...ASSET, status: 'scheduled' }))
    expect(scheduled(calls)).toEqual([{ method: 'POST', url: '/api/assets/3/schedule',
      body: { publish_at: SLOT.publish_at, confirmed: false } }])
  })

  it('an eligible (explore) video can be scheduled as a trial Reel', async () => {
    const calls = stubApi({ 'GET /api/assets/3/proposed-slot': [200, { ...SLOT, needs_confirmation: false, ai_label: false, trial_eligible: true }] })
    const onScheduled = sheet()
    const box = await screen.findByRole('checkbox', { name: 'Reel d’essai (les non-abonnés d’abord)' })
    fireEvent.click(box)
    fireEvent.click(screen.getByRole('button', { name: 'Accepter' }))
    await waitFor(() => expect(onScheduled).toHaveBeenCalled())
    expect(scheduled(calls)[0].body).toEqual({ publish_at: SLOT.publish_at, confirmed: false, trial: 'SS_PERFORMANCE' })
  })

  it('picks another time and sends it as ISO with an offset', async () => {
    const calls = stubApi()
    const onScheduled = sheet()
    await screen.findByText('mar. 19 nov. 11:00')
    fireEvent.click(screen.getByRole('button', { name: 'Choisir une autre heure' }))
    const input = screen.getByLabelText('Une autre heure') as HTMLInputElement
    expect(input.type).toBe('datetime-local')
    expect(new Date(input.value).toISOString()).toBe('2030-11-19T10:00:00.000Z') // prefilled
    fireEvent.change(input, { target: { value: '2026-11-20T18:30' } })
    fireEvent.click(screen.getByRole('button', { name: 'Programmer à cette heure' }))
    await waitFor(() => expect(onScheduled).toHaveBeenCalled())
    expect(scheduled(calls)[0].body).toEqual({
      publish_at: new Date('2026-11-20T18:30').toISOString(), confirmed: false })
  })

  it("shows the server's refusal and stays open", async () => {
    stubApi({ 'POST /api/assets/3/schedule': [409, { error: 'qc', message: 'asset 3 has not passed QC' }] })
    const onScheduled = sheet()
    await screen.findByText('mar. 19 nov. 11:00')
    fireEvent.click(screen.getByRole('button', { name: 'Accepter' }))
    expect((await screen.findByRole('alert')).textContent).toBe('asset 3 has not passed QC')
    expect(onScheduled).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Accepter' })).toHaveProperty('disabled', false)
  })

  it('needs the confirmation for a commentary clip', async () => {
    const calls = stubApi({
      'GET /api/assets/3/proposed-slot': [200, { ...SLOT, needs_confirmation: true, ai_label: false }] })
    sheet()
    const box = await screen.findByRole('checkbox')
    expect(screen.queryByText("Published with Instagram's AI label")).toBeNull()
    const accept = screen.getByRole('button', { name: 'Accepter' })
    expect(accept).toHaveProperty('disabled', true)
    fireEvent.click(box)
    expect(accept).toHaveProperty('disabled', false)
    fireEvent.click(accept)
    await waitFor(() => expect(scheduled(calls)[0]?.body).toEqual({
      publish_at: SLOT.publish_at, confirmed: true }))
  })
})

describe('ScheduledSlot', () => {
  it('shows the slot and unschedules', async () => {
    const calls = stubApi({
      'GET /api/assets/3/slot': [200, { ...SLOT, post_id: 9 }],
      'POST /api/assets/3/unschedule': [200, ASSET],
    })
    const onUnscheduled = vi.fn()
    render(<ScheduledSlot assetId={3} onUnscheduled={onUnscheduled} />)
    expect(await screen.findByText('mar. 19 nov. 11:00')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Déprogrammer' }))
    await waitFor(() => expect(onUnscheduled).toHaveBeenCalledWith(ASSET))
    expect(scheduled(calls).map((c) => c.url)).toEqual(['/api/assets/3/unschedule'])
  })
})
