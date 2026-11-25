import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AdPresetValue, EditableSettings, SettingField } from '../api/client'
import SettingsSection from './SettingsSection'

const f = (over: Partial<SettingField> & Pick<SettingField, 'name'>): SettingField => ({
  section: 'ads', value: '10', default: '10', overridden: false, type: 'money', ge: 0, description: null, ...over,
})
const FR: AdPresetValue = { id: 'fr_reels', label: 'France, Reels', countries: ['FR'], age_min: 18, age_max: null, placements: ['reels'] }
const BE: AdPresetValue = { ...FR, id: 'be_feed', label: 'Belgium, Feed', countries: ['BE'], placements: ['stream'] }
const SETTINGS: EditableSettings = {
  version: 1,
  fields: [
    f({ name: 'ads_presets', type: 'presets', value: [FR, BE], default: [FR, BE], ge: undefined }),
    f({ name: 'ads_daily_cap', description: 'Most spend per owner-local day' }),
    f({ name: 'ads_objective', type: 'choice', value: 'OUTCOME_AWARENESS', choices: ['OUTCOME_AWARENESS', 'OUTCOME_ENGAGEMENT'] }),
    f({ name: 'ads_dsa_payor', type: 'text', value: 'Macrobody', default: null, overridden: true, max_length: 512 }),
    f({ name: 'batch_size', section: 'studio', type: 'int', value: 10, ge: 1, le: 50 }),
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

const input = (label: string, i?: number) =>
  (i === undefined ? screen.getByLabelText(label) : screen.getAllByLabelText(label)[i]) as HTMLInputElement

describe('SettingsSection', () => {
  it('edits and saves only what changed, in its own section', async () => {
    const bodies = stubApi([[200, saved('ads_objective', 'OUTCOME_ENGAGEMENT')]])
    render(<SettingsSection section="ads" title="Pubs" />)
    const ads = await screen.findByRole('region', { name: 'Pubs' })
    expect(screen.queryByLabelText('Vidéos faites par jour')).toBeNull()
    // French label and help, never the config.py description
    expect(within(ads).queryByText('Most spend per owner-local day')).toBeNull()
    expect(within(ads).getByText(/^Dépense maximale sur une journée/)).toBeTruthy()
    expect(await within(ads).findByDisplayValue('France, Reels')).toBeTruthy()
    expect(within(ads).getAllByRole('option').map((o) => o.textContent)).toEqual(['Notoriété', 'Interactions'])
    expect((within(ads).getByRole('button', { name: 'Enregistrer' }) as HTMLButtonElement).disabled).toBe(true)
    fireEvent.change(input('Objectif des pubs'), { target: { value: 'OUTCOME_ENGAGEMENT' } })
    fireEvent.click(within(ads).getByRole('button', { name: 'Enregistrer' }))
    await vi.waitFor(() => expect(within(ads).getAllByText('réglé ici')).toHaveLength(2))
    expect(bodies).toEqual([{ values: { ads_objective: 'OUTCOME_ENGAGEMENT' } }])
    expect(screen.queryByRole('dialog')).toBeNull() // no password for this
  })

  it('asks the password only when the server says a cap rises', async () => {
    const bodies = stubApi([[400, { error: 'password_required' }], [403, { error: 'bad_password' }],
      [200, saved('ads_daily_cap', '20')]])
    render(<SettingsSection section="ads" title="Pubs" />)
    await screen.findByLabelText('Plafond par jour')
    fireEvent.change(input('Plafond par jour'), { target: { value: '20' } })
    fireEvent.click(screen.getByRole('button', { name: 'Enregistrer' }))
    const dialog = await screen.findByRole('dialog', { name: 'Monter un plafond d’argent' })
    fireEvent.change(within(dialog).getByLabelText('Mot de passe'), { target: { value: 'nope' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Enregistrer' }))
    expect((await within(dialog).findByRole('alert')).textContent).toBe('Mauvais mot de passe.')
    fireEvent.change(within(dialog).getByLabelText('Mot de passe'), { target: { value: 'right' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Enregistrer' }))
    await vi.waitFor(() => expect(screen.getAllByText('réglé ici')).toHaveLength(2))
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
    render(<SettingsSection section="ads" title="Pubs" />)
    await screen.findByLabelText('Plafond par jour')
    fireEvent.change(input('Plafond par jour'), { target: { value: '500' } })
    fireEvent.click(screen.getByRole('button', { name: 'Enregistrer' }))
    expect((await screen.findByRole('alert')).textContent).toBe('Plafond par jour : Value error, too big')
    fireEvent.click(screen.getByRole('button', { name: 'Remettre Payeur (DSA) par défaut' }))
    await vi.waitFor(() => expect(screen.queryByText('réglé ici')).toBeNull())
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
    expect(within(studio).queryByText(/plafond/)).toBeNull()
    expect(screen.queryByLabelText('Plafond par jour')).toBeNull()
    expect(input('Vidéos faites par jour').value).toBe('10')
    expect([input('Vidéos faites par jour').min, input('Vidéos faites par jour').max]).toEqual(['1', '50'])
    expect(input('Part de vidéos drôles (%)').value).toBe('70')
    fireEvent.change(input('Part de vidéos drôles (%)'), { target: { value: '35' } })
    fireEvent.click(within(studio).getByRole('button', { name: 'Enregistrer' }))
    await vi.waitFor(() => expect(within(studio).getByRole('button', { name: 'Enregistrer' }).getAttribute('aria-busy')).toBeNull())
    expect(input('Part de vidéos drôles (%)').value).toBe('35')
    expect(screen.queryByRole('dialog')).toBeNull()
    fireEvent.change(input('Vidéos faites par jour'), { target: { value: '2' } })
    fireEvent.click(within(studio).getByRole('button', { name: 'Enregistrer' }))
    expect((await screen.findByRole('alert')).textContent).toBe('Vidéos faites par jour : Value error, below BATCH_FLOOR')
    fireEvent.click(screen.getByRole('button', { name: 'Remettre Part de vidéos drôles par défaut' }))
    await vi.waitFor(() => expect(input('Part de vidéos drôles (%)').value).toBe('50'))
    expect(bodies).toEqual([{ values: { humour_share: '0.35' } }, { values: { batch_size: '2' } }, { reset: ['humour_share'] }])
  })

  it('presets: edit, add, remove, save without a password, refusals and reset', async () => {
    const withPresets = (value: AdPresetValue[], version: number, overridden = true): EditableSettings =>
      ({ version, fields: SETTINGS.fields.map((x) => (x.name === 'ads_presets' ? { ...x, value, overridden } : x)) })
    const DE: AdPresetValue = { id: 'germany_young', label: 'Germany young', countries: ['DE', 'AT'], age_min: 18, age_max: 30, placements: ['reels', 'story'] }
    const bodies = stubApi([
      [422, { error: 'invalid', field: 'ads_presets', message: "ads_presets.2.countries.0: Value error, 'DEU' is not a 2-letter country code like FR" }],
      [422, { error: 'invalid', field: 'ads_presets', message: 'ads_presets: Value error, preset be_feed is used by running test 3: remove it once the test ends' }],
      [200, withPresets([{ ...FR, label: 'France only' }, DE], 2)],
      [200, withPresets([FR, BE], 3, false)],
    ])
    render(<SettingsSection section="ads" title="Pubs" />)
    const COUNTRIES = 'Pays (codes à 2 lettres, séparés par des virgules)'
    let box = await screen.findByRole('region', { name: 'Qui voit les pubs' }) // remounted by each save
    const save = () => within(box).getByRole('button', { name: 'Enregistrer les ciblages' }) as HTMLButtonElement
    expect(save().disabled).toBe(true)
    expect(input(COUNTRIES, 1).value).toBe('BE')
    expect((within(box).getByRole('group', { name: 'Emplacements du ciblage 2' }).querySelector('input:checked')?.parentElement?.textContent)).toBe('Fil')
    fireEvent.change(input('Nom', 0), { target: { value: 'France only' } })
    fireEvent.click(within(box).getByRole('button', { name: 'Ajouter un ciblage' }))
    const third = within(box).getByRole('group', { name: 'Ciblage 3' })
    fireEvent.change(within(third).getByLabelText('Nom'), { target: { value: 'Germany young' } })
    fireEvent.change(within(third).getByLabelText(COUNTRIES), { target: { value: 'DEU' } })
    fireEvent.change(within(third).getByLabelText('Âge maximum (vide = 65+)'), { target: { value: '30' } })
    fireEvent.click(within(third).getByLabelText('Stories'))
    fireEvent.click(save())
    expect((await within(box).findByRole('alert')).textContent).toBe("Ciblage 3 : 'DEU' is not a 2-letter country code like FR")
    fireEvent.change(within(third).getByLabelText(COUNTRIES), { target: { value: 'de, AT' } })
    fireEvent.click(within(box).getByRole('button', { name: 'Retirer le ciblage 2' }))
    fireEvent.click(save())
    expect(await within(box).findByText(/be_feed is used by running test 3/)).toBeTruthy()
    fireEvent.click(save())  // the owner tries again once the test ended
    await vi.waitFor(() => expect(screen.getByRole('region', { name: 'Qui voit les pubs' })).not.toBe(box))
    box = screen.getByRole('region', { name: 'Qui voit les pubs' })
    expect(within(box).getByText('réglé ici')).toBeTruthy()
    expect(screen.queryByRole('dialog')).toBeNull() // presets are not money
    expect(within(box).queryByRole('alert')).toBeNull()
    expect(within(box).getAllByRole('group', { name: /^Ciblage / })).toHaveLength(2)
    fireEvent.click(within(box).getByRole('button', { name: 'Rétablir par défaut' }))
    await vi.waitFor(() => expect(screen.getByRole('region', { name: 'Qui voit les pubs' })).not.toBe(box))
    expect(within(screen.getByRole('region', { name: 'Qui voit les pubs' })).queryByText('réglé ici')).toBeNull()
    expect(input('Nom', 1).value).toBe('Belgium, Feed')
    const sentDe = { id: 'germany_young', label: 'Germany young', countries: ['de', 'AT'], age_min: 18, age_max: 30, placements: ['reels', 'story'] }
    expect(bodies).toEqual([
      { values: { ads_presets: [{ ...FR, label: 'France only' }, BE, { ...sentDe, countries: ['DEU'] }] } },
      { values: { ads_presets: [{ ...FR, label: 'France only' }, sentDe] } },
      { values: { ads_presets: [{ ...FR, label: 'France only' }, sentDe] } },
      { reset: ['ads_presets'] },
    ])
  })
})
