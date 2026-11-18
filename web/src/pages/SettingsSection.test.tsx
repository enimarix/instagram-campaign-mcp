import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { EditableSettings, SettingField } from '../api/client'
import SettingsSection from './SettingsSection'

const f = (over: Partial<SettingField> & Pick<SettingField, 'name'>): SettingField => ({
  section: 'ads', value: '10', default: '10', overridden: false, type: 'money', ge: 0, description: null, ...over,
})
const SETTINGS: EditableSettings = {
  version: 1,
  fields: [
    f({ name: 'ads_daily_cap', description: 'Most spend per owner-local day' }),
    f({ name: 'ads_objective', type: 'choice', value: 'OUTCOME_AWARENESS', choices: ['OUTCOME_AWARENESS', 'OUTCOME_ENGAGEMENT'] }),
    f({ name: 'ads_dsa_payor', type: 'text', value: 'Macrobody', default: null, overridden: true, max_length: 512 }),
    f({ name: 'batch_size', section: 'studio', type: 'int', value: 10, ge: 1 }),
    f({ name: 'humour_share', section: 'studio', type: 'float', value: 0.7, default: 0.5, overridden: true, le: 1 }),
  ],
}
const saved = (name: string, value: string): EditableSettings =>
  ({ ...SETTINGS, fields: SETTINGS.fields.map((x) => (x.name === name ? { ...x, value, overridden: true } : x)) })

type Reply = [number, unknown]
/** `patches`: answers to successive PATCH calls; their bodies are returned. */
function stubApi(patches: Reply[]) {
  const bodies: unknown[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method ?? 'GET'} ${url}`
    let reply: Reply = [404, { error: 'not_found' }]
    if (key === 'GET /api/settings') reply = [200, SETTINGS]
    if (key === 'GET /api/ads/presets') reply = [200, { presets: [{ id: 'fr', label: 'France, Reels', varies: [] }] }]
    if (key === 'PATCH /api/settings') {
      bodies.push(JSON.parse(String(init?.body)))
      reply = patches.shift() ?? reply
    }
    return new Response(JSON.stringify(reply[1]), { status: reply[0] })
  }))
  return bodies
}

beforeEach(() => {
  HTMLDialogElement.prototype.showModal = function () { this.open = true }
  HTMLDialogElement.prototype.close = function () { this.open = false; this.dispatchEvent(new Event('close')) }
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

const input = (label: string) => screen.getByLabelText(label) as HTMLInputElement

describe('SettingsSection', () => {
  it('edits and saves only what changed, in its own section', async () => {
    const bodies = stubApi([[200, saved('ads_objective', 'OUTCOME_ENGAGEMENT')]])
    render(<SettingsSection section="ads" title="Ads" />)
    const ads = await screen.findByRole('region', { name: 'Ads' })
    expect(screen.queryByLabelText('Batch size')).toBeNull()
    expect(within(ads).getByText('Most spend per owner-local day')).toBeTruthy()
    expect(await within(ads).findByText(/France, Reels/)).toBeTruthy()
    expect((within(ads).getByRole('button', { name: 'Save' }) as HTMLButtonElement).disabled).toBe(true)
    fireEvent.change(input('Ads objective'), { target: { value: 'OUTCOME_ENGAGEMENT' } })
    fireEvent.click(within(ads).getByRole('button', { name: 'Save' }))
    await vi.waitFor(() => expect(within(ads).getAllByText('set here')).toHaveLength(2))
    expect(bodies).toEqual([{ values: { ads_objective: 'OUTCOME_ENGAGEMENT' } }])
    expect(screen.queryByRole('dialog')).toBeNull() // no password for this
  })

  it('asks the password only when the server says a cap rises', async () => {
    const bodies = stubApi([[400, { error: 'password_required' }], [403, { error: 'bad_password' }],
      [200, saved('ads_daily_cap', '20')]])
    render(<SettingsSection section="ads" title="Ads" />)
    await screen.findByLabelText('Ads daily cap')
    fireEvent.change(input('Ads daily cap'), { target: { value: '20' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    const dialog = await screen.findByRole('dialog', { name: 'Raise a money cap' })
    fireEvent.change(within(dialog).getByLabelText('Password'), { target: { value: 'nope' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save' }))
    expect((await within(dialog).findByRole('alert')).textContent).toBe('Wrong password.')
    fireEvent.change(within(dialog).getByLabelText('Password'), { target: { value: 'right' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save' }))
    await vi.waitFor(() => expect(screen.getAllByText('set here')).toHaveLength(2))
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(bodies).toEqual([
      { values: { ads_daily_cap: '20' } },
      { values: { ads_daily_cap: '20' }, password: 'nope' },
      { values: { ads_daily_cap: '20' }, password: 'right' },
    ])
  })

  it('shows the validator message and resets a field to its default', async () => {
    const bodies = stubApi([
      [422, { error: 'invalid', field: 'ads_daily_cap', message: 'ads_daily_cap: Value error, too big' }],
      [200, { ...SETTINGS, fields: SETTINGS.fields.map((x) => ({ ...x, overridden: false })) }],
    ])
    render(<SettingsSection section="ads" title="Ads" />)
    await screen.findByLabelText('Ads daily cap')
    fireEvent.change(input('Ads daily cap'), { target: { value: '500' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect((await screen.findByRole('alert')).textContent).toBe('Ads daily cap: Value error, too big')
    fireEvent.click(screen.getByRole('button', { name: 'Reset Ads dsa payor to default' }))
    await vi.waitFor(() => expect(screen.queryByText('set here')).toBeNull())
    expect(bodies[1]).toEqual({ reset: ['ads_dsa_payor'] })
  })

  it('studio: plain labels, shares in %, saved without a password, reset and error', async () => {
    const bodies = stubApi([
      [200, saved('humour_share', '0.35')],
      [422, { error: 'invalid', field: 'batch_size', message: 'batch_size: Value error, below BATCH_FLOOR' }],
      [200, { ...SETTINGS, fields: SETTINGS.fields.map((x) => ({ ...x, overridden: false, value: x.default })) }],
    ])
    render(<SettingsSection section="studio" title="Studio" />)
    const studio = await screen.findByRole('region', { name: 'Studio' })
    expect(within(studio).queryByText(/money cap/)).toBeNull()
    expect(screen.queryByLabelText('Ads daily cap')).toBeNull()
    expect(input('Videos made per day').value).toBe('10')
    expect(input('Share of funny videos (%)').value).toBe('70')
    fireEvent.change(input('Share of funny videos (%)'), { target: { value: '35' } })
    fireEvent.click(within(studio).getByRole('button', { name: 'Save' }))
    await vi.waitFor(() => expect(within(studio).getByRole('button', { name: 'Save' }).getAttribute('aria-busy')).toBeNull())
    expect(input('Share of funny videos (%)').value).toBe('35')
    expect(screen.queryByRole('dialog')).toBeNull()
    fireEvent.change(input('Videos made per day'), { target: { value: '2' } })
    fireEvent.click(within(studio).getByRole('button', { name: 'Save' }))
    expect((await screen.findByRole('alert')).textContent).toBe('Videos made per day: Value error, below BATCH_FLOOR')
    fireEvent.click(screen.getByRole('button', { name: 'Reset Share of funny videos to default' }))
    await vi.waitFor(() => expect(input('Share of funny videos (%)').value).toBe('50'))
    expect(bodies).toEqual([{ values: { humour_share: '0.35' } }, { values: { batch_size: '2' } }, { reset: ['humour_share'] }])
  })
})
