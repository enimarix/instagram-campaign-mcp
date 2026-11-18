import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AdEvaluation, AdPreset, AdsAudit, AdsBudget, AdTest, AdTestResults } from '../api/client'
import Ads from './Ads'

const scope = (cap: string, used = '0') => ({ cap, used, remaining: String(Number(cap) - Number(used)) })
const BUDGET: AdsBudget = {
  killed: false, killed_at: null, killed_reason: null, currency: 'EUR', day: '2026-11-18',
  daily: scope('20', '5'), lifetime: scope('200', '5'), test_cap: '100', tests: [{ test_id: 4, ...scope('100', '5') }],
  near_cap: { daily: false, lifetime: false, tests: [] },
}
const TEST: AdTest = {
  id: 4, hypothesis: 'Boss fight wins', variable: 'creative',
  variants: [{ media_id: '1', preset: 'fr_reels' }, { media_id: '2', preset: 'fr_reels' }],
  min_lift: 0.2, spec: { min_days: 7, max_days: 30, min_sample: 5000, primary_metric: 'ctr' }, needed: { total: 84, per_variant: 42, sample_per_variant: 4000 },
  budget_total: null, currency: 'EUR', end_date: null, status: 'proposed', reason: null, underpowered: null,
  created_at: '2026-11-18T08:00:00+00:00', result: null,
}
const WINNERS = [
  { media_id: '1', permalink: null, posted_at: '2026-11-01T10:00:00+00:00', caption: 'Boss fight', asset_id: 1,
    thumbnail_url: '/api/media/1/thumb.jpg' },
  { media_id: '2', permalink: null, posted_at: '2026-11-02T10:00:00+00:00', caption: 'Quiz chest', asset_id: 2, thumbnail_url: null },
]
const PRESETS: AdPreset[] = [
  { id: 'fr_reels', label: 'France, Reels', varies: ['audience', 'placement'] },
  { id: 'fr_feed_reels', label: 'France, Feed and Reels', varies: ['placement'] },
  { id: 'francophone_reels', label: 'France, Belgium, Switzerland, Luxembourg, Reels', varies: ['audience'] },
]
const AUDIT: AdsAudit = {
  total: 25, limit: 20, offset: 0,
  rows: [{ id: 9, at: '2026-11-18T09:00:00+00:00', actor: 'owner', action: 'kill', test_id: null, detail: { reason: 'too much' } }],
}

type Call = { key: string; body?: unknown }
/** `answers`: per "METHOD url" a body, or [status, body] for an error. */
function stubApi(answers: Record<string, unknown> = {}) {
  const calls: Call[] = []
  const base: Record<string, unknown> = {
    'GET /api/ads/budget': BUDGET, 'GET /api/ads/tests': { tests: [TEST] }, 'GET /api/ads/winners': { winners: WINNERS },
    'GET /api/ads/presets': { presets: PRESETS },
    'POST /api/ads/kill': { ...BUDGET, killed: true }, 'POST /api/ads/unkill': BUDGET,
  }
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method ?? 'GET'} ${url}`
    calls.push({ key, body: init?.body ? JSON.parse(String(init.body)) : undefined })
    const a = answers[key] ?? (key.startsWith('GET /api/ads/audit') ? AUDIT : base[key] ?? TEST)
    const [status, body] = Array.isArray(a) ? a : [200, a]
    return new Response(JSON.stringify(body), { status })
  }))
  return calls
}
const posts = (calls: Call[]) => calls.filter((c) => c.key.startsWith('POST'))

beforeEach(() => {
  HTMLDialogElement.prototype.showModal = function () { this.open = true }
  HTMLDialogElement.prototype.close = function () { this.open = false; this.dispatchEvent(new Event('close')) }
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('Ads page', () => {
  it('shows the budget and stops all ads with one tap', async () => {
    const calls = stubApi()
    render(<Ads />)
    const card = await screen.findByRole('region', { name: 'Budget' })
    expect(within(card).getByText('€15.00 left')).toBeTruthy()
    expect(within(card).getByText('€5.00 used of €20.00')).toBeTruthy()
    expect(within(card).getByText('€100.00 at most')).toBeTruthy()
    expect(within(card).getByText(/Test #4: €5.00 used/)).toBeTruthy()
    expect(screen.queryByText(/ADS_DAILY_CAP/)).toBeNull()
    fireEvent.click(within(card).getByRole('button', { name: 'Stop all ads' }))
    await vi.waitFor(() => expect(posts(calls)).toEqual([{ key: 'POST /api/ads/kill', body: undefined }]))
  })

  it('says how to allow spend when a cap is 0', async () => {
    stubApi({ 'GET /api/ads/budget': { ...BUDGET, daily: scope('0') } })
    render(<Ads />)
    expect(await screen.findByText('Set ADS_DAILY_CAP / ADS_TEST_CAP / ADS_LIFETIME_CAP in .env to allow spend.')).toBeTruthy()
  })

  it('asks the password to allow ads again and maps the password errors', async () => {
    const killed = { ...BUDGET, killed: true, killed_reason: 'too much', killed_at: '2026-11-18T09:00:00+00:00' }
    const calls = stubApi({ 'GET /api/ads/budget': killed, 'POST /api/ads/unkill': [403, { error: 'password_not_set' }] })
    render(<Ads />)
    expect(await screen.findByText(/All ads are stopped: too much/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Allow ads again' }))
    const sheet = screen.getByRole('dialog', { name: 'Allow ads again' })
    fireEvent.change(within(sheet).getByLabelText('Password'), { target: { value: 'pw' } })
    fireEvent.click(within(sheet).getByRole('button', { name: 'Allow ads again' }))
    expect((await within(sheet).findByRole('alert')).textContent).toMatch(/^Set UI_PASSWORD/)
    expect(posts(calls)).toEqual([{ key: 'POST /api/ads/unkill', body: { password: 'pw' } }])
  })

  it.each([
    [[403, { error: 'bad_password' }], 'Wrong password.'],
    [[429, { error: 'locked', retry_after: 300 }], 'Too many wrong passwords: try again in 5 min.'],
  ])('shows %j as a plain message', async (answer, text) => {
    stubApi({ 'GET /api/ads/budget': { ...BUDGET, killed: true }, 'POST /api/ads/unkill': answer })
    render(<Ads />)
    fireEvent.click(await screen.findByRole('button', { name: 'Allow ads again' }))
    const sheet = screen.getByRole('dialog')
    fireEvent.change(within(sheet).getByLabelText('Password'), { target: { value: 'x' } })
    fireEvent.click(within(sheet).getByRole('button', { name: 'Allow ads again' }))
    expect((await within(sheet).findByRole('alert')).textContent).toBe(text)
  })

  it('proposes a test and shows the needed budget and the underpowered reason', async () => {
    const calls = stubApi({ 'POST /api/ads/tests': { ...TEST, underpowered: 'the caps allow less than the test needs' } })
    render(<Ads />)
    fireEvent.click(screen.getByRole('button', { name: 'Propose a test' }))
    const sheet = screen.getByRole('dialog', { name: 'Propose a test' })
    const submit = within(sheet).getByRole('button', { name: 'Work out the budget' })
    const boss = await within(sheet).findByRole('checkbox', { name: /Boss fight/ })
    expect(boss.closest('label')?.querySelector('img')?.getAttribute('src')).toBe('/api/media/1/thumb.jpg')
    fireEvent.click(boss)
    fireEvent.click(within(sheet).getByRole('checkbox', { name: /Quiz chest/ }))
    expect(within(sheet).getByRole('checkbox', { name: /Quiz chest/ }).closest('label')?.querySelector('img')).toBeNull()
    expect(within(sheet).getAllByRole('option').map((o) => o.textContent)).toEqual(PRESETS.map((p) => p.label))
    expect((submit as HTMLButtonElement).disabled).toBe(true) // no hypothesis yet
    fireEvent.change(within(sheet).getByLabelText('What you expect'), { target: { value: 'Boss fight wins' } })
    fireEvent.click(submit)
    expect(await screen.findByText('To see a 20 % lift you need about €84.00 over 7 days.')).toBeTruthy()
    expect(screen.getByRole('alert').textContent).toMatch(/Too small: the caps allow less/)
    expect(posts(calls)[0]).toEqual({ key: 'POST /api/ads/tests', body: {
      hypothesis: 'Boss fight wins', variable: 'creative', min_lift: 0.2,
      variants: [{ media_id: '1', preset: 'fr_reels' }, { media_id: '2', preset: 'fr_reels' }] } })
  })

  it('proposes an audience test: one winner, two presets', async () => {
    const calls = stubApi()
    render(<Ads />)
    fireEvent.click(screen.getByRole('button', { name: 'Propose a test' }))
    const sheet = screen.getByRole('dialog')
    fireEvent.click(within(sheet).getByRole('tab', { name: 'Audience' }))
    fireEvent.click(await within(sheet).findByRole('radio', { name: /Boss fight/ }))
    expect(within(sheet).queryByRole('button', { name: 'France, Feed and Reels' })).toBeNull() // placement only
    fireEvent.click(within(sheet).getByRole('button', { name: 'France, Reels' }))
    fireEvent.click(within(sheet).getByRole('button', { name: /Belgium/ }))
    fireEvent.change(within(sheet).getByLabelText('What you expect'), { target: { value: 'h' } })
    fireEvent.click(within(sheet).getByRole('button', { name: 'Work out the budget' }))
    await vi.waitFor(() => expect(posts(calls)[0]?.body).toMatchObject({ variable: 'audience', variants: [
      { media_id: '1', preset: 'fr_reels' }, { media_id: '1', preset: 'francophone_reels' }] }))
  })

  it('shows one calm note when ads are not configured, and keeps the budget card', async () => {
    stubApi({ 'POST /api/ads/tests': [503, { error: 'ads_not_configured', message: 'ads_not_configured: set it' }] })
    render(<Ads />)
    fireEvent.click(screen.getByRole('button', { name: 'Propose a test' }))
    const sheet = screen.getByRole('dialog')
    fireEvent.click(await within(sheet).findByRole('checkbox', { name: /Boss fight/ }))
    fireEvent.click(within(sheet).getByRole('checkbox', { name: /Quiz chest/ }))
    fireEvent.change(within(sheet).getByLabelText('What you expect'), { target: { value: 'h' } })
    fireEvent.click(within(sheet).getByRole('button', { name: 'Work out the budget' }))
    expect(await screen.findByText(/Ads are not set up yet. Setup step H6/)).toBeTruthy()
    expect(screen.getByRole('region', { name: 'Budget' })).toBeTruthy()
  })

  it('approves with budget and password, the underpowered box only when needed, and shows refusals', async () => {
    const calls = stubApi({ 'POST /api/ads/tests/4/approve': [409, { error: 'daily_cap', message: 'over the daily cap' }] })
    render(<Ads />)
    fireEvent.click(await screen.findByRole('button', { name: 'Approve' }))
    const sheet = screen.getByRole('dialog', { name: 'Approve and start' })
    const budget = within(sheet).getByLabelText('Budget (EUR)') as HTMLInputElement
    expect(budget.value).toBe('84.00')
    expect(within(sheet).queryByRole('checkbox')).toBeNull()
    fireEvent.change(within(sheet).getByLabelText('Password'), { target: { value: 'pw' } })
    fireEvent.click(within(sheet).getByRole('button', { name: 'Approve and spend' }))
    expect((await within(sheet).findByRole('alert')).textContent).toBe('over the daily cap')
    expect(posts(calls)).toEqual([{ key: 'POST /api/ads/tests/4/approve',
      body: { budget: '84.00', password: 'pw', underpowered_ok: false } }])

    fireEvent.change(budget, { target: { value: '50' } })
    expect(within(sheet).getByText(/Too small to trust: the budget is below the €84.00/)).toBeTruthy()
    const go = within(sheet).getByRole('button', { name: 'Approve and spend' }) as HTMLButtonElement
    expect(go.disabled).toBe(true)
    fireEvent.click(within(sheet).getByRole('checkbox', { name: 'Run underpowered anyway' }))
    fireEvent.click(go)
    await vi.waitFor(() => expect(posts(calls).at(-1)?.body).toEqual({ budget: '50', password: 'pw', underpowered_ok: true }))
  })

  it('cancels a test only after the confirm step', async () => {
    const calls = stubApi()
    render(<Ads />)
    fireEvent.click(await screen.findByRole('button', { name: 'Cancel' }))
    expect(posts(calls)).toEqual([])
    expect(screen.getByText('Cancel this test? Its ads stop.')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Yes, cancel it' }))
    await vi.waitFor(() => expect(posts(calls)).toEqual([{ key: 'POST /api/ads/tests/4/cancel', body: undefined }]))
  })

  it('lists the audit log, paged', async () => {
    const calls = stubApi()
    render(<Ads />)
    const log = await screen.findByRole('region', { name: 'Audit log' })
    expect(await within(log).findByText('Kill')).toBeTruthy()
    expect(within(log).getByText('Reason: too much')).toBeTruthy()
    expect(within(log).getByText('1–20 of 25')).toBeTruthy()
    fireEvent.click(within(log).getByRole('button', { name: 'Older' }))
    await vi.waitFor(() => expect(calls.at(-1)?.key).toBe('GET /api/ads/audit?limit=20&offset=20'))
  })

  describe('results', () => {
    const v = (media_id: string, impressions: number, spend: string) =>
      ({ media_id, preset: 'fr_reels', impressions, clicks: 0, results: 0, spend })
    const EVAL: AdEvaluation = {
      status: 'winner', metric: 'ctr', days: 9, winner: 'B', p_values: { A: 0.0123 },
      variants: { A: { successes: 60, trials: 6000, rate: 0.01 }, B: { successes: 74, trials: 6000, rate: 0.0124 } },
      lift: { vs: 'A', value: 0.24, ci_low: 0.1, ci_high: 0.38, confidence: 0.95 },
    }
    const ISSUE = { ad_id: '903', media_id: '2', effective_status: 'DISAPPROVED', reason: 'Text: too much text' }
    const running = (evaluation: Partial<AdEvaluation>, review: typeof ISSUE[] = []): AdTest => ({
      ...TEST, status: 'running', budget_total: '84.00',
      result: { synced_at: '2026-11-18T09:00:00+00:00', days: evaluation.days ?? 9,
        variants: { A: v('1', 6000, '21.00'), B: v('2', 6000, '21.50') }, evaluation: { ...EVAL, ...evaluation }, review },
    })
    const details = (t: AdTest): AdTestResults => ({
      ...t, spend: { reported: '42.50', counted: '84.00', budget: '84.00', currency: 'EUR' },
      near_cap: { daily: false, lifetime: false, test: false },
    })
    async function openResults(t: AdTest) {
      const calls = stubApi({ 'GET /api/ads/tests': { tests: [t] }, 'GET /api/ads/tests/4': details(t) })
      render(<Ads />)
      fireEvent.click(await screen.findByRole('button', { name: 'Results' }))
      const sheet = screen.getByRole('dialog', { name: 'Test #4 results' })
      await within(sheet).findByText(/€42.50 spent of €84.00/)
      return { calls, sheet }
    }

    it('says who won, by how much, with the interval, and shows spend and versions', async () => {
      const { calls, sheet } = await openResults(running({}))
      expect(calls.some((c) => c.key === 'GET /api/ads/tests/4')).toBe(true)
      expect(within(sheet).getByText('B gets 24 % more clicks than A (between 10 % and 38 %), 95 % sure.')).toBeTruthy()
      expect(within(sheet).getByRole('progressbar', { name: 'Spend' }).getAttribute('aria-valuenow')).toBe('51')
      const row = within(sheet).getByText('B · Post 2').closest('tr') as HTMLElement
      expect(row.textContent).toBe('B · Post 21.24 %6,000€21.50')
    })

    it('keeps the p-values in a details disclosure', async () => {
      const { sheet } = await openResults(running({}))
      const box = within(sheet).getByText('Details').closest('details') as HTMLDetailsElement
      expect(box.open).toBe(false)
      expect(within(box).getByText('A vs the leader: p = 0.0123')).toBeTruthy()
    })

    it.each([
      [{ status: 'too_early', days: 3, winner: null, lift: null, p_values: {},
        variants: { A: { successes: 9, trials: 1200, rate: 0.0075 }, B: { successes: 9, trials: 1300, rate: 0.007 } } },
      'Too early: day 3 of 7, 1,200 of 5,000 views per version.'],
      [{ status: 'running', winner: null, lift: null }, 'No clear difference yet.'],
      [{ status: 'no_difference', days: 30, winner: null, lift: null }, 'No clear difference after 30 days.'],
    ] as [Partial<AdEvaluation>, string][])('says %j in plain words', async (evaluation, text) => {
      const { sheet } = await openResults(running(evaluation))
      expect(within(sheet).getByText(text)).toBeTruthy()
    })

    it('says why when the numbers could not be judged', async () => {
      const t = running({})
      const { sheet } = await openResults({ ...t, result: { ...t.result!,
        evaluation: { status: 'error', error: 'expected 2 variants, got 1' } as AdEvaluation } })
      expect(within(sheet).getByText('The numbers could not be judged: expected 2 variants, got 1.')).toBeTruthy()
      expect(within(sheet).getByText('No p-values before the planned sample is reached.')).toBeTruthy()
    })

    it('shows the review issue on the row and in the details', async () => {
      const t = running({ status: 'running' }, [ISSUE, { ...ISSUE, ad_id: '904', effective_status: 'WITH_ISSUES', reason: 'limited' }])
      const { sheet } = await openResults(t)
      expect(within(sheet).getByText('Meta rejected')).toBeTruthy()
      expect(within(sheet).getByText('Text: too much text')).toBeTruthy()
      const tests = screen.getByRole('region', { name: 'Tests', hidden: true })
      expect(within(tests).getAllByText(/^Meta (rejected|limits)$/, { exact: true }).map((e) => e.textContent))
        .toContain('Meta limits')
    })

    it('shows the declared winner on a finished row', async () => {
      stubApi({ 'GET /api/ads/tests': { tests: [{ ...running({}), status: 'finished', reason: 'winner' }] } })
      render(<Ads />)
      expect(await screen.findByText('Winner: B (Post 2)')).toBeTruthy()
    })

    it('warns when the server flags a scope near its cap', async () => {
      stubApi({ 'GET /api/ads/budget': { ...BUDGET, daily: scope('20', '17'), tests: [{ test_id: 4, ...scope('100', '90') }],
        near_cap: { daily: true, lifetime: false, tests: [4] } } })
      render(<Ads />)
      expect(await screen.findByText("Today's ad spend is at 85 % of the daily cap.")).toBeTruthy()
      expect(screen.getByText('Test #4 is at 90 % of its cap.')).toBeTruthy()
      expect(screen.queryByText(/lifetime cap/)).toBeNull()
    })

    it('shows no near-cap banner when the server does not flag one', async () => {
      stubApi({ 'GET /api/ads/budget': { ...BUDGET, daily: scope('20', '19') } })
      render(<Ads />)
      await screen.findByRole('region', { name: 'Budget' })
      expect(screen.queryByText(/of the daily cap/)).toBeNull()
    })
  })
})
