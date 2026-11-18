import { useEffect, useState, type FormEvent } from 'react'
import {
  ApiError, errorMessage, getSettings, listAdPresets, saveSettings, type EditableSettings, type SettingField,
} from '../api/client'
import { Button } from '../ui/Button'
import { Card, Skeleton } from '../ui/Card'
import { Chip } from '../ui/Chip'
import { Sheet } from '../ui/Sheet'
import { field as fieldClass } from '../ui/styles'
import { humanize } from './load'

// Step 124: owner-editable settings, stored by the server over .env and seen by every process.
// The form comes from the server (type, limits), so a new editable field needs no web change.
const REAUTH: Record<string, string> = {
  password_not_set: 'Set UI_PASSWORD in .env first: raising a money cap needs the website password.',
  bad_password: 'Wrong password.',
}

type Change = { values?: Record<string, unknown>; reset?: string[] }

// Plain words where the field name says little (step 125); pct: stored 0-1, shown in %.
const COPY: Record<string, { label: string; help: string; pct?: boolean }> = {
  batch_size: { label: 'Videos made per day', help: 'Ideas the AI turns into videos each day (fewer while many liked videos wait).' },
  max_posts_per_day: { label: 'Most posts per day', help: 'Never more posts than this on one day.' },
  explore_share: { label: 'Share of new ideas to try (explore)', help: "At most this part of each day's videos tries something new.", pct: true },
  humour_share: { label: 'Share of funny videos', help: 'Where the funny / informative split starts; your likes move it from there.', pct: true },
}
const label = (name: string) => COPY[name]?.label ?? humanize(name)

const shown = (f: SettingField, v: SettingField['value'] = f.value) =>
  v === null ? '' : COPY[f.name]?.pct ? String(Math.round(Number(v) * 1000) / 10) : String(v)
/** The draft back in the server's unit (% -> share). */
const sent = (f: SettingField, v: string) => (COPY[f.name]?.pct && v.trim() !== '' ? String(Number(v) / 100) : v)

function Input({ f, value, onChange }: { f: SettingField; value: string; onChange: (v: string) => void }) {
  const common = { id: `setting-${f.name}`, value, className: `${fieldClass} w-full`, onChange: (e: { target: { value: string } }) => onChange(e.target.value) }
  if (f.type === 'choice')
    return <select {...common}>{f.choices?.map((c) => <option key={c} value={c}>{humanize(c)}</option>)}</select>
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
    <Sheet title="Raise a money cap" onClose={onClose}>
      <form onSubmit={(e) => void submit(e)} className="mt-3 grid gap-3 text-sm">
        <p className="text-muted">More ad money could be spent. Type your website password.</p>
        <label>Password
          <input type="password" value={password} required autoComplete="current-password"
            onChange={(e) => setPassword(e.target.value)} className={`${fieldClass} mt-1 block w-full`} />
        </label>
        {error && <p role="alert" className="text-danger">{error}</p>}
        <Button type="submit" variant="primary" loading={busy}>Save</Button>
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
  const [presets, setPresets] = useState<string[]>()

  function load(d: EditableSettings) {
    setData(d)
    setDraft(Object.fromEntries(d.fields.map((f) => [f.name, shown(f)])))
  }
  useEffect(() => {
    getSettings().then(load, (e: unknown) => setError(errorMessage(e)))
    if (section === 'ads') listAdPresets().then((p) => setPresets(p.map((x) => x.label)), () => setPresets([]))
  }, [section])

  const fields = data?.fields.filter((f) => f.section === section) ?? []
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
        setError(field ? `${label(field)}: ${msg.replace(`${field}: `, '')}` : msg)
        if (e instanceof ApiError && e.code !== 'bad_password') setPending(null)
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card as="section" aria-label={title}>
      <h2 className="font-semibold">{title}</h2>
      <p className="mt-1 text-sm text-muted">
        Saved here, these win over .env.{section === 'ads' && ' Raising a money cap asks your password.'}
      </p>
      {!data ? (
        error ? <p role="alert" className="mt-2 text-sm text-danger">{error}</p> : <Skeleton className="mt-3 h-24" />
      ) : (
        <form className="mt-3 grid gap-3 text-sm" onSubmit={(e) => { e.preventDefault(); void save({ values: changed }) }}>
          {fields.map((f) => (
            <div key={f.name}>
              <label htmlFor={`setting-${f.name}`} className="font-medium">{label(f.name)}{COPY[f.name]?.pct && ' (%)'}</label>
              {f.overridden && <Chip tone="accent" className="ml-2">set here</Chip>}
              {(COPY[f.name]?.help ?? f.description) && <p className="text-xs text-muted">{COPY[f.name]?.help ?? f.description}</p>}
              <div className="mt-1 flex gap-2">
                <Input f={f} value={draft[f.name] ?? ''} onChange={(v) => setDraft({ ...draft, [f.name]: v })} />
                {f.overridden && (
                  <Button size="sm" variant="ghost" disabled={busy} onClick={() => void save({ reset: [f.name] })}
                    aria-label={`Reset ${label(f.name)} to default`} title={`.env: ${shown(f, f.default) || 'empty'}`}>
                    Reset
                  </Button>
                )}
              </div>
            </div>
          ))}
          {presets && (
            <p className="text-muted">Audience and placement presets (read-only for now): {presets.join(' · ') || 'none'}</p>
          )}
          {error && !pending && <p role="alert" className="text-danger">{error}</p>}
          <Button type="submit" variant="primary" loading={busy} disabled={!Object.keys(changed).length}>Save</Button>
        </form>
      )}
      {pending && <PasswordSheet error={error} onSubmit={(p) => save(pending, p)} onClose={() => { setPending(null); setError(null) }} />}
    </Card>
  )
}
