import { useEffect, useState, type FormEvent } from 'react'
import {
  ApiError, errorMessage, getSettings, saveSettings, type EditableSettings, type SettingField,
} from '../api/client'
import { Button } from '../ui/Button'
import { Card, Skeleton } from '../ui/Card'
import { Chip } from '../ui/Chip'
import { Sheet } from '../ui/Sheet'
import { field as fieldClass } from '../ui/styles'
import AdPresets from './AdPresets'
import { humanize } from './load'

// Step 124: owner-editable settings, stored by the server over .env and seen by every process.
// The form comes from the server (type, limits), so a new editable field needs no web change.
const REAUTH: Record<string, string> = {
  password_not_set: 'Mets d’abord UI_PASSWORD dans .env : monter un plafond d’argent demande le mot de passe du site.',
  bad_password: 'Mauvais mot de passe.',
}

type Change = { values?: Record<string, unknown>; reset?: string[] }

// Every field the server sends, in plain French (step 125; config.py descriptions stay for developers,
// a new field without an entry shows its humanized name and that description). pct: stored 0-1, shown in %.
const COPY: Record<string, { label: string; help: string; pct?: boolean }> = {
  batch_size: { label: 'Vidéos faites par jour', help: 'Les idées que l’IA fait seule chaque jour (moins quand beaucoup de vidéos aimées attendent). Tes propres commandes passent toujours : elles prennent des places sur ce nombre. 0 = pas de limite : l’IA en fait autant que son run le permet.' },
  max_posts_per_day: { label: 'Posts par jour au plus', help: 'Jamais plus de posts que ça sur une journée.' },
  explore_share: { label: 'Part d’idées nouvelles à essayer (explorer)', help: 'Au plus cette part des vidéos du jour essaie quelque chose de nouveau.', pct: true },
  humour_share: { label: 'Part de vidéos drôles', help: 'Le point de départ du partage drôle / instructif ; tes « j’aime » le font bouger ensuite.', pct: true },
  lemo_films_per_day: { label: 'Films Lemo par jour', help: 'Les films que tes commandes en style Lemo lancent chaque jour (chacun coûte quelques dollars de tokens). 0 = pas de limite. Un film arrêté par un redémarrage du studio ne compte pas.' },
  ads_daily_cap: { label: 'Plafond par jour', help: 'Dépense maximale sur une journée, dans la monnaie du compte pub. 0 = aucune dépense.' },
  ads_test_cap: { label: 'Plafond par test', help: 'Dépense maximale pour un test A/B. 0 = aucune dépense.' },
  ads_lifetime_cap: { label: 'Plafond total', help: 'Dépense maximale depuis le début, tous tests confondus. 0 = aucune dépense.' },
  ads_currency: { label: 'Monnaie', help: 'Code ISO à 3 lettres (EUR, USD…). Il doit être celui du compte pub.' },
  ads_objective: { label: 'Objectif des pubs', help: 'Ce que Meta cherche à obtenir pour les posts mis en avant.' },
  ads_test_days: { label: 'Durée d’un test (jours)', help: 'Jours pendant lesquels un test A/B tourne avant d’être jugé. Meta conseille 7 jours ou plus.' },
  ads_max_running_tests: { label: 'Tests en même temps', help: 'Nombre maximal de tests A/B payants en cours à la fois.' },
  meta_ad_account_id: { label: 'Compte pub Meta', help: 'Le numéro du compte pub, chiffres seulement (sans act_).' },
  meta_page_id: { label: 'Page Facebook', help: 'Le numéro de la Page Facebook liée au compte Instagram.' },
  ads_dsa_beneficiary: { label: 'Bénéficiaire (DSA)', help: 'Qui profite des pubs, comme l’exige le DSA européen.' },
  ads_dsa_payor: { label: 'Payeur (DSA)', help: 'Qui paie les pubs, comme l’exige le DSA européen.' },
}
// Choice values in plain words; an unknown one is humanized.
const CHOICES: Record<string, string> = { OUTCOME_AWARENESS: 'Notoriété', OUTCOME_ENGAGEMENT: 'Interactions' }
const label = (name: string) => COPY[name]?.label ?? humanize(name)

const shown = (f: SettingField, v: SettingField['value'] = f.value) =>
  v === null ? '' : COPY[f.name]?.pct ? String(Math.round(Number(v) * 1000) / 10) : String(v)
/** The draft back in the server's unit (% -> share). */
const sent = (f: SettingField, v: string) => (COPY[f.name]?.pct && v.trim() !== '' ? String(Number(v) / 100) : v)

function Input({ f, value, onChange }: { f: SettingField; value: string; onChange: (v: string) => void }) {
  const common = { id: `setting-${f.name}`, value, className: `${fieldClass} w-full`, onChange: (e: { target: { value: string } }) => onChange(e.target.value) }
  if (f.type === 'choice')
    return <select {...common}>{f.choices?.map((c) => <option key={c} value={c}>{CHOICES[c] ?? humanize(c)}</option>)}</select>
  if (f.type === 'text') return <input {...common} type="text" maxLength={f.max_length} />
  if (COPY[f.name]?.pct) return <input {...common} type="number" inputMode="decimal" min={0} max={100} step="any" />
  return <input {...common} type="number" inputMode="decimal" min={f.ge ?? f.gt} max={f.le ?? f.lt}
    step={f.type === 'money' ? '0.01' : f.type === 'int' ? '1' : 'any'} />
}

function PasswordSheet({ onSubmit, onClose, error }: { onSubmit: (password: string) => Promise<void>; onClose: () => void; error: string | null }) {
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    await onSubmit(password)
    setBusy(false)
  }
  return (
    <Sheet title="Monter un plafond d’argent" onClose={onClose}>
      <form onSubmit={(e) => void submit(e)} className="mt-3 grid gap-3 text-sm">
        <p className="text-muted">Plus d’argent pourrait partir en pubs. Tape le mot de passe du site.</p>
        <label>Mot de passe
          <input type="password" value={password} required autoComplete="current-password"
            onChange={(e) => setPassword(e.target.value)} className={`${fieldClass} mt-1 block w-full`} />
        </label>
        {error && <p role="alert" className="text-danger">{error}</p>}
        <Button type="submit" variant="primary" loading={busy}>Enregistrer</Button>
      </form>
    </Sheet>
  )
}

/** One section of GET /api/settings as a form: edit, save, reset a field to its .env value. */
export default function SettingsSection({ section, title }: { section: string; title: string }) {
  const [data, setData] = useState<EditableSettings>()
  const [draft, setDraft] = useState<Record<string, string>>({})
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState<Change | null>(null) // waits for the password
  const [busy, setBusy] = useState(false)

  function load(d: EditableSettings) {
    setData(d)
    setDraft(Object.fromEntries(d.fields.map((f) => [f.name, shown(f)])))
  }
  useEffect(() => {
    getSettings().then(load, (e: unknown) => setError(errorMessage(e)))
  }, [])

  const all = data?.fields.filter((f) => f.section === section) ?? []
  const fields = all.filter((f) => f.type !== 'presets')
  const presets = all.find((f) => f.type === 'presets')
  const changed = Object.fromEntries(fields.filter((f) => draft[f.name] !== shown(f)).map((f) => [f.name, sent(f, draft[f.name])]))

  async function save(change: Change, password?: string) {
    setBusy(true)
    setError(null)
    try {
      load(await saveSettings({ ...change, ...(password !== undefined && { password }) }))
      setPending(null)
    } catch (e) {
      if (e instanceof ApiError && e.code === 'password_required') setPending(change)
      else {
        const field = e instanceof ApiError ? (e.body as { field?: string } | null)?.field : undefined
        const msg = e instanceof ApiError && REAUTH[e.code] ? REAUTH[e.code] : errorMessage(e)
        setError(field ? `${label(field)} : ${msg.replace(`${field}: `, '')}` : msg)
        if (e instanceof ApiError && e.code !== 'bad_password') setPending(null)
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card as="section" id={section} aria-label={title} className="scroll-mt-16 lg:scroll-mt-4">
      <h2 className="font-semibold">{title}</h2>
      <p className="mt-1 text-sm text-muted">
        Enregistrés ici, ils passent avant .env.{section === 'ads' && ' Monter un plafond d’argent demande ton mot de passe.'}
      </p>
      {!data ? (
        error ? <p role="alert" className="mt-2 text-sm text-danger">{error}</p> : <Skeleton className="mt-3 h-24" />
      ) : (
        <form className="mt-3 grid gap-3 text-sm" onSubmit={(e) => { e.preventDefault(); void save({ values: changed }) }}>
          {fields.map((f) => (
            <div key={f.name}>
              <label htmlFor={`setting-${f.name}`} className="font-medium">{label(f.name)}{COPY[f.name]?.pct && ' (%)'}</label>
              {f.overridden && <Chip tone="accent" className="ml-2">réglé ici</Chip>}
              {(COPY[f.name]?.help ?? f.description) && <p className="text-xs text-muted">{COPY[f.name]?.help ?? f.description}</p>}
              <div className="mt-1 flex gap-2">
                <Input f={f} value={draft[f.name] ?? ''} onChange={(v) => setDraft({ ...draft, [f.name]: v })} />
                {f.overridden && (
                  <Button size="sm" variant="ghost" disabled={busy} onClick={() => void save({ reset: [f.name] })}
                    aria-label={`Remettre ${label(f.name)} par défaut`} title={`.env : ${shown(f, f.default) || 'vide'}`}>
                    Rétablir
                  </Button>
                )}
              </div>
            </div>
          ))}
          {error && !pending && <p role="alert" className="text-danger">{error}</p>}
          <Button type="submit" variant="primary" loading={busy} disabled={!Object.keys(changed).length}>Enregistrer</Button>
        </form>
      )}
      {data && presets && <AdPresets key={data.version} field={presets} onSaved={load} />}
      {pending && <PasswordSheet error={error} onSubmit={(p) => save(pending, p)} onClose={() => { setPending(null); setError(null) }} />}
    </Card>
  )
}
