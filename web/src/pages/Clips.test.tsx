import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Clip, InboxFile } from '../api/client'
import ClipsSection from './Clips'

const FILE: InboxFile = { name: 'my clip.mp4', size_bytes: 1000, modified_at: '2026-11-17T08:00:00+00:00' }
const CLIP: Clip = {
  id: 5, provider: 'local_inbox', url: 'https://x.org/v', author: 'Ann', rights_basis: 'cc',
  rights_note: 'Wikimedia', audio_rights: 'no_audio', stats: { original_name: 'old.mp4' },
  licence: 'CC BY 4.0', attribution: 'Ann, https://x.org/v, CC BY 4.0',
}
const POST = 'POST /api/sources/inbox/my%20clip.mp4'

function stubApi(overrides: Record<string, [number, unknown]> = {}) {
  const calls: { key: string; body?: unknown }[] = []
  let added = false
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method ?? 'GET'} ${url}`
    calls.push({ key, body: init?.body ? JSON.parse(init.body as string) : undefined })
    const routes: Record<string, [number, unknown]> = {
      'GET /api/sources/inbox': [200, added ? [] : [FILE]],
      'GET /api/sources?role=clip': [200, added ? [CLIP, { ...CLIP, id: 6 }] : [CLIP]],
      [POST]: [200, { ...CLIP, id: 6 }],
      ...overrides,
    }
    const [status, body] = routes[key] ?? [404, { error: 'not_found' }]
    if (key === POST && status === 200) added = true
    return new Response(JSON.stringify(body), { status })
  }))
  return calls
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

const input = (form: HTMLElement, name: string) =>
  within(form).getByRole('textbox', { name: new RegExp(`^${name}`) }) as HTMLInputElement

describe('ClipsSection', () => {
  it('lists clips with their basis and credit', async () => {
    stubApi()
    render(<ClipsSection />)
    expect(await screen.findByText('Ann, https://x.org/v, CC BY 4.0', { exact: false })).toBeTruthy()
    expect(screen.getByText('#5 old.mp4')).toBeTruthy()
  })

  it('lists the first 5 clips, then Show all', async () => {
    const many = Array.from({ length: 7 }, (_, i) => ({ ...CLIP, id: i + 1, stats: { original_name: `c${i + 1}.mp4` } }))
    stubApi({ 'GET /api/sources?role=clip': [200, many] })
    render(<ClipsSection />)
    expect(await screen.findByText('#5 c5.mp4')).toBeTruthy()
    expect(screen.queryByText('#6 c6.mp4')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Voir les 7 clips' }))
    expect(screen.getByText('#7 c7.mp4')).toBeTruthy()
    expect(screen.queryByRole('button', { name: /Voir les/ })).toBeNull()
  })

  it('requires the note and the sound answer, never offers unknown, and asks author + licence for cc', async () => {
    stubApi()
    render(<ClipsSection />)
    const form = await screen.findByRole('form', { name: 'Ajouter my clip.mp4' })
    const options = within(form).getAllByRole('option').map((o) => (o as HTMLOptionElement).value)
    expect(options).not.toContain('unknown')
    expect(input(form, 'Note sur les droits').required).toBe(true)
    expect(input(form, 'Auteur').required).toBe(false)
    expect(within(form).queryByRole('textbox', { name: /^Licence/ })).toBeNull()
    const radios = within(form).getAllByRole('radio') as HTMLInputElement[]
    expect(radios.map((r) => r.value)).toEqual(['covered', 'not_covered', 'no_audio'])
    expect(radios.every((r) => r.required)).toBe(true)
    expect(within(form).getByRole('group', { name: 'Le son est-il couvert ?' })).toBeTruthy()

    fireEvent.change(within(form).getByRole('combobox', { name: 'Base des droits' }), { target: { value: 'cc' } })
    expect(input(form, 'Auteur').required).toBe(true)
    expect(input(form, 'Licence').required).toBe(true)
  })

  it('sends the rights and reloads the lists', async () => {
    const calls = stubApi()
    render(<ClipsSection />)
    const form = await screen.findByRole('form', { name: 'Ajouter my clip.mp4' })
    fireEvent.change(within(form).getByRole('combobox', { name: 'Base des droits' }), { target: { value: 'permission' } })
    fireEvent.change(input(form, 'Note sur les droits'), { target: { value: ' DM on 2026-11-10 ' } })
    fireEvent.change(input(form, 'Auteur'), { target: { value: 'bob' } })
    fireEvent.click(within(form).getByRole('radio', { name: /^Non/ }))
    fireEvent.submit(form)
    expect(await screen.findByText('Aucun fichier en attente.')).toBeTruthy()
    expect(calls.find((c) => c.key === POST)?.body).toEqual({
      rights_basis: 'permission', rights_note: 'DM on 2026-11-10', audio_rights: 'not_covered',
      author: 'bob', url: null, licence: null,
    })
    expect(screen.getByText('#6 old.mp4')).toBeTruthy()
  })

  it("shows the server's refusal", async () => {
    stubApi({ [POST]: [422, { error: 'invalid', message: 'the clip has sound: say whether the sound is covered' }] })
    render(<ClipsSection />)
    const form = await screen.findByRole('form', { name: 'Ajouter my clip.mp4' })
    fireEvent.change(input(form, 'Note sur les droits'), { target: { value: 'mine' } })
    fireEvent.click(within(form).getByRole('radio', { name: /pas de son/ }))
    fireEvent.submit(form)
    expect((await within(form).findByRole('alert')).textContent).toMatch(/has sound/)
    expect((within(form).getByRole('button', { name: 'Ajouter le clip' }) as HTMLButtonElement).disabled).toBe(false)
  })
})
