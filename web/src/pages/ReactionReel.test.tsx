import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ReactionReel } from '../api/client'
import ReactionReelSection from './ReactionReel'

const reel = (over: Partial<ReactionReel>): ReactionReel => ({
  id: 1, path: 'reactions/1/reel.mp4', duration_s: 2700, cursor_s: 760, pieces_used: 63,
  used_pct: 28.1, active: true, created_at: '2026-11-17T10:00:00+00:00', ...over,
})

function stubApi(lists: ReactionReel[][]) {
  const calls: string[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method ?? 'GET'} ${url}`
    calls.push(key)
    const body = key === 'GET /api/reactions' ? (lists.length > 1 ? lists.shift() : lists[0]) : reel({})
    return new Response(JSON.stringify(body), { status: 200 })
  }))
  return calls
}

class FakeXHR {
  static last: FakeXHR
  upload: { onprogress: ((e: { lengthComputable: boolean; loaded: number; total: number }) => void) | null } = { onprogress: null }
  status = 0
  responseText = ''
  onload: (() => void) | null = null
  onerror: (() => void) | null = null
  url = ''
  body: unknown
  open(_method: string, url: string) { this.url = url }
  setRequestHeader() {}
  send(body: unknown) {
    this.body = body
    FakeXHR.last = this
  }
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('ReactionReelSection', () => {
  it('shows the active reel, resets it and activates another', async () => {
    const calls = stubApi([[reel({}), reel({ id: 2, active: false, duration_s: 1800, used_pct: 0 })]])
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    render(<ReactionReelSection />)
    expect(await screen.findByText('12:40 of 45:00 used, 63 pieces')).toBeTruthy()
    expect(screen.getByRole('progressbar', { name: 'Reel used' }).getAttribute('aria-valuenow')).toBe('28.1')

    fireEvent.click(screen.getByRole('button', { name: 'Reset' }))
    const others = screen.getByRole('list', { name: 'Other reels' })
    expect(within(others).getByText('Reel 2 · 30:00 · 0% used')).toBeTruthy()
    fireEvent.click(within(others).getByRole('button', { name: 'Activate' }))
    await vi.waitFor(() => expect(calls).toContain('POST /api/reactions/2/activate'))
    expect(calls).toContain('POST /api/reactions/1/reset')
  })

  it('with only inactive reels, it says to activate one', async () => {
    stubApi([[reel({ active: false })]])
    render(<ReactionReelSection />)
    expect(await screen.findByText('No reel in use: activate one below or upload a new one.')).toBeTruthy()
  })

  it('uploads the file as the body with progress, then reloads', async () => {
    const calls = stubApi([[], [reel({ cursor_s: 0, pieces_used: 0, used_pct: 0 })]])
    vi.stubGlobal('XMLHttpRequest', FakeXHR)
    render(<ReactionReelSection />)
    expect(await screen.findByText('No reel yet: upload one.')).toBeTruthy()

    const file = new File(['x'], 'My reel.mov', { type: 'video/quicktime' })
    fireEvent.change(screen.getByLabelText('Upload a reel'), { target: { files: [file] } })
    const xhr = FakeXHR.last
    expect(xhr.url).toBe('/api/reactions/upload?name=My%20reel.mov')
    expect(xhr.body).toBe(file)
    xhr.upload.onprogress?.({ lengthComputable: true, loaded: 1, total: 2 })
    expect(await screen.findByText('Uploading… 50%')).toBeTruthy()

    xhr.status = 200
    xhr.responseText = JSON.stringify(reel({}))
    xhr.onload?.()
    expect(await screen.findByText('0:00 of 45:00 used, 0 pieces')).toBeTruthy()
    expect(calls.filter((c) => c === 'GET /api/reactions')).toHaveLength(2)
    expect(screen.getByText('Upload a reel')).toBeTruthy()
  })

  it('shows the server message when an upload is refused', async () => {
    stubApi([[]])
    vi.stubGlobal('XMLHttpRequest', FakeXHR)
    render(<ReactionReelSection />)
    await screen.findByText('No reel yet: upload one.')
    fireEvent.change(screen.getByLabelText('Upload a reel'), { target: { files: [new File(['x'], 'a.mp4')] } })
    const xhr = FakeXHR.last
    xhr.status = 413
    xhr.responseText = JSON.stringify({ error: 'too_large', message: 'the file is larger than 16000 MB' })
    xhr.onload?.()
    expect((await screen.findByRole('alert')).textContent).toBe('the file is larger than 16000 MB')
  })
})
