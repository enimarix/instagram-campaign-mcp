import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import type { Asset } from '../api/client'
import InboxPage from './InboxPage'

const asset = (id: number, fields: Partial<Asset> = {}): Asset => ({
  id, status: 'ready', verdict: 'none', self_score: 5, self_score_reason: 'ok',
  caption: `caption ${id}`, batch_date: '2026-11-17', preview_url: `/api/media/${id}.mp4`,
  thumbnail_url: null, track: 'motion', strategy: 'exploit', ...fields,
})

const ASSETS = [
  asset(1, { self_score: 9, self_score_reason: 'strong hook', strategy: 'explore' }),
  asset(2, { self_score: 7, verdict: 'liked' }),
]

type Call = { method: string; url: string; body: unknown }

// Routes "METHOD /path" to [status, body]; records every call.
function stubApi(routes: Record<string, [number, unknown]> = {}) {
  const calls: Call[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET'
    calls.push({ method, url, body: init?.body ? JSON.parse(String(init.body)) : undefined })
    const all: Record<string, [number, unknown]> = {
      'GET /api/assets': [200, ASSETS],
      'GET /api/taxonomy': [200, { feedback_reasons: { values: [
        { id: 'weak_hook', label: 'Weak hook' }, { id: 'too_long', label: 'Too long' }] } }],
      ...routes,
    }
    const [status, body] = all[`${method} ${url.split('?')[0]}`] ?? [404, { error: 'not_found' }]
    return new Response(JSON.stringify(body), { status })
  }))
  return calls
}

const card = (id: number) => screen.getByRole('article', { name: `Video ${id}` })
const posts = (calls: Call[]) => calls.filter((c) => c.method === 'POST')

beforeAll(() => {
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

describe('InboxPage', () => {
  it('lists the batch in API order with the counter, player and badges', async () => {
    const calls = stubApi()
    render(<InboxPage />)
    expect(await screen.findByText('1 of 2 reviewed')).toBeTruthy()
    expect(screen.getAllByRole('article').map((a) => a.getAttribute('aria-label')))
      .toEqual(['Video 1', 'Video 2'])
    const d = new Date()
    const today = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
    expect(calls.map((c) => c.url)).toContain(`/api/assets?batch_date=${today}`)
    const video = card(1).querySelector('video')!
    expect(video.getAttribute('src')).toBe('/api/media/1.mp4')
    expect(video.muted && video.loop && video.playsInline).toBe(true)
    expect(within(card(1)).getByText('9/10')).toBeTruthy()
    expect(within(card(1)).getByText('Explore')).toBeTruthy()
    expect(within(card(2)).queryByText('Explore')).toBeNull()
  })

  it('sends the filters to the API', async () => {
    const calls = stubApi()
    render(<InboxPage />)
    await screen.findByText('1 of 2 reviewed')
    fireEvent.change(screen.getByLabelText('Status'), { target: { value: 'ready' } })
    await waitFor(() => expect(calls.at(-1)?.url).toContain('status=ready'))
  })

  it('like updates the counter and posts the verdict', async () => {
    const calls = stubApi({ 'POST /api/assets/1/verdict': [200, asset(1, { verdict: 'liked' })] })
    render(<InboxPage />)
    await screen.findByText('1 of 2 reviewed')
    fireEvent.click(within(card(1)).getByRole('button', { name: 'Like' }))
    expect(screen.getByText('2 of 2 reviewed')).toBeTruthy()
    await waitFor(() => expect(posts(calls)).toEqual([
      { method: 'POST', url: '/api/assets/1/verdict', body: { verdict: 'liked' } }]))
  })

  it('dislike opens the reason sheet and saving posts the reason codes', async () => {
    const calls = stubApi({
      'POST /api/assets/1/verdict': [200, asset(1, { verdict: 'disliked' })],
      'POST /api/assets/1/feedback': [201, { id: 1 }],
    })
    render(<InboxPage />)
    await screen.findByText('1 of 2 reviewed')
    fireEvent.click(within(card(1)).getByRole('button', { name: 'Dislike' }))
    const sheet = await screen.findByRole('dialog', { name: 'What was wrong?' })
    fireEvent.click(await within(sheet).findByRole('button', { name: 'Weak hook' }))
    fireEvent.click(within(sheet).getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(posts(calls).at(-1)).toEqual(
      { method: 'POST', url: '/api/assets/1/feedback', body: { reason_codes: ['weak_hook'] } })
  })

  it('the sheet closes on Esc (native close) without posting feedback', async () => {
    const calls = stubApi({ 'POST /api/assets/1/verdict': [200, asset(1, { verdict: 'disliked' })] })
    render(<InboxPage />)
    await screen.findByText('1 of 2 reviewed')
    fireEvent.click(within(card(1)).getByRole('button', { name: 'Dislike' }))
    ;(await screen.findByRole('dialog') as HTMLDialogElement).close()
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(posts(calls).map((c) => c.url)).toEqual(['/api/assets/1/verdict'])
  })

  it('rolls back a failed verdict and shows the error', async () => {
    stubApi({ 'POST /api/assets/1/verdict': [500, { error: 'boom' }] })
    render(<InboxPage />)
    await screen.findByText('1 of 2 reviewed')
    fireEvent.click(within(card(1)).getByRole('button', { name: 'Like' }))
    expect((await screen.findByRole('alert')).textContent).toContain('boom')
    expect(screen.getByText('1 of 2 reviewed')).toBeTruthy()
  })

  it('keyboard: l likes the current video, ignored while typing; j moves on', async () => {
    const calls = stubApi({
      'POST /api/assets/1/verdict': [200, asset(1, { verdict: 'liked' })],
      'POST /api/assets/2/verdict': [200, asset(2, { verdict: 'disliked' })],
    })
    render(<InboxPage />)
    await screen.findByText('1 of 2 reviewed')
    fireEvent.keyDown(screen.getByLabelText('Batch date'), { key: 'l' })
    expect(posts(calls)).toEqual([])
    fireEvent.keyDown(window, { key: 'l' })
    expect(screen.getByText('2 of 2 reviewed')).toBeTruthy()
    fireEvent.keyDown(window, { key: 'j' })
    fireEvent.keyDown(window, { key: 'd' })
    await waitFor(() => expect(posts(calls).map((c) => [c.url, c.body])).toEqual([
      ['/api/assets/1/verdict', { verdict: 'liked' }],
      ['/api/assets/2/verdict', { verdict: 'disliked' }],
    ]))
  })

  it('approve shows the new status', async () => {
    stubApi({ 'POST /api/assets/1/approve': [200, asset(1, { status: 'approved' })] })
    render(<InboxPage />)
    await screen.findByText('1 of 2 reviewed')
    fireEvent.click(within(card(1)).getByRole('button', { name: 'Approve' }))
    expect(await within(card(1)).findByText('approved')).toBeTruthy()
    expect(within(card(1)).queryByRole('button', { name: 'Approve' })).toBeNull()
  })
})
