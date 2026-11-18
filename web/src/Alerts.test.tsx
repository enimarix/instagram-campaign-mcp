import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import Alerts from './Alerts'
import type { Alert } from './api/client'

const FAILED: Alert = {
  id: 'publish_failed:3', kind: 'publish_failed', severity: 'error', title: 'A post failed to publish',
  detail: 'Rate limited', link: '/assets/9', since: '2026-11-18T08:00:00+00:00',
}
const WORKER: Alert = {
  id: 'worker', kind: 'worker', severity: 'warn', title: 'The publishing worker is not running',
  detail: 'Start it with ig-campaign up.', link: '/settings', since: '2026-11-18T07:00:00+00:00',
}

function stubApi(list: Alert[]) {
  const calls: string[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    calls.push(`${init?.method ?? 'GET'} ${url}`)
    return new Response(JSON.stringify(url === '/api/alerts' ? list : { id: 'x' }), { status: 200 })
  }))
  return calls
}

function setVisibility(state: 'visible' | 'hidden') {
  Object.defineProperty(document, 'visibilityState', { value: state, configurable: true })
  fireEvent(document, new Event('visibilitychange'))
}

const show = () => render(<MemoryRouter><Alerts /></MemoryRouter>)
const polls = (calls: string[]) => calls.filter((c) => c === 'GET /api/alerts').length

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
  vi.useRealTimers()
  Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true })
})

describe('Alerts', () => {
  it('shows the count on the bell and lists the alerts in a sheet', async () => {
    stubApi([FAILED, WORKER])
    show()
    const bell = await screen.findByRole('button', { name: 'Alerts: 2 need attention' })
    expect(bell.textContent).toBe('2')
    fireEvent.click(bell)
    const sheet = screen.getByRole('dialog', { name: 'Alerts' })
    const items = within(sheet).getAllByRole('listitem')
    expect(items.map((li) => within(li).getByText(/^(A post|The publishing)/).textContent))
      .toEqual([FAILED.title, WORKER.title])
    expect(within(items[0]).getByText('Problem')).toBeTruthy()
    expect(within(items[0]).getByText('Rate limited')).toBeTruthy()
    expect(within(items[0]).getByRole('link', { name: `Open: ${FAILED.title}` }).getAttribute('href')).toBe('/assets/9')
  })

  it('dismisses an alert', async () => {
    const calls = stubApi([FAILED])
    show()
    fireEvent.click(await screen.findByRole('button', { name: 'Alerts: 1 needs attention' }))
    fireEvent.click(screen.getByRole('button', { name: `Dismiss: ${FAILED.title}` }))
    expect(calls).toContain('POST /api/alerts/publish_failed%3A3/dismiss')
    expect(screen.getByText('All good')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Alerts' }).textContent).toBe('')
  })

  it('says all good when nothing needs attention', async () => {
    stubApi([])
    show()
    fireEvent.click(await screen.findByRole('button', { name: 'Alerts' }))
    expect(within(screen.getByRole('dialog')).getByText('All good')).toBeTruthy()
  })

  it('polls every minute only while the page is visible', async () => {
    vi.useFakeTimers()
    const calls = stubApi([])
    show()
    await act(() => vi.advanceTimersByTimeAsync(0))
    expect(polls(calls)).toBe(1)
    await act(() => vi.advanceTimersByTimeAsync(60_000))
    expect(polls(calls)).toBe(2)
    act(() => setVisibility('hidden'))
    await act(() => vi.advanceTimersByTimeAsync(180_000))
    expect(polls(calls)).toBe(2)
    act(() => setVisibility('visible')) // back: refresh at once, then every minute
    await act(() => vi.advanceTimersByTimeAsync(0))
    expect(polls(calls)).toBe(3)
    await act(() => vi.advanceTimersByTimeAsync(60_000))
    expect(polls(calls)).toBe(4)
  })
})
