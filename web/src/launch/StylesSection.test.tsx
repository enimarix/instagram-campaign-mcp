import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Style } from '../api/client'
import StylesSection from './StylesSection'

const style = (id: string, label: string, over: Partial<Style> = {}): Style => ({
  id, label, description: null, templates: [], end_card: null, address: null, enabled: true, share: null,
  preview: { still: null, clip: null }, ...over,
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

describe('Settings: Styles (138)', () => {
  it('turns a style off and sets, then clears, a daily share', async () => {
    const calls = stubApi({
      'GET /api/styles': [200, [style('voxel', '3D 8-bit', { share: 0.3 }), style('paper', 'Papier')]],
      'PATCH /api/styles/paper': [200, style('paper', 'Papier', { enabled: false })],
      'PATCH /api/styles/voxel': [200, style('voxel', '3D 8-bit', { share: 0.5 })],
    })
    render(<StylesSection />)
    const section = await screen.findByRole('region', { name: 'Styles' })
    const paper = await within(section).findByRole('checkbox', { name: 'Papier' }) as HTMLInputElement
    expect(paper.checked).toBe(true)
    fireEvent.click(paper)
    expect(await within(section).findByRole('checkbox', { name: 'Papier', checked: false })).toBeTruthy()
    const share = within(section).getByLabelText('Part par jour de 3D 8-bit (%)') as HTMLInputElement
    expect(share.value).toBe('30')
    fireEvent.blur(share, { target: { value: '30' } }) // unchanged: nothing sent
    fireEvent.blur(share, { target: { value: '50' } })
    expect(await within(section).findByDisplayValue('50')).toBeTruthy()
    expect(calls.filter((c) => c.key.startsWith('PATCH')).map((c) => [c.key, c.body])).toEqual([
      ['PATCH /api/styles/paper', { enabled: false }], ['PATCH /api/styles/voxel', { share: 0.5 }]])
  })

  it('shows the refusal', async () => {
    stubApi({
      'GET /api/styles': [200, [style('voxel', '3D 8-bit')]],
      'PATCH /api/styles/voxel': [422, { error: 'invalid', message: 'share must be above 0 and at most 1 (or empty: no limit)' }],
    })
    render(<StylesSection />)
    const share = await screen.findByLabelText('Part par jour de 3D 8-bit (%)')
    fireEvent.blur(share, { target: { value: '150' } })
    expect((await screen.findByRole('alert')).textContent).toContain('share must be')
  })
})
