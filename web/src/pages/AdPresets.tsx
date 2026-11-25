import { useState } from 'react'
import {
  errorMessage, saveSettings, type AdPlacement, type AdPresetValue, type EditableSettings, type SettingField,
} from '../api/client'
import { Button } from '../ui/Button'
import { Chip } from '../ui/Chip'
import { field as fieldClass } from '../ui/styles'

// Step 127: the ad presets (`ads_presets`) edited as a list. No password: presets are not money.
// Keyed by the settings version: a save or reset starts the drafts again from the server.
const PLACEMENTS: [AdPlacement, string][] = [['reels', 'Reels'], ['stream', 'Fil'], ['story', 'Stories'], ['explore', 'Explorer']]
const MAX = 10

type Draft = { id: string; label: string; countries: string; age_min: string; age_max: string; placements: AdPlacement[] }

const toDraft = (p: AdPresetValue): Draft => ({
  ...p, countries: p.countries.join(', '), age_min: String(p.age_min), age_max: p.age_max === null ? '' : String(p.age_max),
})
const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 36) || 'preset'

/** The drafts as the server wants them; a new preset gets an id from its label. */
function toValues(drafts: Draft[]): AdPresetValue[] {
  const ids = new Set(drafts.map((d) => d.id).filter(Boolean))
  return drafts.map((d) => {
    let id = d.id
    for (let n = 2, base = slug(d.label); !id; n++) {
      const next = n === 2 ? base : `${base}_${n}`
      if (!ids.has(next)) { id = next; ids.add(id) }
    }
    return {
      id, label: d.label, countries: d.countries.split(',').map((c) => c.trim()).filter(Boolean),
      age_min: Number(d.age_min), age_max: d.age_max.trim() === '' ? null : Number(d.age_max), placements: d.placements,
    }
  })
}

/** "ads_presets.1.countries.0: Value error, x" -> "Ciblage 2 : x". */
const friendly = (msg: string) =>
  msg.replace(/^ads_presets\.(\d+)[^:]*: /, (_, i: string) => `Ciblage ${Number(i) + 1} : `)
    .replace(/^ads_presets: /, '').replace('Value error, ', '')

export default function AdPresets({ field, onSaved }: { field: SettingField; onSaved: (d: EditableSettings) => void }) {
  const value = field.value as AdPresetValue[]
  const [drafts, setDrafts] = useState<Draft[]>(() => value.map(toDraft))
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const changed = JSON.stringify(toValues(drafts)) !== JSON.stringify(value)
  const edit = (i: number, patch: Partial<Draft>) => setDrafts(drafts.map((d, j) => (j === i ? { ...d, ...patch } : d)))

  async function save(change: { values?: Record<string, unknown>; reset?: string[] }) {
    setBusy(true)
    setError(null)
    try {
      onSaved(await saveSettings(change))
    } catch (e) {
      setError(friendly(errorMessage(e)))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section aria-label="Qui voit les pubs" className="mt-4 grid gap-3 border-t border-line pt-3 text-sm">
      <div>
        <h3 className="font-medium">Qui voit les pubs{field.overridden && <Chip tone="accent" className="ml-2">réglé ici</Chip>}</h3>
        <p className="text-xs text-muted">Les ciblages (public et emplacements) parmi lesquels l’IA choisit pour chaque pub. Un ciblage utilisé par un test en cours ne peut pas être retiré.</p>
      </div>
      {drafts.map((d, i) => {
        const id = `preset-${i}`
        return (
          <fieldset key={i} aria-label={`Ciblage ${i + 1}`} className="grid gap-2 rounded-lg border border-line p-3">
            <div className="flex items-end gap-2">
              <label htmlFor={`${id}-label`} className="grow">Nom
                <input id={`${id}-label`} value={d.label} maxLength={80} onChange={(e) => edit(i, { label: e.target.value })}
                  className={`${fieldClass} mt-1 block w-full`} />
              </label>
              <Button size="sm" variant="ghost" disabled={busy || drafts.length === 1}
                aria-label={`Retirer le ciblage ${i + 1}`} onClick={() => setDrafts(drafts.filter((_, j) => j !== i))}>
                Retirer
              </Button>
            </div>
            <label htmlFor={`${id}-countries`}>Pays (codes à 2 lettres, séparés par des virgules)
              <input id={`${id}-countries`} value={d.countries} placeholder="FR, BE" onChange={(e) => edit(i, { countries: e.target.value })}
                className={`${fieldClass} mt-1 block w-full`} />
            </label>
            <div className="flex gap-2">
              <label htmlFor={`${id}-min`}>Âge minimum
                <input id={`${id}-min`} type="number" min={18} max={65} value={d.age_min} onChange={(e) => edit(i, { age_min: e.target.value })}
                  className={`${fieldClass} mt-1 block w-24`} />
              </label>
              <label htmlFor={`${id}-max`}>Âge maximum (vide = 65+)
                <input id={`${id}-max`} type="number" min={18} max={65} value={d.age_max} onChange={(e) => edit(i, { age_max: e.target.value })}
                  className={`${fieldClass} mt-1 block w-24`} />
              </label>
            </div>
            <div className="flex flex-wrap gap-3" role="group" aria-label={`Emplacements du ciblage ${i + 1}`}>
              {PLACEMENTS.map(([p, name]) => (
                <label key={p} className="flex items-center gap-1">
                  <input type="checkbox" checked={d.placements.includes(p)}
                    onChange={(e) => edit(i, { placements: e.target.checked ? [...d.placements, p] : d.placements.filter((x) => x !== p) })} />
                  {name}
                </label>
              ))}
            </div>
          </fieldset>
        )
      })}
      {error && <p role="alert" className="text-danger">{error}</p>}
      <div className="flex flex-wrap gap-2">
        <Button variant="primary" loading={busy} disabled={!changed} onClick={() => void save({ values: { ads_presets: toValues(drafts) } })}>
          Enregistrer les ciblages
        </Button>
        <Button disabled={busy || drafts.length >= MAX}
          onClick={() => setDrafts([...drafts, { id: '', label: '', countries: '', age_min: '18', age_max: '', placements: ['reels'] }])}>
          Ajouter un ciblage
        </Button>
        {field.overridden && (
          <Button variant="ghost" disabled={busy} onClick={() => void save({ reset: ['ads_presets'] })}>Rétablir par défaut</Button>
        )}
      </div>
    </section>
  )
}
