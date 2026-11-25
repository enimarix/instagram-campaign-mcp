import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Asset, AssetContext, ReactionInfo } from '../api/client'
import AssetPage from './AssetPage'

const ASSET: Asset = {
  id: 7, status: 'ready', verdict: 'none', self_score_reason: 'ok',
  caption: 'old caption', batch_date: '2026-11-17', preview_url: '/api/media/7.mp4',
  thumbnail_url: null, best_before: '2026-11-20', recipe: { ops: [{ op: 'fit_vertical' }] },
  qc: { passed: false, reasons: ['too quiet'] },
}
const CONTEXT: AssetContext = {
  idea: {
    track: 'remix', pillar: 'myths', hook: 'Wait for it', hook_type: 'question',
    hypothesis: 'questions hook better', strategy: 'explore',
    citations: [{ title: 'A paper', url: 'https://example.org/p' }, { title: 'Bad', url: 'javascript:alert(1)' }],
  },
  source: { rights_basis: 'licensed', author: 'someone', url: 'https://example.org/clip' },
  parent: { ...ASSET, id: 5 },
  children: [],
  ai_label: true,
}
const COMMENT = { id: 1, text: 'first', reason_codes: [], video_time_s: 1.5, wants_changes: 0, created_at: '' }

type Call = { method: string; url: string; body: unknown }

function stubApi(routes: Record<string, [number, unknown]> = {}) {
  const calls: Call[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET'
    calls.push({ method, url, body: init?.body ? JSON.parse(String(init.body)) : undefined })
    const all: Record<string, [number, unknown]> = {
      'GET /api/assets/7': [200, ASSET],
      'GET /api/assets/7/context': [200, CONTEXT],
      'GET /api/assets/7/feedback': [200, [COMMENT]],
      'GET /api/taxonomy': [200, { feedback_reasons: { values: [{ id: 'weak_hook', label: 'Weak hook' }] } }],
      ...routes,
    }
    const [status, body] = all[`${method} ${url}`] ?? [404, { error: 'not_found' }]
    return new Response(JSON.stringify(body), { status })
  }))
  return calls
}

function show() {
  render(
    <MemoryRouter initialEntries={['/assets/7']}>
      <Routes><Route path="/assets/:id" element={<AssetPage />} /></Routes>
    </MemoryRouter>,
  )
  return screen.findByText('first')
}

const comment = (body: unknown) => ({
  feedback: { ...COMMENT, id: 2, text: 'new' }, asset: ASSET, moved: false, reason: null, ...(body as object),
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('AssetPage', () => {
  it('renders the panel, version link, thread and a seekable pinned time', async () => {
    stubApi()
    await show()
    const panel = screen.getByRole('region', { name: 'About this video' })
    for (const text of ['HookWait for it', 'Hook typequestion', 'Hypothesisquestions hook better',
      'TrackremixExplore', 'Pillarmyths', 'Recipefit_vertical', 'Rightslicensed · credit: someone',
      'Quality checkFailed: too quiet', "Published with Instagram's AI label"])
      expect(panel.textContent).toContain(text)
    expect(screen.getByRole('link', { name: 'Older version' }).getAttribute('href')).toBe('/assets/5')
    const video = document.querySelector('video')!
    video.play = vi.fn(async () => {})
    fireEvent.click(screen.getByRole('button', { name: 'Play from 0:01' }))
    expect(video.currentTime).toBe(1.5)
  })

  it('renders citations and the credit as external-safe links only for http(s)', async () => {
    stubApi()
    await show()
    for (const name of ['A paper', 'someone']) {
      const a = screen.getByRole('link', { name })
      expect(a.getAttribute('target')).toBe('_blank')
      expect(a.getAttribute('rel')).toBe('noopener noreferrer')
    }
    expect(screen.queryByRole('link', { name: 'Bad' })).toBeNull()
  })

  it('posts a pinned comment with the player time', async () => {
    const calls = stubApi({ 'POST /api/assets/7/feedback': [200, comment({})] })
    await show()
    document.querySelector('video')!.currentTime = 3.25
    fireEvent.change(screen.getByLabelText('New comment'), { target: { value: 'too slow here' } })
    fireEvent.click(screen.getByRole('button', { name: 'Weak hook' }))
    fireEvent.click(screen.getByLabelText(/Pin to this moment/))
    fireEvent.click(screen.getByRole('button', { name: 'Add comment' }))
    expect(await screen.findByText('new')).toBeTruthy()
    expect(calls.find((c) => c.method === 'POST')!.body).toEqual({
      text: 'too slow here', reason_codes: ['weak_hook'], video_time_s: 3.25, wants_changes: false,
    })
  })

  it('says when asking for changes sent the video back, and why not', async () => {
    stubApi({ 'POST /api/assets/7/feedback': [200, comment({ moved: true, asset: { ...ASSET, status: 'revision_requested' } })] })
    await show()
    fireEvent.change(screen.getByLabelText('New comment'), { target: { value: 'redo' } })
    fireEvent.click(screen.getByRole('switch', { name: 'Ask for changes' }))
    fireEvent.click(screen.getByRole('button', { name: 'Add comment' }))
    expect(await screen.findByText('Sent back for a new version.')).toBeTruthy()
    expect(screen.getByText('revision requested')).toBeTruthy()
  })

  it('shows the server error when a caption is refused', async () => {
    const calls = stubApi({ 'PATCH /api/assets/7': [422, { error: 'invalid', message: 'caption has 31 hashtags' }] })
    await show()
    fireEvent.change(screen.getByLabelText('Caption'), { target: { value: '#a #b' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(await screen.findByText('Not saved: caption has 31 hashtags')).toBeTruthy()
    expect(calls.find((c) => c.method === 'PATCH')!.body).toEqual({ caption: '#a #b' })
  })

  describe('approve with a caption typed but not saved (UI-002)', () => {
    const APPROVED = { ...ASSET, caption: 'NEW', status: 'approved' }
    const typeAndApprove = async (text: string) => {
      await show()
      fireEvent.change(screen.getByLabelText('Caption'), { target: { value: text } })
      fireEvent.click(screen.getByRole('button', { name: 'Approve' }))
    }
    // approving opens the schedule sheet (jsdom has no modal dialogs)
    beforeEach(() => { HTMLDialogElement.prototype.showModal = function () { this.open = true } })
    const sent = (calls: Call[]) => calls.filter((c) => c.method !== 'GET').map((c) => [c.method, c.url, c.body])

    it('saves the caption first, then approves', async () => {
      const calls = stubApi({
        'PATCH /api/assets/7': [200, { ...ASSET, caption: 'NEW' }],
        'POST /api/assets/7/approve': [200, APPROVED],
      })
      await typeAndApprove('NEW')
      await waitFor(() => expect(sent(calls)).toEqual([
        ['PATCH', '/api/assets/7', { caption: 'NEW' }], ['POST', '/api/assets/7/approve', undefined]]))
    })

    it('a refused caption shows the error and does not approve', async () => {
      const calls = stubApi({ 'PATCH /api/assets/7': [422, { error: 'invalid', message: 'caption has 31 hashtags' }] })
      await typeAndApprove('#a #b')
      expect((await screen.findByRole('alert')).textContent).toBe('caption has 31 hashtags')
      expect(sent(calls)).toEqual([['PATCH', '/api/assets/7', { caption: '#a #b' }]])
    })

    it('an unchanged caption makes no PATCH', async () => {
      const calls = stubApi({ 'POST /api/assets/7/approve': [200, { ...ASSET, status: 'approved' }] })
      await typeAndApprove('old caption')
      await waitFor(() => expect(sent(calls)).toEqual([['POST', '/api/assets/7/approve', undefined]]))
    })
  })

  describe('a reaction remix', () => {
    const REMIX: Asset = { ...ASSET, recipe: { ops: [{ op: 'trim' }], inputs: { source: 's.mp4', reaction: 'reactions/1/pieces/4.mp4' } } }
    const REACTION: ReactionInfo = {
      piece: { id: 4, start_s: 60, end_s: 80, url: '/api/media/reactions/1/pieces/4.mp4' },
      reel: { id: 1, duration_s: 600, created_at: '' },
      source: { id: 2, author: 'creator', url: 'https://www.instagram.com/reel/x/', rights_basis: 'commentary', attribution: '@creator' },
      trim: { start_s: 10, end_s: 30 },
      transcript: [
        { index: 1, start_s: 9, end_s: 11, text: 'across the start' },
        { index: 2, start_s: 12, end_s: 14, text: 'insdie' },
      ],
    }
    const routes = (extra: Record<string, [number, unknown]> = {}) => stubApi({
      'GET /api/assets/7': [200, REMIX],
      'GET /api/assets/7/context': [200, { ...CONTEXT, source: REACTION.source }],
      'GET /api/assets/7/reaction': [200, REACTION],
      ...extra,
    })
    const child = { ...REMIX, id: 9, status: 'rendering', parent_asset_id: 7 }

    it('shows the reaction card: the piece, the credit and the rights', async () => {
      routes()
      await show()
      const card = await screen.findByRole('region', { name: 'Reaction' })
      for (const text of ['Piece #4 of reel #1, 1:00–1:20', 'Clip used0:10–0:30', '@creator · commentary'])
        expect(card.textContent).toContain(text)
      expect(screen.getByRole('link', { name: '@creator' }).getAttribute('href')).toBe(REACTION.source.url)
      expect(screen.getByLabelText('Reaction piece').getAttribute('src')).toBe(REACTION.piece.url)
    })

    it('uses the next piece after a confirm and links the new version', async () => {
      const calls = routes({ 'POST /api/assets/7/next-piece': [200, { asset: child }] })
      vi.stubGlobal('confirm', vi.fn(() => true))
      await show()
      fireEvent.click(await screen.findByRole('button', { name: 'Use the next reaction piece' }))
      expect(await screen.findByRole('link', { name: 'Newer version #9 (rendering)' })).toBeTruthy()
      expect(calls.filter((c) => c.url === '/api/assets/7/next-piece')).toHaveLength(1)
      expect(screen.getByText(/New version: #9/)).toBeTruthy()
    })

    it('does nothing when the confirm is cancelled', async () => {
      const calls = routes()
      vi.stubGlobal('confirm', vi.fn(() => false))
      await show()
      fireEvent.click(await screen.findByRole('button', { name: 'Use the next reaction piece' }))
      expect(calls.some((c) => c.method === 'POST')).toBe(false)
    })

    it('saves the corrected clip speech and re-renders the captions', async () => {
      const calls = routes({ 'POST /api/assets/7/transcript': [200, { asset: child }] })
      await show()
      const speech = await screen.findByRole('region', { name: 'Clip speech' })
      fireEvent.change(screen.getByDisplayValue('insdie'), { target: { value: 'inside' } })
      fireEvent.click(screen.getByRole('button', { name: 'Save and re-render captions' }))
      await waitFor(() => expect(calls.find((c) => c.url === '/api/assets/7/transcript')?.body)
        .toEqual({ texts: ['across the start', 'inside'] }))
      expect(await screen.findByRole('link', { name: 'Newer version #9 (rendering)' })).toBeTruthy()
      expect(speech.textContent).toContain('0:12–0:14')
    })

    it('shows the server refusal of a transcript', async () => {
      routes({ 'POST /api/assets/7/transcript': [422, { error: 'invalid', message: 'line 2 is empty' }] })
      await show()
      await screen.findByRole('region', { name: 'Clip speech' })
      fireEvent.click(screen.getByRole('button', { name: 'Save and re-render captions' }))
      expect(await screen.findByText('Not done: line 2 is empty')).toBeTruthy()
    })

    it('approving a commentary video asks for the rights confirmation', async () => {
      HTMLDialogElement.prototype.showModal = function () { this.open = true }
      const slot = { publish_at: '2026-11-20T10:00:00Z', local: '2026-11-20T11:00:00+01:00' }
      const calls = routes({
        'POST /api/assets/7/approve': [200, { ...REMIX, status: 'approved' }],
        'GET /api/assets/7/proposed-slot': [200, { ...slot, needs_confirmation: true }],
        'POST /api/assets/7/schedule': [200, { asset: { ...REMIX, status: 'scheduled' } }],
      })
      await show()
      fireEvent.click(screen.getByRole('button', { name: 'Approve' }))
      const box = await screen.findByRole('checkbox', { name: /my own take is a substantial part/ })
      const accept = screen.getByRole('button', { name: 'Accept' })
      expect(accept).toHaveProperty('disabled', true)
      fireEvent.click(box)
      fireEvent.click(accept)
      await waitFor(() => expect(calls.find((c) => c.url === '/api/assets/7/schedule')?.body)
        .toEqual({ publish_at: slot.publish_at, confirmed: true }))
    })
  })
})
