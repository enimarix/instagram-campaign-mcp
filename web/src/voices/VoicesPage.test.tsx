import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Voice } from '../api/client'
import VoicesPage from './VoicesPage'

const voice = (id: string, label: string, over: Partial<Voice> = {}): Voice => ({
  id, label, description: null, use_for: null, styles: [], address: ['tu'], default: false, designed: true,
  enabled: true, sample_text: 'Arrête de compter tes pas.', sample: `/api/voices/${id}/sample`, ...over,
})

function stubApi(answers: Record<string, [number, unknown]>) {
  const calls: { key: string; body?: unknown }[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method ?? 'GET'} ${url}`
    calls.push({ key, body: init?.body ? JSON.parse(String(init.body)) : undefined })
    const [status, body] = answers[key] ?? [404, { error: 'not_found' }]
    return new Response(JSON.stringify(body), { status })
  }))
  return calls
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('VoicesPage', () => {
  it('lists each voice with its sample and turns one off', async () => {
    const calls = stubApi({
      'GET /api/voices': [200, [voice('souriante', 'Souriante', { default: true, use_for: 'Récits et explications' }), voice('old', 'Ancienne', { enabled: false })]],
      'PATCH /api/voices/old': [200, voice('old', 'Ancienne', { enabled: true })],
    })
    const { container } = render(<VoicesPage />)
    const sw = await screen.findByRole('switch', { name: 'Utiliser Ancienne pour les vidéos' })
    expect(container.querySelectorAll('audio')).toHaveLength(2)
    expect(screen.getByText('Secours')).toBeTruthy()
    expect(screen.getByText('Récits et explications')).toBeTruthy()
    expect(screen.getByText('1 voix active sur 2')).toBeTruthy()
    // the only voice on cannot be turned off
    expect((screen.getByRole('switch', { name: 'Utiliser Souriante pour les vidéos' }) as HTMLInputElement).disabled).toBe(true)
    fireEvent.click(sw)
    await waitFor(() => expect(calls.at(-1)).toEqual({ key: 'PATCH /api/voices/old', body: { enabled: true } }))
    expect(screen.getByText('2 voix actives sur 2')).toBeTruthy()
  })

  it('puts a refused switch back', async () => {
    stubApi({
      'GET /api/voices': [200, [voice('a', 'A'), voice('b', 'B')]],
      'PATCH /api/voices/a': [422, { error: 'invalid', message: 'at least one voice must stay on' }],
    })
    render(<VoicesPage />)
    const sw = await screen.findByRole('switch', { name: 'Utiliser A pour les vidéos' }) as HTMLInputElement
    fireEvent.click(sw)
    await waitFor(() => expect(sw.checked).toBe(true))
  })
})
