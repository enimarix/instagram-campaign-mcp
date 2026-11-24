import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Voice } from '../api/client'
import VoicesPage from './VoicesPage'
import { Preview } from './Preview'

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

  it('switches the engine priority and the ElevenLabs model, and shows the credits', async () => {
    const calls = stubApi({
      'GET /api/voices': [200, [voice('souriante', 'Souriante')]],
      'GET /api/voices/engine': [200, {
        priority: 'elevenlabs', model: 'eleven_v4', local: true,
        elevenlabs: { configured: true, credits: { used: 9626, limit: 10000, left: 374, resets_at: null, tier: 'free' }, error: null },
      }],
      'GET /api/voices/elevenlabs/models': [200, [
        { id: 'eleven_v4', name: 'Eleven v4', description: '', languages: ['fr'], cost: 1 },
        { id: 'eleven_flash_v2_5', name: 'Flash v2.5', description: '', languages: ['fr'], cost: 0.5 },
      ]],
      'PATCH /api/voices/engine': [200, { priority: 'local', model: 'eleven_v4' }],
    })
    render(<VoicesPage />)
    expect(await screen.findByText(/374 restants sur 10/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: "Voix locale d'abord" }))
    await waitFor(() => expect(calls.at(-1)).toEqual({ key: 'PATCH /api/voices/engine', body: { priority: 'local' } }))
    const model = await screen.findByRole('combobox', { name: 'Modèle ElevenLabs' }) as HTMLSelectElement
    await waitFor(() => expect(model.options).toHaveLength(2))
    expect(screen.getByText(/joue les balises d'émotion/)).toBeTruthy()
    fireEvent.change(model, { target: { value: 'eleven_flash_v2_5' } })
    await waitFor(() => expect(calls.at(-1)).toEqual({ key: 'PATCH /api/voices/engine', body: { model: 'eleven_flash_v2_5' } }))
    expect(screen.getByText(/ne joue pas les balises/)).toBeTruthy()
  })

  it('finds a library voice by filters and adds it as a card with its local relay', async () => {
    const lib = (q: string) => `GET /api/voices/elevenlabs/search?${q}`
    const hugo = { voice_id: 'lib1', public_owner_id: 'own1', name: 'Hugo - Coach', description: 'Coach énergique', gender: 'male', age: 'young',
      accent: 'parisian', language: 'fr', use_case: 'social_media', descriptive: 'upbeat', category: 'professional', preview_url: 'https://x/p.mp3', free_users_allowed: true }
    const calls = stubApi({
      'GET /api/voices': [200, [voice('souriante', 'Souriante', { gender: 'female' }), voice('energique_homme', 'Énergique (homme)', { gender: 'male' })]],
      'GET /api/voices/engine': [200, { priority: 'elevenlabs', model: 'eleven_v4', local: true, elevenlabs: { configured: true, credits: null, error: null } }],
      'GET /api/voices/elevenlabs/models': [200, []],
      [lib('source=library&language=fr&sort=trending')]: [200, { voices: [], next: null, total: 0 }],
      [lib('source=library&language=fr&sort=trending&gender=male')]: [200, { voices: [hugo], next: null, total: 1 }],
      'POST /api/voices/elevenlabs': [200, voice('el_hugo', 'Hugo', { engine: 'elevenlabs' })],
    })
    HTMLDialogElement.prototype.showModal = function () { this.open = true }
    render(<VoicesPage />)
    fireEvent.click(await screen.findByRole('button', { name: 'Ajouter une voix ElevenLabs' }))
    expect(await screen.findByText('Aucune voix avec ces filtres.')).toBeTruthy()
    fireEvent.change(screen.getByRole('combobox', { name: 'Genre' }), { target: { value: 'male' } })
    fireEvent.click(await screen.findByRole('button', { name: 'Choisir' }))
    expect((screen.getByRole('combobox', { name: 'Voix locale de relais' }) as HTMLSelectElement).value).toBe('energique_homme')
    fireEvent.click(screen.getByRole('button', { name: 'Ajouter la carte' }))
    await waitFor(() => expect(calls.find((c) => c.key === 'POST /api/voices/elevenlabs')?.body).toMatchObject({
      voice_id: 'lib1', public_owner_id: 'own1', label: 'Hugo', fallback: 'energique_homme', gender: 'male', address: ['tu', 'vous'] }))
    await waitFor(() => expect(calls.filter((c) => c.key === 'GET /api/voices')).toHaveLength(2)) // the list comes back with the card
  })

  it('never asks for the key when the engine status only failed to load', async () => {
    stubApi({ 'GET /api/voices': [200, [voice('souriante', 'Souriante')]] }) // engine: 404
    render(<VoicesPage />)
    expect(await screen.findByText(/Moteurs indisponibles/)).toBeTruthy()
    expect(screen.getByText(/rechargez la page/)).toBeTruthy()
    expect(screen.queryByText(/ELEVENLABS_API_KEY/)).toBeNull()
  })

  it('says when a preview cannot load instead of a silent player', () => {
    const { container } = render(<Preview eager src="https://x/p.mp3" label="Écouter Hugo" />)
    const audio = container.querySelector('audio') as HTMLAudioElement
    expect(audio.preload).toBe('metadata')
    fireEvent.error(audio)
    expect(screen.getByRole('alert').textContent).toMatch(/Rechargez la page/)
  })
})
