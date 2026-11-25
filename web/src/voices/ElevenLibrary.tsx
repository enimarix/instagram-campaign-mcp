import { useEffect, useState } from 'react'
import { addElevenCard, errorMessage, searchElevenVoices, type ElevenVoice, type Voice, type VoiceSearch } from '../api/client'
import { Button } from '../ui/Button'
import { Chip } from '../ui/Chip'
import { Sheet } from '../ui/Sheet'
import { clip } from '../pages/load'
import { Preview } from './Preview'
import { field } from '../ui/styles'

// The Voice Library filters (GET /v1/shared-voices): the API takes these values as they are.
const LANGUAGES: [string, string][] = [['fr', 'Français'], ['en', 'Anglais'], ['es', 'Espagnol'], ['de', 'Allemand'], ['it', 'Italien'], ['pt', 'Portugais'], ['ar', 'Arabe'], ['', 'Toutes']]
const GENDERS: [string, string][] = [['', 'Tous'], ['female', 'Femme'], ['male', 'Homme'], ['neutral', 'Neutre']]
const AGES: [string, string][] = [['', 'Tous'], ['young', 'Jeune'], ['middle_aged', 'Adulte'], ['old', 'Âgé']]
const USES: [string, string][] = [['', 'Tous'], ['social_media', 'Réseaux sociaux'], ['narrative_story', 'Récit'], ['conversational', 'Conversation'], ['characters_animation', 'Personnages'], ['informative_educational', 'Explications'], ['advertisement', 'Pub'], ['entertainment_tv', 'Divertissement']]
const MOODS: [string, string][] = [['', 'Tous'], ['upbeat', 'Enjoué'], ['confident', 'Assuré'], ['casual', 'Décontracté'], ['calm', 'Calme'], ['deep', 'Grave'], ['soft', 'Doux'], ['intense', 'Intense'], ['excited', 'Excité'], ['sassy', 'Piquant'], ['professional', 'Pro'], ['whispery', 'Chuchoté']]
const SORTS: [string, string][] = [['trending', 'Tendance'], ['usage_character_count_1y', 'Les plus utilisées'], ['cloned_by_count', 'Les plus ajoutées'], ['created_date', 'Récentes']]
const CARD_GENDERS = ['male', 'female', 'neutral'] // what a card takes (src/api/voices.py CardIn)
const label = (list: [string, string][], v: string | null) => list.find(([k]) => k === v)?.[1] ?? v

function Select({ name, list, value, onChange }: { name: string; list: [string, string][]; value: string; onChange: (v: string) => void }) {
  return (
    <label className="block text-sm">
      <span className="text-muted">{name}</span>
      <select aria-label={name} className={`${field} mt-1 block w-full`} value={value} onChange={(e) => onChange(e.target.value)}>
        {list.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
      </select>
    </label>
  )
}

/** The card form once a voice is picked: its name, what the AI uses it for, its local relay. */
function AddForm({ voice: v, locals, onAdded, onCancel }: { voice: ElevenVoice; locals: Voice[]; onAdded: (c: Voice) => void; onCancel: () => void }) {
  const same = locals.find((l) => l.gender && l.gender === v.gender) ?? locals[0]
  const [name, setName] = useState(clip(v.name.split(' - ')[0], 60))
  const [useFor, setUseFor] = useState(clip(v.description, 400))
  const [fallback, setFallback] = useState(same?.id ?? '')
  const [address, setAddress] = useState<string[]>(['tu', 'vous'])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const flip = (a: string) => setAddress((x) => (x.includes(a) ? (x.length > 1 ? x.filter((y) => y !== a) : x) : [...x, a]))
  const add = () => {
    setBusy(true)
    setError(null)
    addElevenCard({
      voice_id: v.voice_id, public_owner_id: v.public_owner_id, label: name, fallback, use_for: useFor,
      description: clip(v.description, 400), gender: CARD_GENDERS.includes(v.gender ?? '') ? v.gender : null,
      language: v.language?.slice(0, 10), accent: v.accent?.slice(0, 40),
      preview_url: v.preview_url, address,
    }).then(onAdded, (e: unknown) => { setError(errorMessage(e)); setBusy(false) })
  }
  return (
    <div className="mt-3 space-y-3 rounded-control border border-line p-3" aria-label={`Ajouter ${v.name}`} role="group">
      <label className="block text-sm"><span className="font-medium">Nom de la carte</span>
        <input className={`${field} mt-1 block w-full`} value={name} maxLength={60} onChange={(e) => setName(e.target.value)} /></label>
      <label className="block text-sm"><span className="font-medium">L'IA la choisit pour</span>
        <textarea className={`${field} mt-1 block w-full py-2`} rows={3} maxLength={400} value={useFor}
          placeholder="Énergie et accroches : astuces rapides, défis, humour…" onChange={(e) => setUseFor(e.target.value)} /></label>
      <label className="block text-sm"><span className="font-medium">Voix locale de relais</span>
        <select aria-label="Voix locale de relais" className={`${field} mt-1 block w-full`} value={fallback} onChange={(e) => setFallback(e.target.value)}>
          {locals.map((l) => <option key={l.id} value={l.id}>{l.label}</option>)}
        </select>
        <span className="mt-1 block text-muted">Elle parle à la place de cette voix quand ElevenLabs échoue (et inversement si la voix locale passe en premier).</span>
      </label>
      <div className="flex flex-wrap items-center gap-2 text-sm"><span className="font-medium">Tutoiement</span>
        {['tu', 'vous'].map((a) => <Chip key={a} pressed={address.includes(a)} onClick={() => flip(a)}>{a}</Chip>)}</div>
      {v.public_owner_id && <p className="text-sm text-muted">Une voix de la bibliothèque prend un emplacement de voix sur votre compte ElevenLabs (3 sur l'offre gratuite).</p>}
      {error && <p role="alert" className="text-sm text-danger">{error}</p>}
      <div className="flex gap-2">
        <Button variant="primary" loading={busy} disabled={!name.trim() || !fallback} onClick={add}>Ajouter la carte</Button>
        <Button variant="ghost" onClick={onCancel}>Annuler</Button>
      </div>
    </div>
  )
}

/** Step 204: search the ElevenLabs Voice Library (or the account's own voices) with filters,
 * listen to each voice, and add one as a card. The library holds thousands of voices: it is
 * searched page by page on the server, never loaded whole. */
export function ElevenLibrary({ locals, onAdded, onClose }: { locals: Voice[]; onAdded: (c: Voice) => void; onClose: () => void }) {
  const [q, setQ] = useState<VoiceSearch>({ source: 'library', language: 'fr', sort: 'trending' })
  const [text, setText] = useState('')
  // the answer and the query it answers: another query shows « Recherche… » until its own comes
  const [res, setRes] = useState<{ q: VoiceSearch; voices: ElevenVoice[]; next: string | null; total: number | null; error?: string }>()
  const [more, setMore] = useState(false)
  const [picked, setPicked] = useState<string | null>(null)
  const set = (k: keyof VoiceSearch) => (v: string) => setQ((x) => ({ ...x, [k]: v }))

  useEffect(() => {
    let live = true
    searchElevenVoices(q).then((r) => live && setRes({ q, ...r }),
      (e: unknown) => live && setRes({ q, voices: [], next: null, total: null, error: errorMessage(e) }))
    return () => { live = false }
  }, [q])
  const current = res?.q === q ? res : undefined
  const found = current?.voices
  const error = current?.error ?? null
  const next = current?.next ?? null
  const total = current?.total ?? null
  // one preview at a time
  useEffect(() => {
    const only = (e: Event) => document.querySelectorAll('audio').forEach((a) => a !== e.target && a.pause())
    document.addEventListener('play', only, true)
    return () => document.removeEventListener('play', only, true)
  }, [])

  const loadMore = () => {
    if (!next) return
    setMore(true)
    searchElevenVoices({ ...q, page: next }).then(
      (r) => setRes((x) => x && x.q === q ? { ...x, voices: [...x.voices, ...r.voices], next: r.next } : x),
      (e: unknown) => setRes((x) => x && { ...x, error: errorMessage(e) })).finally(() => setMore(false))
  }
  const library = q.source === 'library'
  return (
    <Sheet title="Ajouter une voix ElevenLabs" onClose={onClose} wide>
      <div className="mt-3 flex flex-wrap gap-2" role="group" aria-label="Où chercher">
        <Chip pressed={library} onClick={() => setQ({ ...q, source: 'library', page: undefined })}>Bibliothèque ElevenLabs</Chip>
        <Chip pressed={!library} onClick={() => setQ({ ...q, source: 'account', page: undefined })}>Mes voix</Chip>
      </div>
      <form className="mt-3 flex gap-2" role="search" onSubmit={(e) => { e.preventDefault(); setQ({ ...q, search: text.trim() }) }}>
        <input aria-label="Rechercher une voix" className={`${field} min-w-0 flex-1`} placeholder="Nom, style, « coach », « narrateur »…" value={text} onChange={(e) => setText(e.target.value)} />
        <Button type="submit">Chercher</Button>
      </form>
      <div className="mt-3 grid grid-cols-2 gap-2 md:grid-cols-4">
        <Select name="Langue" list={LANGUAGES} value={q.language ?? ''} onChange={set('language')} />
        <Select name="Genre" list={GENDERS} value={q.gender ?? ''} onChange={set('gender')} />
        <Select name="Âge" list={AGES} value={q.age ?? ''} onChange={set('age')} />
        {library && <Select name="Usage" list={USES} value={q.use_cases ?? ''} onChange={set('use_cases')} />}
        {library && <Select name="Ton" list={MOODS} value={q.descriptives ?? ''} onChange={set('descriptives')} />}
        {library && <label className="block text-sm"><span className="text-muted">Accent</span>
          <input aria-label="Accent" className={`${field} mt-1 block w-full`} placeholder="parisian, quebec…" defaultValue={q.accent ?? ''}
            onBlur={(e) => e.target.value.trim() !== (q.accent ?? '') && set('accent')(e.target.value.trim())} /></label>}
        {library && <Select name="Tri" list={SORTS} value={q.sort ?? 'trending'} onChange={set('sort')} />}
      </div>

      <div className="mt-4 max-h-[55dvh] overflow-y-auto pr-1">
        {error ? <p role="alert" className="text-sm text-danger">Recherche impossible : {error}</p>
          : !found ? <p className="text-sm text-muted" role="status">Recherche…</p>
            : !found.length ? <p className="text-sm text-muted">Aucune voix avec ces filtres.</p>
              : (
                <>
                  {total != null && <p className="mb-2 text-sm text-muted" role="status">{total.toLocaleString('fr-FR')} voix</p>}
                  <ul className="space-y-3">
                    {found.map((v) => (
                      <li key={`${v.public_owner_id ?? ''}${v.voice_id}`} className="rounded-control border border-line/60 p-3">
                        <div className="flex items-start gap-3">
                          <div className="min-w-0 flex-1">
                            <h3 className="font-medium">{v.name}</h3>
                            <p className="mt-1 flex flex-wrap gap-1">
                              {[label(GENDERS, v.gender), label(AGES, v.age), v.accent, label(USES, v.use_case), label(MOODS, v.descriptive), v.language]
                                .filter(Boolean).map((t, i) => <Chip key={i}>{t}</Chip>)}
                              {!v.free_users_allowed && <Chip tone="warn" title="Réservée aux offres payantes">Payante</Chip>}
                            </p>
                          </div>
                          {picked !== v.voice_id && <Button size="sm" onClick={() => setPicked(v.voice_id)}>Choisir</Button>}
                        </div>
                        {v.description && <p className="mt-2 line-clamp-2 text-sm text-muted">{v.description}</p>}
                        {v.preview_url && <Preview eager src={v.preview_url} label={`Écouter ${v.name}`} />}
                        {picked === v.voice_id && (
                          <AddForm voice={v} locals={locals} onCancel={() => setPicked(null)} onAdded={(c) => { onAdded(c); onClose() }} />
                        )}
                      </li>
                    ))}
                  </ul>
                  {next && <Button className="mt-3 w-full" loading={more} onClick={loadMore}>Voir plus</Button>}
                </>
              )}
      </div>
    </Sheet>
  )
}
