import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ClaudeIdea, Planning as PlanningData, PlanningItem } from '../api/client'
import { ToastProvider } from '../ui/Toast'
import Planning from './Planning'

const soon = (min: number) => new Date(Date.now() + min * 60_000).toISOString()
const item = (over: Partial<PlanningItem>): PlanningItem => ({
  section: 'next', kind: 'render', title: 'Pourquoi on a faim', source: 'create', ids: {}, style: null,
  engine: 'remotion', voice: null, est_start: soon(1), est_duration_s: 600, est_ready: soon(11), estimated: true,
  why_here: "File des rendus : le plus ancien d'abord.", waits_on: null, not_before: null, stage: null, progress: null, ...over,
})

const idea = (over: Partial<ClaudeIdea> = {}): PlanningItem => item({
  section: 'ideas', kind: 'claude_idea', title: 'Le mythe du jus détox', source: 'agent', ids: { asset_id: 9 },
  est_start: null, est_ready: null, est_duration_s: null, why_here: 'Idée de Claude : rien ne se rend sans toi.',
  idea: {
    asset_id: 9, batch_date: '2026-11-23', hook: 'Le mythe du jus détox', style: 'pixel', kind: 'motion',
    template: 'FactQuest', voice: 'lea', music: 'music-overworld', caption: 'Le jus détox ? #nutrition',
    description: 'Trois faits.', sources: [{ url: 'https://example.org/a', title: 'Étude' }],
    music_options: ['music-cave', 'music-overworld', 'none'],
    script: [{ text: 'Le jus détox', editable: true }, { text: 'Fait un', editable: true },
      { text: 'Fait deux', editable: false }, { text: 'Fin', editable: true }], ...over,
  },
})

function stub(items: PlanningItem[]) {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ now: soon(0), items }))))
}
type Call = { method: string; url: string; body: unknown }
function stubCalls(items: PlanningItem[]) {
  const calls: Call[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET'
    calls.push({ method, url, body: init?.body ? JSON.parse(String(init.body)) : undefined })
    if (method === 'GET') return new Response(JSON.stringify({ now: soon(0), items }))
    return new Response(JSON.stringify({ not_before: null }))
  }))
  return calls
}
const show = () => render(<MemoryRouter><ToastProvider><Planning /></ToastProvider></MemoryRouter>)

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('Planning', () => {
  it('shows the chain in its three sections, linked to the video and the Inbox', async () => {
    stub([
      item({ section: 'running', title: 'Le rendu actuel', ids: { asset_id: 17 }, stage: 'rendu', progress: 0.5 }),
      item({ title: 'Ma commande', kind: 'work_order', ids: { order_id: 4 }, waits_on: 'gpu_busy', style: 'blender', engine: 'blender' }),
      item({ section: 'planned', kind: 'agent_run', title: 'Vidéos du jour', source: 'schedule',
        picks_up: { orders: 2, change_requests: 1, dm_picks: 0, ideas_left: 7 } }),
    ])
    show()
    const running = await screen.findByRole('region', { name: 'En cours' })
    expect(within(running).getByRole('link', { name: 'vidéo 17' }).getAttribute('href')).toBe('/assets/17')
    expect(within(running).getByRole('progressbar').getAttribute('aria-valuenow')).toBe('50')
    const next = screen.getByRole('region', { name: 'Ensuite' })
    expect(within(next).getByText('attend le GPU')).toBeTruthy()
    expect(within(next).getByText('style blender · moteur blender')).toBeTruthy()
    expect(within(next).getByText(/10 min/)).toBeTruthy()
    const planned = screen.getByRole('region', { name: "Runs prévus de l'IA" })
    expect(within(planned).getByText(/place\(s\) pour les idées de Claude/).textContent).toContain('7')
    expect(screen.getAllByRole('link', { name: 'Inbox' })).toHaveLength(2) // the videos, not the run
    expect(within(next).getByText(/vérification par l'IA/).textContent).toBe("→ vérification par l'IA → Inbox")
    expect(document.querySelector('a[href="/calendar"]')).toBeNull() // publishing is the Calendar's (195)
  })

  it('a run with no batch limit says so (206)', async () => {
    stub([item({ section: 'planned', kind: 'agent_run', title: 'Vidéos du jour', source: 'schedule',
      picks_up: { orders: 0, change_requests: 0, dm_picks: 0, ideas_left: null } })])
    show()
    expect((await screen.findByText(/pour les idées de Claude/)).textContent).toContain('sans limite pour les idées de Claude')
  })

  it('says when nothing is planned', async () => {
    stub([])
    show()
    expect(await screen.findByText('Rien de prévu')).toBeTruthy()
  })

  it('an order that waits for the owner has no time', async () => {
    stub([item({ kind: 'work_order', waits_on: 'needs_instruction', est_start: null, est_ready: null, est_duration_s: null })])
    show()
    expect(await screen.findByText('attend ta consigne')).toBeTruthy()
    expect(screen.getByText("Pas d'heure : attend ta consigne.")).toBeTruthy()
  })

  it("a film past the daily cap points at the owner's setting (205)", async () => {
    stub([item({ kind: 'film', title: 'Un film', ids: { order_id: 4 }, waits_on: 'daily_cap', est_start: null, est_ready: null, est_duration_s: null })])
    show()
    expect(await screen.findByText('limite de films du jour atteinte (Réglages)')).toBeTruthy()
  })

  it('a waiting render starts now; the running card has no such button', async () => {
    const calls = stubCalls([
      item({ section: 'running', title: 'Le rendu actuel', ids: { asset_id: 17, job_id: 5 }, progress: 0.5 }),
      item({ title: 'Le suivant', ids: { asset_id: 18, job_id: 6 }, waits_on: 'gpu_busy' }),
      item({ kind: 'work_order', title: 'Ma commande', ids: { order_id: 4 } }),
    ])
    show()
    const running = await screen.findByRole('region', { name: 'En cours' })
    expect(within(running).queryByRole('button', { name: 'Lancer maintenant' })).toBeNull()
    const [button] = within(screen.getByRole('region', { name: 'Ensuite' })).getAllByRole('button', { name: 'Lancer maintenant' })
    expect(screen.getAllByRole('button', { name: 'Lancer maintenant' })).toHaveLength(2) // the order's launches (196)
    fireEvent.click(button)
    expect(await screen.findByText('Passe en tête de la file.')).toBeTruthy()
    expect(calls).toContainEqual({ method: 'POST', url: '/api/planning/render/6/start-now', body: undefined })
    await waitFor(() => expect(calls.filter((c) => c.method === 'GET').length).toBeGreaterThan(1)) // reloaded
  })

  it("a film's timer is set in owner-local time, shown on the card, and cleared", async () => {
    const calls = stubCalls([item({ kind: 'film', title: 'Un film', ids: { order_id: 4 }, waits_on: 'timer', not_before: soon(120) })])
    show()
    expect(await screen.findByText(/^Minuteur : .*\d\d:\d\d/)).toBeTruthy() // its slot (195)
    expect(screen.getByText('attend son minuteur')).toBeTruthy()
    const input = screen.getByLabelText('Minuteur') as HTMLInputElement
    expect(input.type).toBe('datetime-local')
    fireEvent.change(input, { target: { value: '2026-11-30T14:30' } })
    fireEvent.click(screen.getByRole('button', { name: 'Régler' }))
    expect(await screen.findByText(/Minuteur réglé : pas avant/)).toBeTruthy()
    expect(calls).toContainEqual({ method: 'PUT', url: '/api/planning/film/4/timer', body: { at: new Date('2026-11-30T14:30').toISOString() } })
    fireEvent.click(screen.getByRole('button', { name: 'Retirer le minuteur' }))
    expect(await screen.findByText('Minuteur retiré.')).toBeTruthy()
    expect(calls).toContainEqual({ method: 'PUT', url: '/api/planning/film/4/timer', body: { at: null } })
  })

  it('a render waiting for the machine says so, with its next try (197)', async () => {
    stub([item({ ids: { asset_id: 68, job_id: 7 }, waits_on: 'machine', not_before: soon(20) })])
    show()
    expect(await screen.findByText(/^En attente de la machine — nouvel essai vers .*\d\d:\d\d/)).toBeTruthy()
    expect(screen.getByText('attend la machine')).toBeTruthy()
  })

  it('a refused start says why', async () => {
    vi.stubGlobal('fetch', vi.fn(async (_url: string, init?: RequestInit) => init?.method
      ? new Response(JSON.stringify({ error: 'invalid', message: 'Ce rendu est en cours' }), { status: 422 })
      : new Response(JSON.stringify({ now: soon(0), items: [item({ ids: { job_id: 6 } })] }))))
    show()
    fireEvent.click(await screen.findByRole('button', { name: 'Lancer maintenant' }))
    expect(await screen.findByText('Pas fait : Ce rendu est en cours')).toBeTruthy()
  })

  it('moves a waiting render up / down and holds or releases a film (187)', async () => {
    const calls = stubCalls([
      item({ title: 'Le suivant', ids: { job_id: 6 } }),
      item({ kind: 'film', title: 'Un film', ids: { order_id: 4 }, waits_on: 'held', est_start: null, est_ready: null }),
    ])
    show()
    const [render, film] = await screen.findAllByRole('article')
    fireEvent.click(within(render).getByRole('button', { name: 'Monter' }))
    expect(await screen.findByText('Monté d’une place.')).toBeTruthy()
    fireEvent.click(within(render).getByRole('button', { name: 'Descendre' }))
    await waitFor(() => expect(calls).toContainEqual({ method: 'POST', url: '/api/planning/render/6/move', body: { by: 1 } }))
    expect(calls).toContainEqual({ method: 'POST', url: '/api/planning/render/6/move', body: { by: -1 } })
    fireEvent.click(within(render).getByRole('button', { name: 'Mettre en pause' }))
    await waitFor(() => expect(calls).toContainEqual({ method: 'PUT', url: '/api/planning/render/6/hold', body: { held: true } }))
    expect(within(film).getByText('En pause')).toBeTruthy()
    fireEvent.click(within(film).getByRole('button', { name: 'Reprendre' }))
    await waitFor(() => expect(calls).toContainEqual({ method: 'PUT', url: '/api/planning/film/4/hold', body: { held: false } }))
  })

  it('removes with a 5 s undo: nothing is sent before it closes', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      const calls = stubCalls([
        item({ title: 'Le suivant', ids: { job_id: 6 } }),
        item({ kind: 'work_order', title: 'Ma commande', ids: { order_id: 4 } }),
        item({ kind: 'work_order', title: 'Sans consigne', ids: { order_id: 5 }, waits_on: 'needs_instruction' }),
      ])
      show()
      const titles = () => screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent)
      const buttons = await screen.findAllByRole('button', { name: 'Retirer' })
      expect(buttons).toHaveLength(2) // not on the order that waits for its instruction
      fireEvent.click(buttons[0])
      expect(screen.queryByText('Le suivant')).toBeNull() // out at once
      fireEvent.click(screen.getByRole('button', { name: 'Annuler' }))
      expect(titles()).toEqual(['Le suivant', 'Ma commande', 'Sans consigne']) // back in its place
      vi.advanceTimersByTime(6000)
      expect(calls.filter((c) => c.url.endsWith('/remove'))).toEqual([])
      fireEvent.click(screen.getAllByRole('button', { name: 'Retirer' })[1])
      expect(screen.queryByText('Ma commande')).toBeNull()
      expect(calls.filter((c) => c.url.endsWith('/remove'))).toEqual([])
      vi.advanceTimersByTime(5000)
      await waitFor(() => expect(calls).toContainEqual({ method: 'POST', url: '/api/planning/order/4/remove', body: undefined }))
    } finally {
      vi.useRealTimers()
    }
  })

  it('leaving the page sends a removal still in its undo window', async () => {
    const calls = stubCalls([item({ kind: 'film', title: 'Un film', ids: { order_id: 4 } })])
    show()
    fireEvent.click(await screen.findByRole('button', { name: 'Retirer' }))
    cleanup()
    await waitFor(() => expect(calls).toContainEqual({ method: 'POST', url: '/api/planning/film/4/remove', body: undefined }))
  })

  it('the pause switch pauses and resumes the whole studio', async () => {
    let paused: string | null = null
    const calls: Call[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      const body = init?.body ? JSON.parse(String(init.body)) : undefined
      calls.push({ method: init?.method ?? 'GET', url, body })
      if (init?.method === 'PUT') paused = body.paused ? soon(0) : null
      return new Response(JSON.stringify(init?.method ? { paused } : { now: soon(0), items: [item({})], paused }))
    }))
    show()
    const toggle = await screen.findByRole('switch', { name: 'Tout mettre en pause' }) as HTMLInputElement
    expect(toggle.checked).toBe(false)
    fireEvent.click(toggle)
    expect(await screen.findByText('Studio en pause : rien ne démarre, ce qui tourne finit.')).toBeTruthy()
    expect(calls).toContainEqual({ method: 'PUT', url: '/api/planning/pause', body: { paused: true } })
    expect(toggle.checked).toBe(true)
    expect(screen.getByText(/Studio en pause depuis/)).toBeTruthy()
    fireEvent.click(toggle)
    expect(await screen.findByText('Studio repris : la file repart.')).toBeTruthy()
    expect(toggle.checked).toBe(false)
    expect(screen.queryByText(/Studio en pause depuis/)).toBeNull()
  })

  it("Claude's ideas: their own section and colour, the script, the sources; release, now, timer", async () => {
    const calls = stubCalls([idea(), item({ title: 'Le suivant', ids: { job_id: 6 } })])
    show()
    const ideas = await screen.findByRole('region', { name: 'Idées de Claude — à valider' })
    const card = within(ideas).getByRole('article')
    expect(card.className).toContain('border-l-idea')
    expect(within(card).getByText('Idée de Claude').className).toContain('text-idea')
    expect(within(card).getAllByRole('listitem').map((l) => l.textContent)).toEqual(
      ['Le jus détox', 'Fait un', 'Fait deux', '… 1 ligne(s) de plus'])
    expect(within(card).getByText('style pixel · FactQuest · voix lea · musique music-overworld')).toBeTruthy()
    expect(within(card).getByRole('link', { name: 'Étude' }).getAttribute('href')).toBe('https://example.org/a')
    expect(within(card).queryByText(/Génération prévue/)).toBeNull() // no time until released
    fireEvent.click(within(card).getByRole('button', { name: 'Valider' }))
    expect(await screen.findByText('Validée : son rendu entre dans la file.')).toBeTruthy()
    fireEvent.click(within(card).getByRole('button', { name: 'Lancer maintenant' }))
    await waitFor(() => expect(calls).toContainEqual({ method: 'POST', url: '/api/planning/idea/9/release', body: { now: true } }))
    expect(calls).toContainEqual({ method: 'POST', url: '/api/planning/idea/9/release', body: {} })
    fireEvent.change(within(card).getByLabelText('Minuteur'), { target: { value: '2026-12-01T09:30' } })
    fireEvent.click(within(card).getByRole('button', { name: 'Régler' }))
    const iso = new Date('2026-12-01T09:30').toISOString()
    await waitFor(() => expect(calls).toContainEqual({ method: 'POST', url: '/api/planning/idea/9/release', body: { at: iso } }))
  })

  it("edits an idea: only what changed is sent, a joined line stays locked, a refusal keeps the sheet", async () => {
    HTMLDialogElement.prototype.showModal = function () { this.open = true } // jsdom has none
    const calls: Call[] = []
    let refuse = true
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      calls.push({ method, url, body: init?.body ? JSON.parse(String(init.body)) : undefined })
      if (url === '/api/voices') return new Response(JSON.stringify([
        { id: 'lea', label: 'Léa', enabled: true }, { id: 'marc', label: 'Marc', enabled: true },
        { id: 'off', label: 'Éteinte', enabled: false }]))
      if (method === 'PATCH' && refuse) {
        refuse = false
        return new Response(JSON.stringify({ error: 'invalid', message: 'la ligne 1 est vide' }), { status: 422 })
      }
      return new Response(JSON.stringify(method === 'GET' ? { now: soon(0), items: [idea()] } : {}))
    }))
    show()
    fireEvent.click(await screen.findByRole('button', { name: 'Modifier' }))
    const sheet = await screen.findByRole('dialog', { name: "Modifier l'idée" })
    await waitFor(() => expect(within(sheet).getAllByRole('option', { name: 'Marc' })).toHaveLength(1))
    expect(within(sheet).queryByRole('option', { name: 'Éteinte' })).toBeNull()
    expect((within(sheet).getByLabelText('Ligne 3') as HTMLTextAreaElement).disabled).toBe(true)
    fireEvent.change(within(sheet).getByLabelText('Voix'), { target: { value: 'marc' } })
    fireEvent.change(within(sheet).getByLabelText('Musique'), { target: { value: 'none' } })
    fireEvent.change(within(sheet).getByLabelText('Ligne 1'), { target: { value: 'Le jus détox ne détoxifie rien.' } })
    fireEvent.click(within(sheet).getByRole('button', { name: 'Enregistrer' }))
    expect(await screen.findByText('Pas fait : la ligne 1 est vide')).toBeTruthy()
    expect(screen.getByRole('dialog', { name: "Modifier l'idée" })).toBeTruthy()
    fireEvent.click(within(sheet).getByRole('button', { name: 'Enregistrer' }))
    expect(await screen.findByText('Idée modifiée.')).toBeTruthy()
    expect(calls.filter((c) => c.method === 'PATCH').at(-1)).toEqual({
      method: 'PATCH', url: '/api/planning/idea/9',
      body: { voice: 'marc', music: 'none', lines: ['Le jus détox ne détoxifie rien.', 'Fait un', 'Fait deux', 'Fin'] },
    })
  })

  it('removes an idea after the 5 s undo', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      const calls = stubCalls([idea()])
      show()
      fireEvent.click(await screen.findByRole('button', { name: 'Retirer' }))
      expect(screen.queryByText('Le mythe du jus détox')).toBeNull()
      expect(calls.filter((c) => c.url.endsWith('/remove'))).toEqual([])
      vi.advanceTimersByTime(5000)
      await waitFor(() => expect(calls).toContainEqual({ method: 'POST', url: '/api/planning/idea/9/remove', body: undefined }))
    } finally {
      vi.useRealTimers()
    }
  })

  it('a running item past its usual time shows « en retard » in orange', async () => {
    stub([item({ section: 'running', title: 'Le rendu actuel', progress: 0.9, late_s: 600 })])
    show()
    const late = await screen.findByText('en retard de 10 min')
    expect(late.className).toContain('text-warn')
    expect(screen.getByText(/^En cours depuis/).className).toContain('text-warn')
  })

  describe('190 extras', () => {
    const extras = (over: Partial<PlanningData> = {}): PlanningData => ({
      now: soon(0), items: [], paused: null,
      strip: { start: soon(0), end: soon(24 * 60), blocks: [], posts: [] },
      supply: { approved: 4, bench: 2, per_day: 3, days: 2, until: '2026-11-26', low: false, making: 1, ideas: 2 },
      history: [], ...over,
    })
    function stubPlanning(p: PlanningData, preview?: unknown) {
      const calls: Call[] = []
      vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ method, url, body: init?.body ? JSON.parse(String(init.body)) : undefined })
        if (method === 'GET') return new Response(JSON.stringify(p))
        if (url === '/api/planning/preview') return new Response(JSON.stringify(preview ?? { pushed: [] }))
        return new Response('{}')
      }))
      return calls
    }

    it('the 24 h strip: a block per lane, a late one in orange, the posts as ticks, scrolls on a phone', async () => {
      stubPlanning(extras({
        items: [item({})],
        strip: {
          start: soon(0), end: soon(24 * 60), posts: [soon(180)],
          blocks: [
            { lane: 'render', kind: 'render', title: 'Le rendu', section: 'running', start: soon(0), end: soon(60), late: true },
            { lane: 'run', kind: 'agent_run', title: 'Vidéos du jour', section: 'planned', start: soon(600), end: soon(620), late: false },
          ],
        },
      }))
      show()
      const strip = await screen.findByRole('region', { name: 'Les prochaines 24 h' })
      expect(strip.querySelector('.overflow-x-auto')).toBeTruthy()
      const renders = within(within(strip).getByRole('list', { name: 'Rendus' })).getAllByRole('listitem')
      expect(renders).toHaveLength(1)
      expect(renders[0].className).toContain('bg-warn')
      expect(renders[0].getAttribute('aria-label')).toMatch(/^Rendu : Le rendu, .* en retard$/)
      expect(renders[0].style.left).toBe('0%')
      const run = within(within(strip).getByRole('list', { name: "Runs de l'IA" })).getByRole('listitem')
      expect(run.className).toContain('bg-accent')
      expect(parseFloat(run.style.left)).toBeCloseTo((600 / (24 * 60)) * 100, 0)
      expect(within(within(strip).getByRole('list', { name: 'Publications' })).getAllByRole('listitem')).toHaveLength(1)
      expect(within(strip).getByLabelText('Maintenant')).toBeTruthy()
    })

    it('the supply gauge: days, until, what is coming; orange under a day', async () => {
      stubPlanning(extras())
      show()
      expect(await screen.findByText(/Réserve : 2 jours/)).toBeTruthy()
      expect(screen.getByText(/jusqu'à jeudi/)).toBeTruthy()
      expect(screen.getByText('4 approuvée(s) + 2 sur le banc, 3 par jour · une fois faites : + 1 en fabrication, + 2 idée(s) de Claude')).toBeTruthy()
      expect(screen.getByRole('meter', { name: 'Réserve' }).getAttribute('aria-valuenow')).toBe('2')
      cleanup()
      stubPlanning(extras({ supply: { approved: 1, bench: 0, per_day: 3, days: 0.3, until: '2026-11-23', low: true, making: 0, ideas: 0 } }))
      show()
      const low = await screen.findByText(/Réserve : moins d’un jour/)
      expect(low.parentElement?.className).toContain('text-warn')
    })

    it("today's history: done to the Inbox, a failure with its reason and « Relancer », the runs", async () => {
      const recipe = { kind: 'motion', template: 'FactQuest', props: {} }
      const row = { asset_id: null, order_id: null, run_id: null, reason: null, status: null, recipe: null, tries: null }
      const calls = stubPlanning(extras({
        history: [
          { ...row, kind: 'failed', at: soon(-10), title: 'Raté', asset_id: 7, reason: 'ffmpeg crashed', recipe, tries: 2 },
          { ...row, kind: 'failed', at: soon(-15), title: 'Raté aussi', asset_id: 5, reason: 'blender crashed', recipe, tries: 2 },
          { ...row, kind: 'dropped', at: soon(-20), title: 'Floue', asset_id: 8, reason: 'image floue' },
          { ...row, kind: 'removed', at: soon(-30), title: 'Retirée', order_id: 3 },
          { ...row, kind: 'done', at: soon(-40), title: 'Finie', asset_id: 6 },
          { ...row, kind: 'run', at: soon(-50), title: 'Vidéos du jour', run_id: 2, status: 'succeeded' },
        ],
      }))
      show()
      const today = await screen.findByRole('region', { name: "Aujourd'hui" })
      const rows = within(today).getAllByRole('listitem')
      expect(rows.map((r) => r.textContent)).toEqual([
        expect.stringContaining('Rendu ratéRaté: ffmpeg crashed· 2 essais'), expect.stringContaining('Raté aussi'),
        expect.stringContaining('Écartée par la vérificationFloue: image floue'),
        expect.stringContaining('Retiré du planning'), expect.stringContaining('Rendu finiFinie'), expect.stringContaining('réussi'),
      ])
      expect(within(rows[4]).getByRole('link', { name: 'Inbox' }).getAttribute('href')).toBe('/inbox')
      expect(within(today).getAllByRole('button', { name: 'Relancer' })).toHaveLength(2) // every failed video (195)
      fireEvent.click(within(rows[0]).getByRole('button', { name: 'Relancer' }))
      expect(await screen.findByText('Relancé : le rendu revient dans la file.')).toBeTruthy()
      expect(calls).toContainEqual({ method: 'POST', url: '/api/assets/7/rerender', body: { recipe } })
    })

    it('the delay warning: what a start now pushes back, cancel sends nothing, confirm does', async () => {
      const calls = stubPlanning(extras({ items: [item({ title: 'Le suivant', ids: { job_id: 6 } })] }),
        { pushed: [{ kind: 'render', title: 'A', by_s: 5400 }, { kind: 'render', title: 'B', by_s: 5400 }, { kind: 'render', title: 'C', by_s: 5000 }] })
      show()
      fireEvent.click(await screen.findByRole('button', { name: 'Lancer maintenant' }))
      const box = await screen.findByRole('alertdialog', { name: 'Ce que ça repousse' })
      expect(within(box).getByText("Repousse 3 rendus d'environ 1 h 30.")).toBeTruthy()
      expect(calls).toContainEqual({ method: 'POST', url: '/api/planning/preview', body: { action: 'start_now', kind: 'render', id: 6 } })
      fireEvent.click(within(box).getByRole('button', { name: 'Annuler' }))
      expect(screen.queryByRole('alertdialog')).toBeNull()
      expect(calls.some((c) => c.url.endsWith('/start-now'))).toBe(false)
      fireEvent.click(screen.getByRole('button', { name: 'Descendre' }))
      await waitFor(() => expect(calls).toContainEqual({ method: 'POST', url: '/api/planning/preview', body: { action: 'move', kind: 'render', id: 6, by: 1 } }))
      fireEvent.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Confirmer' }))
      await waitFor(() => expect(calls).toContainEqual({ method: 'POST', url: '/api/planning/render/6/move', body: { by: 1 } }))
    })

    it("the delay warning before releasing Claude's idea with start now", async () => {
      const calls = stubPlanning(extras({ items: [idea()] }), { pushed: [{ kind: 'film', title: 'Un film', by_s: 900 }] })
      show()
      fireEvent.click(await screen.findByRole('button', { name: 'Lancer maintenant' }))
      const box = await screen.findByRole('alertdialog')
      expect(within(box).getByText("Repousse 1 élément d'environ 15 min.")).toBeTruthy()
      expect(calls).toContainEqual({ method: 'POST', url: '/api/planning/preview', body: { action: 'release', kind: 'idea', id: 9 } })
      fireEvent.click(within(box).getByRole('button', { name: 'Confirmer' }))
      await waitFor(() => expect(calls).toContainEqual({ method: 'POST', url: '/api/planning/idea/9/release', body: { now: true } }))
    })
  })

  it('a card leaving above keeps the typed timer, the open delay warning and the open sheet below (194)', async () => {
    HTMLDialogElement.prototype.showModal = function () { this.open = true } // jsdom has none
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const other = idea({ asset_id: 8, hook: 'Autre idée' })
    const first = [item({ title: 'Le premier', ids: { asset_id: 17, job_id: 5 } }),
      item({ kind: 'film', title: 'Un film', ids: { order_id: 4 } }),
      { ...other, title: 'Autre idée', ids: { asset_id: 8 } }, idea()]
    let items = first
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/voices') return new Response('[]')
      if (url === '/api/planning/preview') return new Response(JSON.stringify({ pushed: [{ kind: 'render', title: 'A', by_s: 900 }] }))
      return new Response(JSON.stringify(init?.method ? {} : { now: soon(0), items }))
    }))
    try {
      show()
      const film = (await screen.findByText('Un film')).closest('article') as HTMLElement
      fireEvent.change(within(film).getByLabelText('Minuteur'), { target: { value: '2026-11-30T14:30' } })
      fireEvent.click(within(film).getByRole('button', { name: 'Lancer maintenant' }))
      expect(await within(film).findByRole('alertdialog')).toBeTruthy()
      const mine = screen.getByText('Le mythe du jus détox').closest('article') as HTMLElement
      fireEvent.click(within(mine).getByRole('button', { name: 'Modifier' }))
      fireEvent.change(within(await screen.findByRole('dialog', { name: "Modifier l'idée" })).getByLabelText('Légende'),
        { target: { value: 'Ma légende' } })
      items = [first[1], first[3]] // the first render and the first idea are done
      await vi.advanceTimersByTimeAsync(10_000) // the poll
      await waitFor(() => expect(screen.queryByText('Le premier')).toBeNull())
      expect(screen.queryByText('Autre idée')).toBeNull()
      const after = screen.getByText('Un film').closest('article') as HTMLElement
      expect((within(after).getByLabelText('Minuteur') as HTMLInputElement).value).toBe('2026-11-30T14:30')
      expect(within(after).getByRole('alertdialog')).toBeTruthy()
      const sheet = screen.getByRole('dialog', { name: "Modifier l'idée" })
      expect((within(sheet).getByLabelText('Légende') as HTMLTextAreaElement).value).toBe('Ma légende')
    } finally {
      vi.useRealTimers()
    }
  })

  it('each card says its own generation slot in plain words (195)', async () => {
    stub([
      item({ section: 'running', title: 'Le rendu actuel', est_start: soon(-5), progress: 0.5 }),
      item({ title: 'Le suivant', ids: { job_id: 6 } }),
      item({ kind: 'film', title: 'Un film', ids: { order_id: 4 }, waits_on: 'held', est_start: null, est_ready: null, est_duration_s: null }),
      item({ kind: 'agent_run', title: 'Analyse de la nuit' }),
    ])
    show()
    const [running, next, film, run] = await screen.findAllByRole('article')
    expect(within(running).getByText(/^En cours depuis \d\d:\d\d/)).toBeTruthy()
    expect(within(next).getByText(/^Génération prévue vers \d\d:\d\d · 10 min · prête ~/)).toBeTruthy()
    expect(within(film).getAllByText('En pause')).toHaveLength(1) // the slot, no chip saying it again
    expect(within(run).getByText(/^Prévu vers/)).toBeTruthy()
    expect(within(run).queryByRole('link', { name: 'Inbox' })).toBeNull()
  })

  it('drags a waiting card with the pointer: the new order stays through a poll until the server answers (195)', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const rect = HTMLElement.prototype.getBoundingClientRect
    HTMLElement.prototype.getBoundingClientRect = function () { // jsdom lays nothing out: 100 px per card
      const n = [...document.querySelectorAll('[data-drag]')].indexOf(this)
      return { top: n * 100, height: 100, bottom: n * 100 + 100, left: 0, right: 0, width: 0, x: 0, y: n * 100, toJSON: () => ({}) }
    }
    const [a, b, c] = [
      item({ title: 'A', ids: { job_id: 1 }, line_index: 0 }),
      item({ kind: 'film', title: 'B', ids: { order_id: 2 }, line_index: 1 }),
      item({ title: 'C', ids: { job_id: 3 }, line_index: 2 }),
    ]
    let items = [a, b, c]
    let answer = () => {}
    const calls: Call[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ method: init?.method ?? 'GET', url, body: init?.body ? JSON.parse(String(init.body)) : undefined })
      if (url.endsWith('/place')) await new Promise<void>((r) => { answer = r })
      return new Response(JSON.stringify(init?.method ? {} : { now: soon(0), items }))
    }))
    const titles = () => screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent)
    try {
      show()
      const grips = await screen.findAllByRole('button', { name: 'Glisser pour déplacer' })
      expect(grips).toHaveLength(3)
      expect(grips[0].className).toContain('touch-none') // a finger drags, the page does not scroll
      fireEvent.pointerDown(grips[0], { button: 0, clientY: 50 })
      fireEvent.pointerMove(window, { clientY: 160 }) // past B's middle
      expect(titles()).toEqual(['B', 'A', 'C']) // live
      fireEvent.pointerUp(window, { clientY: 160 })
      await waitFor(() => expect(calls).toContainEqual({ method: 'POST', url: '/api/planning/render/1/place', // down: after B
        body: { anchor_kind: 'film', anchor_id: 2, side: 'after' } }))
      await vi.advanceTimersByTimeAsync(10_000) // a poll still says the old order
      expect(titles()).toEqual(['B', 'A', 'C'])
      items = [b, a, c].map((i, n) => ({ ...i, line_index: n }))
      answer()
      expect(await screen.findByText('Déplacé dans la file.')).toBeTruthy()
      await waitFor(() => expect(titles()).toEqual(['B', 'A', 'C']))
      fireEvent.pointerDown(screen.getAllByRole('button', { name: 'Glisser pour déplacer' })[2], { button: 0, clientY: 250 })
      fireEvent.pointerMove(window, { clientY: 10 }) // to the head
      fireEvent.pointerUp(window, { clientY: 10 })
      await waitFor(() => expect(calls).toContainEqual({ method: 'POST', url: '/api/planning/render/3/place', // up: before B
        body: { anchor_kind: 'film', anchor_id: 2, side: 'before' } }))
      answer()
      fireEvent.pointerDown(screen.getAllByRole('button', { name: 'Glisser pour déplacer' })[0], { button: 0, clientY: 50 })
      fireEvent.pointerUp(window, { clientY: 50 }) // dropped where it was: nothing sent
      expect(calls.filter((x) => x.url.endsWith('/place'))).toHaveLength(2)
    } finally {
      HTMLElement.prototype.getBoundingClientRect = rect
      vi.useRealTimers()
    }
  })

  it('a drop lands where the owner sees it with a machine card between; no drag while it saves (200)', async () => {
    const rect = HTMLElement.prototype.getBoundingClientRect
    HTMLElement.prototype.getBoundingClientRect = function () { // 100 px per card
      const n = [...document.querySelectorAll('[data-drag]')].indexOf(this)
      return { top: n * 100, height: 100, bottom: n * 100 + 100, left: 0, right: 0, width: 0, x: 0, y: n * 100, toJSON: () => ({}) }
    }
    // the line is R1, T0, R2; T0 waits for the machine, so the page shows it last
    const items = [
      item({ title: 'R1', ids: { job_id: 1 }, line_index: 0 }),
      item({ title: 'R2', ids: { job_id: 3 }, line_index: 2 }),
      item({ title: 'T0', ids: { job_id: 2 }, line_index: 1, waits_on: 'machine', not_before: soon(15) }),
    ]
    let answer = () => {}
    const calls: Call[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ method: init?.method ?? 'GET', url, body: init?.body ? JSON.parse(String(init.body)) : undefined })
      if (url.endsWith('/place')) await new Promise<void>((r) => { answer = r })
      return new Response(JSON.stringify(init?.method ? {} : { now: soon(0), items }))
    }))
    const titles = () => screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent)
    try {
      show()
      const grips = await screen.findAllByRole('button', { name: 'Glisser pour déplacer' })
      fireEvent.pointerDown(grips[0], { button: 0, clientY: 50 })
      fireEvent.pointerMove(window, { clientY: 160 }) // past R2's middle, not T0's
      fireEvent.pointerUp(window, { clientY: 160 })
      expect(titles()).toEqual(['R2', 'R1', 'T0'])
      await waitFor(() => expect(calls).toContainEqual({ method: 'POST', url: '/api/planning/render/1/place',
        body: { anchor_kind: 'render', anchor_id: 3, side: 'after' } })) // not « before T0 »: it would not move
      const again = screen.getAllByRole('button', { name: 'Glisser pour déplacer' })
      expect(again.every((g) => (g as HTMLButtonElement).disabled)).toBe(true) // the save is pending
      fireEvent.pointerDown(again[2], { button: 0, clientY: 250 })
      fireEvent.pointerMove(window, { clientY: 10 })
      fireEvent.pointerUp(window, { clientY: 10 })
      expect(titles()).toEqual(['R2', 'R1', 'T0']) // no second drag mid-save
      answer()
      await waitFor(() => expect((screen.getAllByRole('button', { name: 'Glisser pour déplacer' })[0] as HTMLButtonElement).disabled).toBe(false))
      expect(calls.filter((x) => x.url.endsWith('/place'))).toHaveLength(1)
    } finally {
      HTMLElement.prototype.getBoundingClientRect = rect
    }
  })

  it('« Lancer maintenant » on a card waiting for the machine says it skips the retry (200)', async () => {
    const calls = stubCalls([item({ title: 'T0', ids: { job_id: 2 }, line_index: 0, waits_on: 'machine', not_before: soon(15) })])
    show()
    fireEvent.click(await screen.findByRole('button', { name: 'Lancer maintenant' }))
    expect(await screen.findByText('Passe en tête de la file, sans attendre le nouvel essai de la machine.')).toBeTruthy()
    expect(calls).toContainEqual({ method: 'POST', url: '/api/planning/render/2/start-now', body: undefined })
  })

  describe('« Lancer » (196)', () => {
    type Launched = { front: unknown[]; requested: unknown[]; refused: unknown[]; left?: unknown[]; busy: string | null; paused: string | null }
    function stubLaunch(items: PlanningItem[], answer: Launched, pushed: unknown[] = []) {
      const calls: Call[] = []
      vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ method, url, body: init?.body ? JSON.parse(String(init.body)) : undefined })
        if (method === 'GET') return new Response(JSON.stringify({ now: soon(0), items }))
        return new Response(JSON.stringify(url.endsWith('/preview') ? { pushed } : answer))
      }))
      return calls
    }
    const cards = [
      item({ section: 'running', title: 'Le rendu actuel', ids: { asset_id: 17, job_id: 5 } }),
      item({ title: 'Rendu A', ids: { asset_id: 18, job_id: 6 } }),
      item({ kind: 'work_order', title: 'Ma commande', ids: { order_id: 4 } }),
      item({ kind: 'change_request', title: 'Vidéo 3', ids: { asset_id: 3 }, waits_on: 'next_ai_run' }),
      item({ kind: 'work_order', title: 'Sans consigne', ids: { order_id: 8 }, waits_on: 'needs_instruction' }),
      item({ section: 'planned', kind: 'agent_run', title: 'Analyse de la nuit', source: 'schedule', playbook: 'daily-learn' }),
      idea(),
    ]
    const launch = (calls: Call[]) => calls.find((c) => c.url === '/api/planning/launch')

    it('ticks some cards and launches the selection in on-screen order, then one toast', async () => {
      const calls = stubLaunch(cards, { front: [{ kind: 'render', id: 6 }], requested: [{ kind: 'work_order', id: 4 }],
        refused: [], busy: 'renders are waiting', paused: null })
      show()
      const boxes = await screen.findAllByRole('checkbox', { name: /^Sélectionner : / })
      expect(boxes.map((b) => b.getAttribute('aria-label'))).toEqual([ // not the running card, not the order without instruction
        'Sélectionner : Le mythe du jus détox', 'Sélectionner : Rendu A', 'Sélectionner : Ma commande',
        'Sélectionner : Vidéo 3', 'Sélectionner : Analyse de la nuit'])
      const bar = screen.getByRole('region', { name: 'Lancer' })
      expect(within(bar).getByRole('button', { name: 'Lancer la sélection (0)' })).toHaveProperty('disabled', true)
      fireEvent.click(screen.getByRole('checkbox', { name: 'Sélectionner : Ma commande' }))
      fireEvent.click(screen.getByRole('checkbox', { name: 'Sélectionner : Rendu A' }))
      fireEvent.click(within(bar).getByRole('button', { name: 'Lancer la sélection (2)' }))
      expect(await screen.findByText(/1 passe en tête de la file · 1 lancement demandé : démarre dès que la machine est libre/)).toBeTruthy()
      expect(screen.getByText(/un seul travail lourd à la fois/)).toBeTruthy()
      expect(calls).toContainEqual({ method: 'POST', url: '/api/planning/launch/preview',
        body: { items: [{ kind: 'render', id: 6 }, { kind: 'work_order', id: 4 }], bulk: true } })
      expect(launch(calls)?.body).toEqual({ items: [{ kind: 'render', id: 6 }, { kind: 'work_order', id: 4 }], bulk: true })
      await waitFor(() => expect(within(bar).getByRole('button', { name: 'Lancer la sélection (0)' })).toBeTruthy()) // cleared
    })

    it('the bar sits in the flow with its explanation until a card is ticked, then sticks without it (UI-003)', async () => {
      const calls = stubLaunch(cards, { front: [], requested: [], refused: [], busy: null, paused: null })
      show()
      const bar = await screen.findByRole('region', { name: 'Lancer' })
      const why = /^Un seul travail lourd à la fois/
      expect(bar.className).not.toMatch(/\bsticky\b/)
      expect(within(bar).getByText(why)).toBeTruthy()
      fireEvent.click(screen.getByRole('checkbox', { name: 'Sélectionner : Rendu A' }))
      expect(bar.className).toMatch(/\bsticky\b/)
      expect(within(bar).queryByText(why)).toBeNull()
      fireEvent.click(within(bar).getByRole('button', { name: 'Tout lancer' })) // works ticked too
      await waitFor(() => expect(launch(calls)).toBeTruthy())
      expect((launch(calls)!.body as { items: unknown[] }).items).toHaveLength(5)
    })

    it('« Tout lancer » sends every waiting card, after the delay warning', async () => {
      const calls = stubLaunch(cards, { front: [], requested: [], refused: [{ kind: 'agent_run', id: 'daily-learn', message: 'Le run daily-learn est déjà en cours.' }],
        busy: null, paused: '2026-11-23T10:00:00+00:00' }, [{ kind: 'render', title: 'Rendu B', by_s: 600 }])
      show()
      const all = await screen.findByRole('button', { name: 'Tout lancer' })
      fireEvent.click(all)
      expect(all).toHaveProperty('disabled', true) // from the first click (200)
      fireEvent.click(all)
      const warning = await screen.findByRole('alertdialog', { name: 'Ce que ça repousse' })
      expect(calls.filter((c) => c.url.endsWith('/preview'))).toHaveLength(1) // a double click asks once
      expect(all).toHaveProperty('disabled', true) // still, while the warning is open
      expect(launch(calls)).toBeUndefined() // nothing before the owner confirms
      fireEvent.click(within(warning).getByRole('button', { name: 'Confirmer' }))
      expect(await screen.findByText(/1 refusé \(Le run daily-learn est déjà en cours.\)\. Studio en pause/)).toBeTruthy()
      expect(launch(calls)?.body).toEqual({ items: [{ kind: 'claude_idea', id: 9 }, { kind: 'render', id: 6 },
        { kind: 'work_order', id: 4 }, { kind: 'change_request', id: 3 }, { kind: 'agent_run', id: 'daily-learn' }], bulk: true })
      expect(calls.filter((c) => c.url === '/api/planning/launch')).toHaveLength(1)
    })

    it('« Tout lancer » says which cards it left where they are, and why; cancelling frees the buttons (200)', async () => {
      stubLaunch(cards, { front: [{ kind: 'render', id: 6 }], requested: [], refused: [], busy: null, paused: null,
        left: [{ kind: 'render', id: 7, why: 'held' }, { kind: 'film', id: 2, why: 'timer' }, { kind: 'render', id: 8, why: 'machine' },
          { kind: 'render', id: 9, why: 'timer' }] }, [{ kind: 'render', title: 'Rendu B', by_s: 600 }])
      show()
      const all = await screen.findByRole('button', { name: 'Tout lancer' })
      fireEvent.click(all)
      fireEvent.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Annuler' }))
      await waitFor(() => expect(all).toHaveProperty('disabled', false))
      fireEvent.click(all)
      fireEvent.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Confirmer' }))
      expect(await screen.findByText(/1 passe en tête de la file · 4 laissés : en pause \/ minuteur \/ machine\./)).toBeTruthy()
    })

    it("an order's own button launches it alone; a launched one says it waits for the machine", async () => {
      const calls = stubLaunch([
        item({ kind: 'work_order', title: 'Ma commande', ids: { order_id: 4 } }),
        item({ kind: 'change_request', title: 'Déjà demandée', ids: { asset_id: 3 }, launch_requested: true }),
      ], { front: [], requested: [{ kind: 'work_order', id: 4 }], refused: [], busy: null, paused: null })
      show()
      expect(await screen.findByText('Lancement demandé — démarre dès que la machine est libre')).toBeTruthy()
      expect(screen.getAllByRole('button', { name: 'Lancer maintenant' })).toHaveLength(1) // not twice
      fireEvent.click(screen.getByRole('button', { name: 'Lancer maintenant' }))
      expect(await screen.findByText(/1 lancement demandé : démarre dans la minute/)).toBeTruthy()
      expect(calls.some((c) => c.url.endsWith('/preview'))).toBe(false) // an order pushes no render back
      expect(launch(calls)?.body).toEqual({ items: [{ kind: 'work_order', id: 4 }], bulk: false })
    })
  })
})
