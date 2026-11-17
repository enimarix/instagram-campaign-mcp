import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Asset, AssetContext } from '../api/client'
import AssetPage from './AssetPage'

const ASSET: Asset = {
  id: 7, status: 'ready', verdict: 'none', self_score: 8, self_score_reason: 'ok',
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
      'Quality checkFailed: too quiet'])
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
})
