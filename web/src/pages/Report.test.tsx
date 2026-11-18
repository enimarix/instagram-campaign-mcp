import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { DailyReport, ReportDay } from '../api/client'
import ReportPage, { TodayReport } from './Report'

const REPORT: DailyReport = {
  report_date: '2026-11-16',
  summary: '# Good day\nThe **quiz** won.\n\n- hook held\n- [source](https://example.com/a)\n\nSee hook_type and `code`.',
  facts: {
    yesterday: {
      published: { count: 2 }, matured: { count: 1 },
      funnel: { produced: 9, reviewed: 8, liked: 5, approved: 3, published: 2, winner: 1, like_rate: 0.6, approval_rate: 0.3 },
    },
    audience_comments: { note: null, posts: [{ media_id: 'm1', permalink: 'https://www.instagram.com/reel/1/', comments: [{ quote: 'so funny <b>lol</b>', likes: 12 }] }] },
  },
  analysis: {
    best: [{ media_id: 'm1', why: 'hook holds: skip 20 % vs 35 %' }],
    worst: [{ media_id: 'm/2', why: 'left at 0:06 during the freeze' }],
    experiments: [{ hypothesis: 'Question hooks keep viewers', variable: 'hook_type', variants: ['question', 'pov'] }],
  },
  posts: {
    m1: { media_id: 'm1', permalink: null, title: 'The quiz', asset_id: 7, thumbnail_url: '/api/media/7/thumb.jpg', verdict: 'winner', retention: [] },
    'm/2': {
      media_id: 'm/2', permalink: null, title: null, asset_id: null, thumbnail_url: null, verdict: 'weak',
      retention: [{ kind: 'exit', at_s: 6.4, confidence: 'low', evidence: {}, text: 'The average viewer leaves around 0:06' }],
    },
  },
}
const day = (report_date: string, first_line: string | null): ReportDay =>
  ({ report_date, first_line, published: 1, matured: 1, best: 1, worst: 1, experiments: 0 })
const ARCHIVE = [{ ...day('2026-11-17', null), published: 0, matured: 0 }, day('2026-11-16', 'Good day'), day('2026-11-15', 'Older day')]

function stubApi(routes: Record<string, unknown>) {
  vi.stubGlobal('fetch', vi.fn(async (url: string) =>
    routes[url] !== undefined ? new Response(JSON.stringify(routes[url])) : new Response('{"error":"not_found"}', { status: 404 })))
}
const show = (path: string) => render(
  <MemoryRouter initialEntries={[path]}>
    <Routes>
      <Route path="/reports" element={<ReportPage />} />
      <Route path="/reports/:date" element={<ReportPage />} />
      <Route path="/today" element={<TodayReport />} />
    </Routes>
  </MemoryRouter>)

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('ReportPage', () => {
  it('renders the summary, picks with links, experiments, numbers and viewer quotes', async () => {
    stubApi({ '/api/reports/latest': REPORT, '/api/reports?limit=60': ARCHIVE })
    show('/reports')
    expect(await screen.findByRole('heading', { name: 'Good day' })).toBeTruthy()
    expect(screen.getByText('quiz').tagName).toBe('STRONG')
    expect(screen.getByText('hook held').tagName).toBe('LI')
    expect(screen.getByRole('link', { name: 'source' }).getAttribute('href')).toBe('https://example.com/a')
    expect(screen.getByText(/See hook_type and/)).toBeTruthy() // no italics inside a word
    expect(screen.getByText('code').tagName).toBe('CODE')

    const best = screen.getByRole('region', { name: 'Best' })
    expect(within(best).getByRole('link', { name: 'The quiz' }).getAttribute('href')).toBe('/analytics/posts/m1')
    expect(best.querySelector('img')?.getAttribute('src')).toBe('/api/media/7/thumb.jpg')
    expect(within(best).getByText(/hook holds/)).toBeTruthy()
    const worst = screen.getByRole('region', { name: 'Worst' })
    expect(within(worst).getByRole('link', { name: 'Untitled post' }).getAttribute('href')).toBe('/analytics/posts/m%2F2')
    expect(within(worst).getByText('Exit · 0:06')).toBeTruthy()
    expect(within(worst).getByText(/The average viewer leaves/)).toBeTruthy()

    const ideas = screen.getByRole('region', { name: 'Ideas to try next' })
    expect(within(ideas).getByText('Question hooks keep viewers')).toBeTruthy()
    expect(within(ideas).getByText(/Change hook type/)).toBeTruthy()
    expect(within(ideas).getByText('pov')).toBeTruthy()

    const numbers = screen.getByRole('region', { name: "The day's numbers" })
    expect(within(numbers).getByText('Old enough to judge').nextElementSibling?.textContent).toBe('1')
    expect(within(numbers).getByText('Videos made').nextElementSibling?.textContent).toBe('9')

    const viewers = screen.getByRole('region', { name: 'From viewers' })
    expect(viewers.querySelector('blockquote')?.textContent).toBe('“so funny <b>lol</b>”') // text, not markup
    expect(within(viewers).getByText(/from viewers · 12 likes/)).toBeTruthy()
    expect(within(viewers).getByRole('link', { name: 'the post' }).getAttribute('href')).toBe('https://www.instagram.com/reel/1/')
  })

  it('shows raw HTML in the summary as text and never runs it', async () => {
    stubApi({ '/api/reports/latest': { ...REPORT, summary: 'Hi <script>window.pwned = 1</script> <img src=x onerror="window.pwned=1">\n[x](javascript:alert(1))' }, '/api/reports?limit=60': [] })
    const { container } = show('/reports')
    expect(await screen.findByText(/<script>window.pwned = 1<\/script>/)).toBeTruthy()
    expect(container.querySelector('script, img[src="x"]')).toBeNull()
    expect(screen.queryByRole('link', { name: 'x' })).toBeNull() // only http(s) links
    expect((window as { pwned?: number }).pwned).toBeUndefined()
  })

  it('shows the empty and quiet states', async () => {
    stubApi({ '/api/reports?limit=60': [] })
    show('/reports')
    expect(await screen.findByText('No report yet')).toBeTruthy()
    expect(screen.getByText(/runs at 02:00/)).toBeTruthy()
    cleanup()

    stubApi({ '/api/reports/2026-11-17': { ...REPORT, report_date: '2026-11-17', summary: null, analysis: {}, posts: {}, facts: { yesterday: {} } }, '/api/reports?limit=60': ARCHIVE })
    show('/reports/2026-11-17')
    expect(await screen.findByText(/Quiet day: nothing was published/)).toBeTruthy()
    expect(screen.queryByRole('region', { name: 'Best' })).toBeNull()
    cleanup()

    // facts stored, the analysis not run yet: not a quiet day
    stubApi({ '/api/reports/2026-11-17': { ...REPORT, summary: null, analysis: {}, posts: {} }, '/api/reports?limit=60': ARCHIVE })
    show('/reports/2026-11-17')
    expect(await screen.findByText(/Not analysed yet/)).toBeTruthy()
    cleanup()

    stubApi({ '/api/reports?limit=60': ARCHIVE })
    show('/reports/2020-01-01')
    expect(await screen.findByText('No report for this day.')).toBeTruthy()
  })

  it('moves between days with older / newer and the archive', async () => {
    stubApi({
      '/api/reports/2026-11-16': REPORT, '/api/reports?limit=60': ARCHIVE,
      '/api/reports/2026-11-15': { ...REPORT, report_date: '2026-11-15', summary: 'Older day' },
    })
    show('/reports/2026-11-16')
    await screen.findByRole('heading', { name: 'Good day' })
    const nav = screen.getByRole('navigation', { name: 'Other days' })
    expect(await within(nav).findByRole('link', { name: 'Newer →' })).toHaveProperty('href', expect.stringMatching(/\/reports\/2026-11-17$/))
    const archive = screen.getByRole('region', { name: 'All reports' })
    expect(within(archive).getByRole('link', { current: 'page' }).textContent).toContain('2026-11-16')
    expect(within(archive).getByText('Quiet day')).toBeTruthy()
    fireEvent.click(within(nav).getByRole('link', { name: '← Older' }))
    expect(await screen.findByText('Older day', { selector: 'p' })).toBeTruthy()
    expect(within(screen.getByRole('navigation', { name: 'Other days' })).getByRole('link', { name: 'Newer →' }))
      .toHaveProperty('href', expect.stringMatching(/\/reports\/2026-11-16$/))
  })
})

describe('TodayReport (Analytics card)', () => {
  it('shows the newest report and links to it', async () => {
    stubApi({ '/api/reports/latest': REPORT })
    show('/today')
    const card = screen.getByRole('region', { name: "Today's report" })
    expect(await within(card).findByRole('link', { name: 'Read the report' })).toHaveProperty('href', expect.stringMatching(/\/reports\/2026-11-16$/))
    expect(within(card).getByText(/Good day/)).toBeTruthy()
    expect(within(card).getByText('1 best · 1 worst · 1 ideas to try')).toBeTruthy()
  })

  it('says when the first report will come', async () => {
    stubApi({})
    show('/today')
    expect(await screen.findByText('No report yet: the nightly analysis runs at 02:00.')).toBeTruthy()
  })
})
