import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Learning } from '../api/client'
import { ToastProvider } from '../ui/Toast'
import Learnings from './Learnings'

const row = (l: Partial<Learning>): Learning => ({
  id: 1, statement: '', kind: 'do', origin: 'taste', confidence: 'low', status: 'active', scope: {}, evidence: [],
  created_at: '', updated_at: '', ...l,
})
const TASTE = row({
  id: 1, statement: 'Slow starts lose me', kind: 'dont', confidence: 'medium', scope: { tag: 'hook_type', value: 'question' },
  evidence: [
    { feedback_id: 4, text: 'too slow', asset_id: 7, thumbnail_url: '/api/media/7/thumb.jpg' },
    { kind: 'audience_index', n: 9, index: 1.23, verdict: 'contradicts' },
    { kind: 'conflict', with: 2, detail: 'audience learning says do' },
  ],
})
const AUDIENCE = row({ id: 2, statement: 'Questions win', origin: 'audience', confidence: 'high', status: 'contradicted',
  evidence: [{ kind: 'audience_index', n: 2, index: null, verdict: 'needs_n', note: 'needs n ≥ 5' }] })
const TAXONOMY = { feedback_reasons: { values: [] }, hook_types: { values: [{ id: 'question', label: 'Question' }, { id: 'pov', label: 'POV' }] } }

type Call = { method: string; url: string; body: unknown }
function stubApi(list: Learning[] = [TASTE, AUDIENCE]) {
  const calls: Call[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET'
    const body = init?.body ? JSON.parse(String(init.body)) : undefined
    calls.push({ method, url, body })
    if (url === '/api/taxonomy') return new Response(JSON.stringify(TAXONOMY))
    if (method === 'GET') return new Response(JSON.stringify(list))
    if (url === '/api/learnings/refresh') return new Response(JSON.stringify({ evaluated: 2, contradicted: [], conflicts: [] }))
    return new Response(JSON.stringify(row({ ...body })))
  }))
  return calls
}
const show = () => render(<MemoryRouter><ToastProvider><Learnings /></ToastProvider></MemoryRouter>)
const card = (statement: string) => screen.getByText(statement).closest('li') as HTMLElement

// jsdom has no modal dialogs
HTMLDialogElement.prototype.showModal = function () { this.open = true }
HTMLDialogElement.prototype.close = function () {
  this.open = false
  this.dispatchEvent(new Event('close'))
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('Learnings', () => {
  it('shows cards with badges, the predicate in words and the evidence', async () => {
    stubApi()
    show()
    const taste = within(await waitFor(() => card('Slow starts lose me')))
    for (const text of ['À éviter', 'Ton goût', 'Assez sûre']) expect(taste.getByText(text)).toBeTruthy()
    expect(await taste.findByText('Quand Type d’accroche = Question')).toBeTruthy()
    expect(taste.getByText(/Ton commentaire : « too slow »/)).toBeTruthy()
    expect(taste.getByRole('link', { name: 'la vidéo' }).getAttribute('href')).toBe('/assets/7')
    expect(taste.getByText(/Public : 9 publications · \+23 % vs la normale · les chiffres disent le contraire/)).toBeTruthy()
    expect(taste.getByText(/Conflit : audience learning says do/).className).toContain('text-warn')
    const audience = within(card('Questions win'))
    expect(audience.getByText('Contredite par les chiffres')).toBeTruthy()
    expect(audience.getByText(/Public : 2 publications · trop peu de publications pour le dire \(needs n ≥ 5\)/)).toBeTruthy()
    expect(audience.getByRole('button', { name: 'Réactiver' })).toBeTruthy()
    expect(taste.queryByRole('button', { name: 'Réactiver' })).toBeNull()
  })

  it('filters by kind, status, origin and confidence', async () => {
    const calls = stubApi()
    show()
    await screen.findByText('Questions win')
    fireEvent.click(within(screen.getByRole('group', { name: 'Type' })).getByRole('button', { name: 'À éviter' }))
    fireEvent.click(within(screen.getByRole('group', { name: 'Statut' })).getByRole('button', { name: 'Contredite' }))
    fireEvent.click(within(screen.getByRole('group', { name: 'Origine' })).getByRole('button', { name: 'Public' }))
    fireEvent.click(within(screen.getByRole('group', { name: 'Confiance' })).getByRole('button', { name: 'Sûre' }))
    await waitFor(() => expect(calls.at(-1)?.url).toBe('/api/learnings?kind=dont&status=contradicted&origin=audience&confidence=high'))
    fireEvent.click(within(screen.getByRole('group', { name: 'Type' })).getByRole('button', { name: 'À éviter' })) // off again
    await waitFor(() => expect(calls.at(-1)?.url).toBe('/api/learnings?status=contradicted&origin=audience&confidence=high'))
  })

  it('adds a rule with a predicate', async () => {
    const calls = stubApi()
    show()
    await screen.findByText('Questions win')
    fireEvent.click(screen.getAllByRole('button', { name: 'Ajouter une règle' })[0])
    fireEvent.change(screen.getByRole('textbox', { name: 'La règle' }), { target: { value: 'Never use red' } })
    fireEvent.change(screen.getByRole('combobox', { name: 'Condition' }), { target: { value: 'hook_type' } })
    fireEvent.change(screen.getByRole('combobox', { name: 'Valeur' }), { target: { value: 'pov' } })
    fireEvent.click(screen.getByRole('button', { name: 'Enregistrer' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.url === '/api/learnings')).toBe(true))
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ statement: 'Never use red', kind: 'dont', predicate: { tag: 'hook_type', value: 'pov' } })
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Enregistrer' })).toBeNull())
  })

  it('edits a rule and can drop its predicate', async () => {
    const calls = stubApi()
    show()
    fireEvent.click(within(await waitFor(() => card('Slow starts lose me'))).getByRole('button', { name: 'Modifier' }))
    expect(screen.getByText(/L’enregistrer en fait ta règle/)).toBeTruthy()
    fireEvent.change(screen.getByRole('textbox', { name: 'La règle' }), { target: { value: 'Slow intros lose me' } })
    fireEvent.change(screen.getByRole('combobox', { name: 'Condition' }), { target: { value: '' } })
    fireEvent.click(screen.getByRole('button', { name: 'Enregistrer' }))
    await waitFor(() => expect(calls.find((c) => c.method === 'PATCH')).toEqual({
      method: 'PATCH', url: '/api/learnings/1', body: { statement: 'Slow intros lose me', kind: 'dont', predicate: null } }))
  })

  it('confirms, retires and reactivates', async () => {
    const calls = stubApi()
    show()
    fireEvent.click(within(await waitFor(() => card('Slow starts lose me'))).getByRole('button', { name: 'Confirmer' }))
    fireEvent.click(within(card('Slow starts lose me')).getByRole('button', { name: 'Retirer' }))
    fireEvent.click(within(card('Questions win')).getByRole('button', { name: 'Réactiver' }))
    await waitFor(() => expect(calls.filter((c) => c.method === 'POST').map((c) => c.url)).toEqual([
      '/api/learnings/1/confirm', '/api/learnings/1/retire', '/api/learnings/2/reactivate']))
  })

  it('checks the numbers on demand', async () => {
    const calls = stubApi()
    show()
    await screen.findByText('Questions win')
    fireEvent.click(screen.getByRole('button', { name: 'Vérifier les chiffres' }))
    expect(await screen.findByText('2 règles vérifiées avec les chiffres.')).toBeTruthy()
    expect(calls.some((c) => c.url === '/api/learnings/refresh')).toBe(true)
  })

  it('shows an empty state', async () => {
    stubApi([])
    show()
    expect(await screen.findByText('Pas encore d’apprentissages')).toBeTruthy()
    fireEvent.click(within(screen.getByRole('group', { name: 'Type' })).getByRole('button', { name: 'Idée' }))
    expect(await screen.findByText('Rien ne correspond à ces filtres.')).toBeTruthy()
  })
})
