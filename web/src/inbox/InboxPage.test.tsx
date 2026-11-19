import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Asset } from '../api/client'
import { ToastProvider } from '../ui/Toast'
import InboxPage from './InboxPage'

const asset = (id: number, fields: Partial<Asset> = {}): Asset => ({
  id, status: 'ready', verdict: 'none', self_score: 5, self_score_reason: 'ok',
  caption: `caption ${id}`, batch_date: '2026-11-17', preview_url: `/api/media/${id}.mp4`,
  thumbnail_url: null, track: 'motion', strategy: 'exploit', ...fields,
})

const ASSETS = [
  asset(1, { self_score: 9, self_score_reason: 'strong hook', strategy: 'explore',
    description: 'A knight jumps over three facts.' }),
  asset(2, { self_score: 7 }),
  asset(3, { status: 'scheduled' }), // decided earlier
  asset(4, { status: 'rendering' }), // nothing to decide yet
]
const SLOT = { publish_at: '2026-11-18T10:00:00Z', local: '2026-11-18T11:00:00+01:00' }

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
      'GET /api/assets/1/proposed-slot': [200, { ...SLOT, needs_confirmation: false }],
      'GET /api/assets/2/proposed-slot': [200, { ...SLOT, needs_confirmation: false }],
      ...routes,
    }
    const [status, body] = all[`${method} ${url.split('?')[0]}`] ?? [404, { error: 'not_found' }]
    return new Response(JSON.stringify(body), { status })
  }))
  return calls
}

const wrapper = ({ children }: { children: ReactNode }) => (
  <MemoryRouter><ToastProvider>{children}</ToastProvider></MemoryRouter>
)
const renderPage = () => render(<InboxPage />, { wrapper })
const card = (id: number) => screen.getByRole('article', { name: `Video ${id}` })
const cards = () => screen.queryAllByRole('article').map((a) => a.getAttribute('aria-label'))
const posts = (calls: Call[]) => calls.filter((c) => c.method === 'POST').map((c) => [c.url, c.body])
const press = (id: number, name: string) => fireEvent.click(within(card(id)).getByRole('button', { name }))
const declineSheet = () => screen.getByRole('dialog', { name: 'Why decline?' })
/** Decline (button or key `d`) opens the motive sheet; this fills its text and confirms. */
function declineWith(id: number | null, text = 'Trop lent') {
  if (id === null) fireEvent.keyDown(window, { key: 'd' })
  else press(id, 'Decline')
  const sheet = within(declineSheet())
  fireEvent.change(sheet.getByRole('textbox', { name: 'Pourquoi ?' }), { target: { value: text } })
  fireEvent.click(sheet.getByRole('button', { name: 'Decline' }))
}

/** Let the 5 s undo window close (fake timers), then wait on real ones. */
async function closeUndoWindow() {
  await act(() => vi.advanceTimersByTimeAsync(5000))
  vi.useRealTimers()
}

// IntersectionObserver stub: `show(el)` reports that element as on screen.
let observed: { cb: IntersectionObserverCallback; els: Element[] }[] = []
const show = (el: Element) =>
  act(() => observed.filter((o) => o.els.includes(el)).forEach((o) =>
    o.cb([{ target: el, isIntersecting: true, intersectionRatio: 1 } as unknown as IntersectionObserverEntry],
      {} as IntersectionObserver)))

beforeAll(() => {
  // jsdom has no modal dialogs and no media playback
  HTMLDialogElement.prototype.showModal = function () { this.open = true }
  HTMLDialogElement.prototype.close = function () {
    this.open = false
    this.dispatchEvent(new Event('close'))
  }
})

beforeEach(() => {
  observed = []
  vi.stubGlobal('IntersectionObserver', class {
    entry: { cb: IntersectionObserverCallback; els: Element[] }
    constructor(cb: IntersectionObserverCallback) {
      this.entry = { cb, els: [] }
      observed.push(this.entry)
    }
    observe(el: Element) { this.entry.els.push(el) }
    disconnect() { observed = observed.filter((o) => o !== this.entry) }
  })
  HTMLMediaElement.prototype.play = vi.fn(function (this: HTMLMediaElement) {
    Object.defineProperty(this, 'paused', { value: false, configurable: true })
    return Promise.resolve()
  })
  HTMLMediaElement.prototype.pause = vi.fn(function (this: HTMLMediaElement) {
    Object.defineProperty(this, 'paused', { value: true, configurable: true })
  })
})

afterEach(() => {
  vi.useRealTimers()
  cleanup()
  vi.unstubAllGlobals()
  sessionStorage.clear()
})

describe('InboxPage feed', () => {
  it('marks a reaction remix with a reaction badge', async () => {
    stubApi({ 'GET /api/assets': [200, [asset(1), asset(2, {
      track: 'remix', recipe: { inputs: { source: 's.mp4', reaction: 'reactions/1/pieces/3.mp4' } } })]] })
    renderPage()
    await screen.findByText('0 of 2 decided')
    expect(within(card(2)).getByText('reaction')).toBeTruthy()
    expect(within(card(1)).queryByText('reaction')).toBeNull()
  })

  it('shows only the videos to decide, with the counter and the overlay', async () => {
    const calls = stubApi()
    renderPage()
    expect(await screen.findByText('1 of 3 decided')).toBeTruthy()
    expect(cards()).toEqual(['Video 1', 'Video 2'])
    expect(calls.map((c) => c.url)).toContain(`/api/assets?batch_date=${new Date().toLocaleDateString('sv')}`)
    const video = card(1).querySelector('video')!
    expect(video.getAttribute('src')).toBe('/api/media/1.mp4')
    expect(video.muted && video.loop && video.playsInline).toBe(true)
    expect(video.getAttribute('preload')).toBe('auto')
    expect(card(2).querySelector('video')!.getAttribute('preload')).toBe('auto') // the next one
    const c1 = within(card(1))
    expect(c1.getByText('9/10')).toBeTruthy()
    expect(c1.getByText('strong hook')).toBeTruthy()
    expect(c1.getByText('Explore')).toBeTruthy()
    const desc = c1.getByRole('button', { name: 'A knight jumps over three facts.' })
    fireEvent.click(desc)
    expect(desc.getAttribute('aria-expanded')).toBe('true')
    expect(within(card(2)).queryByText('Explore')).toBeNull()
    expect(c1.getByRole('link', { name: 'Details' }).getAttribute('href')).toBe('/assets/1')
  })

  it('only the next video preloads', async () => {
    stubApi({ 'GET /api/assets': [200, [asset(1), asset(2), asset(3)]] })
    renderPage()
    await screen.findByText('0 of 3 decided')
    expect(card(3).querySelector('video')!.getAttribute('preload')).toBe('none')
  })

  it('plays only the card on screen', async () => {
    stubApi()
    renderPage()
    await screen.findByText('1 of 3 decided')
    const [v1, v2] = [card(1).querySelector('video')!, card(2).querySelector('video')!]
    await waitFor(() => expect(v1.paused).toBe(false))
    expect(v2.paused).not.toBe(false)
    await show(card(2))
    expect(v2.paused).toBe(false)
    expect(v1.paused).toBe(true)
  })

  it('a tap on the video toggles the sound for the feed', async () => {
    stubApi()
    renderPage()
    await screen.findByText('1 of 3 decided')
    fireEvent.click(card(1).querySelector('video')!)
    expect(card(1).querySelector('video')!.muted).toBe(false)
    expect(card(2).querySelector('video')!.muted).toBe(false)
    expect(within(card(1)).getByRole('button', { name: 'Mute' })).toBeTruthy()
  })

  describe('approve', () => {
    it('queues after the undo window', async () => {
      const calls = stubApi({
        'POST /api/assets/1/approve-and-queue': [200, { asset: asset(1, { status: 'scheduled' }), slot: SLOT }],
      })
      renderPage()
      await screen.findByText('1 of 3 decided')
      vi.useFakeTimers()
      press(1, 'Approve')
      await act(() => vi.advanceTimersByTimeAsync(0)) // the proposed-slot check
      expect(cards()).toEqual(['Video 2'])
      expect(screen.getByText('2 of 3 decided')).toBeTruthy()
      expect(screen.getByText('Approved')).toBeTruthy()
      expect(posts(calls)).toEqual([])
      await closeUndoWindow()
      await waitFor(() => expect(posts(calls)).toEqual([
        ['/api/assets/1/approve-and-queue', { confirmed: false }]]))
    })

    it('without a free slot it says so', async () => {
      stubApi({
        'POST /api/assets/1/approve-and-queue': [200, { asset: asset(1, { status: 'approved' }), slot: null }],
      })
      renderPage()
      await screen.findByText('1 of 3 decided')
      vi.useFakeTimers()
      press(1, 'Approve')
      await act(() => vi.advanceTimersByTimeAsync(0))
      await closeUndoWindow()
      expect(await screen.findByText('Approved, no free slot: set one in Calendar')).toBeTruthy()
      expect(cards()).toEqual(['Video 2'])
    })

    it('a commentary video asks for the rights confirmation first', async () => {
      const calls = stubApi({
        'GET /api/assets/1/proposed-slot': [200, { ...SLOT, needs_confirmation: true }],
        'POST /api/assets/1/approve-and-queue': [200, { asset: asset(1, { status: 'scheduled' }), slot: SLOT }],
      })
      renderPage()
      await screen.findByText('1 of 3 decided')
      press(1, 'Approve')
      const sheet = await screen.findByRole('dialog', { name: 'Approve this reaction video?' })
      expect(cards()).toEqual(['Video 1', 'Video 2']) // nothing decided yet
      const ok = within(sheet).getByRole('button', { name: 'Approve' }) as HTMLButtonElement
      expect(ok.disabled).toBe(true)
      fireEvent.click(within(sheet).getByRole('checkbox'))
      vi.useFakeTimers()
      fireEvent.click(ok)
      expect(screen.queryByRole('dialog')).toBeNull()
      expect(cards()).toEqual(['Video 2'])
      await closeUndoWindow()
      await waitFor(() => expect(posts(calls)).toEqual([
        ['/api/assets/1/approve-and-queue', { confirmed: true }]]))
    })

    it('an explore video can be approved as a trial Reel during the undo window', async () => {
      const calls = stubApi({
        'POST /api/assets/1/approve-and-queue': [200, { asset: asset(1, { status: 'scheduled' }), slot: SLOT }],
      })
      renderPage()
      await screen.findByText('1 of 3 decided')
      vi.useFakeTimers()
      press(1, 'Approve')
      await act(() => vi.advanceTimersByTimeAsync(0))
      const group = screen.getByRole('group', { name: 'Publish as a trial Reel? (optional)' })
      const toggle = within(group).getByRole('button', { name: 'Approve as trial Reel' })
      expect(toggle.getAttribute('aria-pressed')).toBe('false')
      fireEvent.click(toggle)
      expect(toggle.getAttribute('aria-pressed')).toBe('true')
      await closeUndoWindow()
      await waitFor(() => expect(posts(calls)).toEqual([
        ['/api/assets/1/approve-and-queue', { confirmed: false, trial: 'SS_PERFORMANCE' }]]))
      expect(screen.queryByRole('group', { name: 'Publish as a trial Reel? (optional)' })).toBeNull()
    })

    it('an experiment video (exploit) can be approved as a trial Reel too', async () => {
      stubApi({
        'GET /api/assets': [200, ASSETS.map((a) => (a.id === 2 ? { ...a, experiment: 'exp:4:question' } : a))],
        'POST /api/assets/2/approve-and-queue': [200, { asset: asset(2, { status: 'scheduled' }), slot: SLOT }],
      })
      renderPage()
      await screen.findByText('1 of 3 decided')
      vi.useFakeTimers()
      press(2, 'Approve')
      await act(() => vi.advanceTimersByTimeAsync(0))
      const group = screen.getByRole('group', { name: 'Publish as a trial Reel? (optional)' })
      expect(within(group).getByRole('button', { name: 'Approve as trial Reel' })).toBeTruthy()
    })

    it('a normal (exploit) video offers no trial Reel', async () => {
      stubApi({ 'POST /api/assets/2/approve-and-queue': [200, { asset: asset(2, { status: 'scheduled' }), slot: SLOT }] })
      renderPage()
      await screen.findByText('1 of 3 decided')
      vi.useFakeTimers()
      press(2, 'Approve')
      await act(() => vi.advanceTimersByTimeAsync(0))
      expect(screen.getByText('Approved')).toBeTruthy()
      expect(screen.queryByRole('group', { name: 'Publish as a trial Reel? (optional)' })).toBeNull()
    })

    it('undo brings the card back and sends nothing', async () => {
      const calls = stubApi()
      renderPage()
      await screen.findByText('1 of 3 decided')
      vi.useFakeTimers()
      press(1, 'Approve')
      await act(() => vi.advanceTimersByTimeAsync(0))
      fireEvent.click(screen.getByRole('button', { name: 'Undo' }))
      expect(cards()).toEqual(['Video 1', 'Video 2'])
      await closeUndoWindow()
      expect(posts(calls)).toEqual([])
    })

    it('a refusal puts the card back with the reason', async () => {
      stubApi({ 'POST /api/assets/1/approve-and-queue': [409, { error: 'qc', message: 'has not passed QC' }] })
      renderPage()
      await screen.findByText('1 of 3 decided')
      vi.useFakeTimers()
      press(1, 'Approve')
      await act(() => vi.advanceTimersByTimeAsync(0))
      await closeUndoWindow()
      expect((await screen.findByRole('alert')).textContent).toContain('has not passed QC')
      expect(cards()).toEqual(['Video 1', 'Video 2'])
    })
  })

  describe('decline', () => {
    const declineApi = () => stubApi({
      'POST /api/assets/1/decline': [200, asset(1, { status: 'archived', verdict: 'disliked' })],
    })

    it('opens the motive sheet; Confirm waits for a reason or words; commits after 5 s', async () => {
      const calls = declineApi()
      renderPage()
      await screen.findByText('1 of 3 decided')
      press(1, 'Decline')
      const sheet = within(declineSheet())
      expect(cards()).toEqual(['Video 1', 'Video 2']) // nothing decided before Confirm
      const confirm = sheet.getByRole('button', { name: 'Decline' }) as HTMLButtonElement
      expect(confirm.disabled).toBe(true)
      fireEvent.change(sheet.getByRole('textbox', { name: 'Pourquoi ?' }), { target: { value: '   ' } })
      expect(confirm.disabled).toBe(true) // blanks are no motive
      fireEvent.click(await sheet.findByRole('button', { name: 'Too long' }))
      expect(confirm.disabled).toBe(false)
      fireEvent.change(sheet.getByRole('textbox', { name: 'Pourquoi ?' }), { target: { value: ' On décroche ' } })
      vi.useFakeTimers()
      fireEvent.click(confirm)
      expect(screen.queryByRole('dialog')).toBeNull()
      expect(cards()).toEqual(['Video 2'])
      expect(screen.getByText('Declined')).toBeTruthy()
      await act(() => vi.advanceTimersByTimeAsync(4900))
      expect(posts(calls)).toEqual([])
      await closeUndoWindow()
      await waitFor(() => expect(posts(calls)).toEqual([
        ['/api/assets/1/decline', { reason_codes: ['too_long'], text: 'On décroche' }],
      ]))
    })

    it('words alone are a motive; sent with keepalive (it may be flushed on tab close)', async () => {
      const calls = declineApi()
      renderPage()
      await screen.findByText('1 of 3 decided')
      vi.useFakeTimers()
      declineWith(1, 'Trop lent')
      await closeUndoWindow()
      await waitFor(() => expect(posts(calls)).toEqual([
        ['/api/assets/1/decline', { reason_codes: [], text: 'Trop lent' }]]))
      const init = vi.mocked(fetch).mock.calls.find(([u]) => String(u).endsWith('/decline'))![1]
      expect(init?.keepalive).toBe(true)
    })

    it('the key d opens it too; Cancel decides nothing', async () => {
      const calls = declineApi()
      renderPage()
      await screen.findByText('1 of 3 decided')
      fireEvent.keyDown(window, { key: 'd' })
      fireEvent.click(within(declineSheet()).getByRole('button', { name: 'Cancel' }))
      expect(screen.queryByRole('dialog')).toBeNull()
      expect(cards()).toEqual(['Video 1', 'Video 2'])
      vi.useFakeTimers()
      await closeUndoWindow()
      expect(posts(calls)).toEqual([])
    })

    it('undo cancels it', async () => {
      const calls = declineApi()
      renderPage()
      await screen.findByText('1 of 3 decided')
      vi.useFakeTimers()
      declineWith(1)
      fireEvent.click(screen.getByRole('button', { name: 'Undo' }))
      expect(cards()).toEqual(['Video 1', 'Video 2'])
      await closeUndoWindow()
      expect(posts(calls)).toEqual([])
    })

    it('commits at once when the page is hidden', async () => {
      const calls = declineApi()
      renderPage()
      await screen.findByText('1 of 3 decided')
      declineWith(1)
      Object.defineProperty(document, 'visibilityState', { value: 'hidden', configurable: true })
      try {
        fireEvent(document, new Event('visibilitychange'))
      } finally {
        Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true })
      }
      await waitFor(() => expect(posts(calls).map(([u]) => u)).toEqual(
        ['/api/assets/1/decline']))
    })

    it('commits at once when the Inbox is left', async () => {
      const calls = declineApi()
      const { unmount } = renderPage()
      await screen.findByText('1 of 3 decided')
      declineWith(1)
      unmount()
      await waitFor(() => expect(posts(calls).map(([u]) => u)).toEqual(
        ['/api/assets/1/decline']))
    })
  })

  it('a revised video shows what the owner asked: Changé : « … »', async () => {
    stubApi({ 'GET /api/assets': [200, [
      asset(1, { change_request: { text: 'Plus court', reason_codes: [] } }),
      asset(2, { change_request: { text: null, reason_codes: ['weak_hook'] } }), asset(3)]] })
    renderPage()
    await screen.findByText('0 of 3 decided')
    expect(within(card(1)).getByText('Changé : « Plus court »')).toBeTruthy()
    expect(await within(card(2)).findByText('Changé : « Weak hook »')).toBeTruthy()
    expect(within(card(3)).queryByText(/Changé/)).toBeNull()
  })

  it('shows the DM pick sender and the commentary chip a row carries', async () => {
    stubApi({ 'GET /api/assets': [200, [asset(1, { dm_pick_sender: 'pal', rights_basis: 'commentary' }), asset(2)]] })
    renderPage()
    await screen.findByText('0 of 2 decided')
    expect(within(card(1)).getByText('DM pick from @pal')).toBeTruthy()
    expect(within(card(1)).getByText('commentary')).toBeTruthy()
    expect(within(card(2)).queryByText(/DM pick/)).toBeNull()
  })

  it('badges a video made from a work order with its instruction', async () => {
    const order = { id: 4, mode: 'inspired' as const, instruction: 'version sans sucre', permalink: null }
    stubApi({ 'GET /api/assets': [200, [
      asset(1, { work_order: order }), asset(2, { work_order: { ...order, instruction: null, mode: 'owner' } }), // real rows: no source, DM orders are owner
      asset(3, { work_order: { ...order, mode: 'owner', source: 'trend' } }), asset(4)]] })
    renderPage()
    await screen.findByText('0 of 4 decided')
    expect(within(card(1)).getByText('Tendance')).toBeTruthy()
    expect(within(card(1)).getByText('Ta consigne : « version sans sucre »')).toBeTruthy()
    expect(within(card(2)).getByText('Mes envois')).toBeTruthy()
    expect(within(card(2)).queryByText(/Ta consigne/)).toBeNull()
    expect(within(card(3)).getByText('Tendance')).toBeTruthy() // an explicit source wins
    expect(within(card(4)).queryByText(/Tendance|Mes envois/)).toBeNull()
  })

  describe('save for later', () => {
    it('sends the video to the bench after the undo window; a saved one is not in Today', async () => {
      const calls = stubApi({
        'GET /api/assets': [200, [...ASSETS, asset(5, { verdict: 'liked' })]],
        'POST /api/assets/1/verdict': [200, asset(1, { verdict: 'liked' })],
      })
      renderPage()
      await screen.findByText('2 of 4 decided')
      expect(cards()).toEqual(['Video 1', 'Video 2'])
      vi.useFakeTimers()
      press(1, 'Save for later')
      expect(cards()).toEqual(['Video 2'])
      expect(screen.getByText('Saved for later')).toBeTruthy()
      await closeUndoWindow()
      await waitFor(() => expect(posts(calls)).toEqual([['/api/assets/1/verdict', { verdict: 'liked' }]]))
    })

    it('opening the Saved tab right after loads the bench once the save landed', async () => {
      const calls = stubApi()
      const stubbed = fetch
      let release = () => {}
      const held = new Promise<void>((r) => { release = r })
      vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
        if (init?.method === 'POST') {
          await held // the save is still on its way
          return new Response(JSON.stringify(asset(1, { verdict: 'liked' })), { status: 200 })
        }
        return stubbed(url, init)
      }))
      renderPage()
      await screen.findByText('1 of 3 decided')
      press(1, 'Save for later')
      const benchGets = () => calls.filter((c) => c.url === '/api/bench').length
      const before = benchGets()
      fireEvent.click(screen.getByRole('tab', { name: /Saved/ }))
      await act(() => new Promise((r) => setTimeout(r, 20)))
      expect(benchGets()).toBe(before)
      release()
      await waitFor(() => expect(benchGets()).toBeGreaterThan(before))
    })

    it('key s saves; undo sends nothing', async () => {
      const calls = stubApi()
      renderPage()
      await screen.findByText('1 of 3 decided')
      vi.useFakeTimers()
      fireEvent.keyDown(window, { key: 's' })
      expect(cards()).toEqual(['Video 2'])
      fireEvent.click(screen.getByRole('button', { name: 'Undo' }))
      expect(cards()).toEqual(['Video 1', 'Video 2'])
      await closeUndoWindow()
      expect(posts(calls)).toEqual([])
    })
  })

  describe('change', () => {
    const changeApi = () => stubApi({
      'POST /api/assets/1/feedback': [201, { feedback: {}, asset: asset(1, { status: 'revision_requested' }),
        moved: true, reason: null }],
    })

    it('sends wants_changes with the reasons, the text and the pinned moment', async () => {
      const calls = changeApi()
      renderPage()
      await screen.findByText('1 of 3 decided')
      Object.defineProperty(card(1).querySelector('video')!, 'currentTime', { value: 7.4 })
      press(1, 'Change')
      const sheet = await screen.findByRole('dialog', { name: 'What should change?' })
      const send = within(sheet).getByRole('button', { name: 'Send for changes' }) as HTMLButtonElement
      expect(send.disabled).toBe(true)
      fireEvent.click(await within(sheet).findByRole('button', { name: 'Weak hook' }))
      fireEvent.click(within(sheet).getByRole('button', { name: 'at 0:07' }))
      fireEvent.change(within(sheet).getByLabelText('What to change'), { target: { value: ' shorter hook ' } })
      vi.useFakeTimers()
      fireEvent.click(send)
      expect(screen.queryByRole('dialog')).toBeNull()
      expect(cards()).toEqual(['Video 2'])
      expect(screen.getByText('Sent for changes')).toBeTruthy()
      expect(posts(calls)).toEqual([])
      await closeUndoWindow()
      await waitFor(() => expect(posts(calls)).toEqual([['/api/assets/1/feedback', {
        reason_codes: ['weak_hook'], text: 'shorter hook', video_time_s: 7.4, wants_changes: true }]]))
    })

    it('undo cancels it', async () => {
      const calls = changeApi()
      renderPage()
      await screen.findByText('1 of 3 decided')
      press(1, 'Change')
      const sheet = await screen.findByRole('dialog')
      fireEvent.click(await within(sheet).findByRole('button', { name: 'Too long' }))
      vi.useFakeTimers()
      fireEvent.click(within(sheet).getByRole('button', { name: 'Send for changes' }))
      fireEvent.click(screen.getByRole('button', { name: 'Undo' }))
      expect(cards()).toEqual(['Video 1', 'Video 2'])
      await closeUndoWindow()
      expect(posts(calls)).toEqual([])
    })
  })

  it('keys: d declines, j / k move, c opens the change sheet, m mutes; ignored while typing', async () => {
    const calls = stubApi({ 'GET /api/assets': [200, [asset(1), asset(2), asset(3)]] })
    renderPage()
    await screen.findByText('0 of 3 decided')
    fireEvent.keyDown(screen.getByLabelText('Batch date'), { key: 'd' })
    expect(cards()).toEqual(['Video 1', 'Video 2', 'Video 3'])
    fireEvent.keyDown(window, { key: 'j' })
    fireEvent.keyDown(window, { key: 'ArrowDown' })
    fireEvent.keyDown(window, { key: 'k' })
    declineWith(null) // on video 2: d opens the motive sheet
    expect(cards()).toEqual(['Video 1', 'Video 3'])
    fireEvent.keyDown(window, { key: 'm' })
    expect(card(3).querySelector('video')!.muted).toBe(false)
    fireEvent.keyDown(window, { key: 'c' }) // video 3 took video 2's place
    expect(await screen.findByRole('dialog', { name: 'What should change?' })).toBeTruthy()
    fireEvent.keyDown(window, { key: 'd' }) // a sheet is open: no decision
    expect(cards()).toEqual(['Video 1', 'Video 3'])
    expect(posts(calls)).toEqual([])
  })

  it('keys: a approves, space pauses and plays', async () => {
    stubApi()
    renderPage()
    await screen.findByText('1 of 3 decided')
    const v = card(1).querySelector('video')!
    await waitFor(() => expect(v.paused).toBe(false))
    fireEvent.keyDown(window, { key: ' ' })
    expect(v.paused).toBe(true)
    fireEvent.keyDown(window, { key: ' ' })
    expect(v.paused).toBe(false)
    fireEvent.keyDown(window, { key: 'a' })
    await waitFor(() => expect(cards()).toEqual(['Video 2']))
  })

  it('all done: the last decision shows the end screen with the Calendar link', async () => {
    stubApi({ 'GET /api/assets': [200, [asset(1), asset(3, { status: 'scheduled' })]] })
    renderPage()
    await screen.findByText('1 of 2 decided')
    declineWith(1)
    expect(screen.getByText('2 of 2 decided')).toBeTruthy()
    expect(screen.getByText('All done')).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Open the Calendar' }).getAttribute('href')).toBe('/calendar')
  })

  it('an empty day says so', async () => {
    stubApi({ 'GET /api/assets': [200, []] })
    renderPage()
    expect(await screen.findByText('No videos for this day.')).toBeTruthy()
  })

  describe('bench', () => {
    const BENCH = {
      assets: [asset(7, { verdict: 'liked', best_before: '2026-11-20', batch_date: '2026-11-10' }),
        asset(8, { verdict: 'liked', best_before: null, batch_date: '2026-11-12' }),
        asset(9, { verdict: 'liked', batch_date: '2026-11-13' }),
        asset(10, { verdict: 'liked', batch_date: '2026-11-14' })],
      supply_days: 2,
      max_posts_per_day: 3,
      suggestion: { asset_id: 7, ...SLOT },
    }
    const benchApi = (routes: Record<string, [number, unknown]> = {}) =>
      stubApi({ 'GET /api/bench': [200, BENCH], ...routes })

    it('the Saved tab (bench) is a feed of liked videos with the supply line and best-before', async () => {
      benchApi()
      renderPage()
      fireEvent.click(await screen.findByRole('tab', { name: 'Saved (4)' }))
      expect(await screen.findByText('4 saved videos = 2 days at 3 a day')).toBeTruthy()
      expect(cards()).toEqual(['Video 7', 'Video 8', 'Video 9', 'Video 10'])
      expect(within(card(7)).getByText('best before 2026-11-20')).toBeTruthy()
      expect(within(card(8)).queryByText(/best before/)).toBeNull()
      expect(within(card(7)).queryByRole('button', { name: 'Save for later' })).toBeNull()
      expect(screen.queryByLabelText('Batch date')).toBeNull()
      fireEvent.click(screen.getByRole('tab', { name: 'Today' }))
      expect(await screen.findByText('1 of 3 decided')).toBeTruthy()
    })

    it('one saved video reads in the singular', async () => {
      stubApi({ 'GET /api/bench': [200, { ...BENCH, assets: [BENCH.assets[0]], supply_days: 1 }] })
      renderPage()
      fireEvent.click(await screen.findByRole('tab', { name: 'Saved (1)' }))
      expect(await screen.findByText('1 saved video = 1 day at 3 a day')).toBeTruthy()
    })

    it('switching tabs commits a waiting decision first', async () => {
      const calls = benchApi({
        'POST /api/assets/1/decline': [200, asset(1, { status: 'archived', verdict: 'disliked' })],
      })
      renderPage()
      await screen.findByText('1 of 3 decided')
      declineWith(1)
      fireEvent.click(screen.getByRole('tab', { name: 'Saved (4)' }))
      await waitFor(() => expect(posts(calls).map(([u]) => u)).toEqual(
        ['/api/assets/1/decline']))
    })

    it('the banner suggests the freshest video; Review it opens the bench', async () => {
      const calls = benchApi()
      renderPage()
      const banner = await screen.findByRole('region', { name: 'Saved video suggestion' })
      expect(banner.textContent).toMatch(/Free slot (today|tomorrow|2026-11-18) 11:00/)
      fireEvent.click(within(banner).getByRole('button', { name: 'Review it' }))
      expect(await screen.findByRole('article', { name: 'Video 7' })).toBeTruthy()
      expect(screen.getByRole('tab', { name: 'Saved (4)' }).getAttribute('aria-selected')).toBe('true')
      expect(posts(calls)).toEqual([]) // nothing approved by itself
    })

    it('the banner can be dismissed for the session', async () => {
      benchApi()
      const { unmount } = renderPage()
      const banner = await screen.findByRole('region', { name: 'Saved video suggestion' })
      fireEvent.click(within(banner).getByRole('button', { name: 'Dismiss' }))
      expect(screen.queryByRole('region', { name: 'Saved video suggestion' })).toBeNull()
      unmount()
      renderPage()
      await screen.findByRole('tab', { name: 'Saved (4)' })
      expect(screen.queryByRole('region', { name: 'Saved video suggestion' })).toBeNull()
    })

    it('no banner without a suggestion', async () => {
      stubApi({ 'GET /api/bench': [200, { ...BENCH, suggestion: null }] })
      renderPage()
      await screen.findByRole('tab', { name: 'Saved (4)' })
      expect(screen.queryByRole('region', { name: 'Saved video suggestion' })).toBeNull()
    })
  })
})
