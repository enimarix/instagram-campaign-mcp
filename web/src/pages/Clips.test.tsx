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

  it('requires the note and the sound answer, never offers unknown, and asks author + licence for cc', async () => {
    stubApi()
    render(<ClipsSection />)
    const form = await screen.findByRole('form', { name: 'Add my clip.mp4' })
    const options = within(form).getAllByRole('option').map((o) => (o as HTMLOptionElement).value)
    expect(options).not.toContain('unknown')
    expect(input(form, 'Rights note').required).toBe(true)
    expect(input(form, 'Author').required).toBe(false)
    expect(within(form).queryByRole('textbox', { name: /^Licence/ })).toBeNull()
    const radios = within(form).getAllByRole('radio') as HTMLInputElement[]
    expect(radios.map((r) => r.value)).toEqual(['covered', 'not_covered', 'no_audio'])
    expect(radios.every((r) => r.required)).toBe(true)
    expect(within(form).getByRole('group', { name: 'Is the sound covered?' })).toBeTruthy()

    fireEvent.change(within(form).getByRole('combobox', { name: 'Rights basis' }), { target: { value: 'cc' } })
    expect(input(form, 'Author').required).toBe(true)
    expect(input(form, 'Licence').required).toBe(true)
  })

  it('sends the rights and reloads the lists', async () => {
    const calls = stubApi()
    render(<ClipsSection />)
    const form = await screen.findByRole('form', { name: 'Add my clip.mp4' })
    fireEvent.change(within(form).getByRole('combobox', { name: 'Rights basis' }), { target: { value: 'permission' } })
    fireEvent.change(input(form, 'Rights note'), { target: { value: ' DM on 2026-11-10 ' } })
    fireEvent.change(input(form, 'Author'), { target: { value: 'bob' } })
    fireEvent.click(within(form).getByRole('radio', { name: /^No/ }))
    fireEvent.submit(form)
    expect(await screen.findByText('No files waiting.')).toBeTruthy()
    expect(calls.find((c) => c.key === POST)?.body).toEqual({
      rights_basis: 'permission', rights_note: 'DM on 2026-11-10', audio_rights: 'not_covered',
      author: 'bob', url: null, licence: null,
    })
    expect(screen.getByText('#6 old.mp4')).toBeTruthy()
  })

  it("shows the server's refusal", async () => {
    stubApi({ [POST]: [422, { error: 'invalid', message: 'the clip has sound: say whether the sound is covered' }] })
    render(<ClipsSection />)
    const form = await screen.findByRole('form', { name: 'Add my clip.mp4' })
    fireEvent.change(input(form, 'Rights note'), { target: { value: 'mine' } })
    fireEvent.click(within(form).getByRole('radio', { name: /no sound/ }))
    fireEvent.submit(form)
    expect((await within(form).findByRole('alert')).textContent).toMatch(/has sound/)
    expect((within(form).getByRole('button', { name: 'Add clip' }) as HTMLButtonElement).disabled).toBe(false)
  })
})
