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
    for (const text of ["Don't", 'Your taste', 'Fairly sure']) expect(taste.getByText(text)).toBeTruthy()
    expect(await taste.findByText('When Type d’accroche = Question')).toBeTruthy()
    expect(taste.getByText(/Your comment: “too slow”/)).toBeTruthy()
    expect(taste.getByRole('link', { name: 'the video' }).getAttribute('href')).toBe('/assets/7')
    expect(taste.getByText(/9 posts · \+23 % vs typical · the numbers disagree/)).toBeTruthy()
    expect(taste.getByText(/Conflict: audience learning says do/).className).toContain('text-warn')
    const audience = within(card('Questions win'))
    expect(audience.getByText('Contradicted by the numbers')).toBeTruthy()
    expect(audience.getByText(/too few posts to tell \(needs n ≥ 5\)/)).toBeTruthy()
    expect(audience.getByRole('button', { name: 'Reactivate' })).toBeTruthy()
    expect(taste.queryByRole('button', { name: 'Reactivate' })).toBeNull()
  })

  it('filters by kind, status, origin and confidence', async () => {
    const calls = stubApi()
    show()
    await screen.findByText('Questions win')
    fireEvent.click(within(screen.getByRole('group', { name: 'Kind' })).getByRole('button', { name: "Don't" }))
    fireEvent.click(within(screen.getByRole('group', { name: 'Status' })).getByRole('button', { name: 'Contradicted' }))
    fireEvent.click(within(screen.getByRole('group', { name: 'From' })).getByRole('button', { name: 'Audience' }))
    fireEvent.click(within(screen.getByRole('group', { name: 'Confidence' })).getByRole('button', { name: 'Sure' }))
    await waitFor(() => expect(calls.at(-1)?.url).toBe('/api/learnings?kind=dont&status=contradicted&origin=audience&confidence=high'))
    fireEvent.click(within(screen.getByRole('group', { name: 'Kind' })).getByRole('button', { name: "Don't" })) // off again
    await waitFor(() => expect(calls.at(-1)?.url).toBe('/api/learnings?status=contradicted&origin=audience&confidence=high'))
  })

  it('adds a rule with a predicate', async () => {
    const calls = stubApi()
    show()
    await screen.findByText('Questions win')
    fireEvent.click(screen.getAllByRole('button', { name: 'Add a rule' })[0])
    fireEvent.change(screen.getByRole('textbox', { name: 'The rule' }), { target: { value: 'Never use red' } })
    fireEvent.change(screen.getByRole('combobox', { name: 'Condition' }), { target: { value: 'hook_type' } })
    fireEvent.change(screen.getByRole('combobox', { name: 'Value' }), { target: { value: 'pov' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.url === '/api/learnings')).toBe(true))
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ statement: 'Never use red', kind: 'dont', predicate: { tag: 'hook_type', value: 'pov' } })
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Save' })).toBeNull())
  })

  it('edits a rule and can drop its predicate', async () => {
    const calls = stubApi()
    show()
    fireEvent.click(within(await waitFor(() => card('Slow starts lose me'))).getByRole('button', { name: 'Edit' }))
    expect(screen.getByText(/Saving makes it your rule/)).toBeTruthy()
    fireEvent.change(screen.getByRole('textbox', { name: 'The rule' }), { target: { value: 'Slow intros lose me' } })
    fireEvent.change(screen.getByRole('combobox', { name: 'Condition' }), { target: { value: '' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(calls.find((c) => c.method === 'PATCH')).toEqual({
      method: 'PATCH', url: '/api/learnings/1', body: { statement: 'Slow intros lose me', kind: 'dont', predicate: null } }))
  })

  it('confirms, retires and reactivates', async () => {
    const calls = stubApi()
    show()
    fireEvent.click(within(await waitFor(() => card('Slow starts lose me'))).getByRole('button', { name: 'Confirm' }))
    fireEvent.click(within(card('Slow starts lose me')).getByRole('button', { name: 'Retire' }))
    fireEvent.click(within(card('Questions win')).getByRole('button', { name: 'Reactivate' }))
    await waitFor(() => expect(calls.filter((c) => c.method === 'POST').map((c) => c.url)).toEqual([
      '/api/learnings/1/confirm', '/api/learnings/1/retire', '/api/learnings/2/reactivate']))
  })

  it('checks the numbers on demand', async () => {
    const calls = stubApi()
    show()
    await screen.findByText('Questions win')
    fireEvent.click(screen.getByRole('button', { name: 'Check the numbers' }))
    expect(await screen.findByText('Checked 2 rules against the numbers.')).toBeTruthy()
    expect(calls.some((c) => c.url === '/api/learnings/refresh')).toBe(true)
  })

  it('shows an empty state', async () => {
    stubApi([])
    show()
    expect(await screen.findByText('No learnings yet')).toBeTruthy()
    fireEvent.click(within(screen.getByRole('group', { name: 'Kind' })).getByRole('button', { name: 'Idea' }))
    expect(await screen.findByText('Nothing matches these filters.')).toBeTruthy()
  })
})
