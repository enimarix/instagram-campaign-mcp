// The Learnings page (step 084): what the studio has learned about your taste and the
// audience, with the evidence behind it. Your edits always win: a rule you edit or confirm
// becomes yours, and neither the agent nor the nightly numbers change it.
import { useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import {
  addRule, editLearning, errorMessage, getTaxonomy, listLearnings, refreshLearnings, setLearning,
  type Evidence, type Learning, type LearningFilters, type LearningKind, type Predicate, type Taxonomy,
} from '../api/client'
import { Button } from '../ui/Button'
import { Card, EmptyState } from '../ui/Card'
import { Chip } from '../ui/Chip'
import { PageHeader } from '../ui/PageHeader'
import { Sheet } from '../ui/Sheet'
import { field, link, type Tone } from '../ui/styles'
import { useToast } from '../ui/useToast'
import { Body } from './Analytics'
import { tagName, TAGS, tagValue, useLoad } from './load'

const KIND: Record<LearningKind, [Tone, string]> = { do: ['success', 'À faire'], dont: ['danger', 'À éviter'], hypothesis: ['info', 'Idée'] }
const ORIGIN: Record<Learning['origin'], string> = { taste: 'Ton goût', audience: 'Public', ads: 'Pubs' }
const CONFIDENCE: Record<Learning['confidence'], [Tone, string]> = {
  owner: ['accent', 'Ta règle'], high: ['success', 'Sûre'], medium: ['warn', 'Assez sûre'], low: ['neutral', 'Incertaine'],
}
const STATUS: Record<Learning['status'], string> = { active: 'Active', contradicted: 'Contredite', retired: 'Retirée' }
const VERDICT: Record<NonNullable<Evidence['verdict']>, string> = {
  supports: 'les chiffres sont d’accord', contradicts: 'les chiffres disent le contraire', inconclusive: 'pas encore de différence nette',
  needs_n: 'trop peu de publications pour le dire', untested: 'une idée, pas testée',
}
const FILTERS: [keyof LearningFilters, string, Record<string, string>][] = [
  ['kind', 'Type', Object.fromEntries(Object.entries(KIND).map(([k, [, l]]) => [k, l]))],
  ['status', 'Statut', STATUS],
  ['origin', 'Origine', ORIGIN],
  ['confidence', 'Confiance', Object.fromEntries(Object.entries(CONFIDENCE).map(([k, [, l]]) => [k, l]))],
]
// The predicate tags with their taxonomy vocabulary; the others have fixed values.
const VOCAB: Record<string, keyof Taxonomy> = { track: 'tracks', pillar: 'pillars', hook_type: 'hook_types', template: 'templates' }
const FIXED: Record<string, string[]> = {
  strategy: ['explore', 'exploit'],
  hour: Array.from({ length: 24 }, (_, h) => String(h)),
  duration: ['<15 s', '15–30 s', '30–60 s', '60 s+'], // breakdowns.duration_bucket
}
const values = (tag: string, tax?: Taxonomy | null): [string, string][] =>
  VOCAB[tag]
    ? (tax?.[VOCAB[tag]]?.values ?? []).map((v) => [v.id, v.label])
    : (FIXED[tag] ?? []).map((v) => [v, tagValue(tag, v)])
/** "Type d’accroche = Question" (the taxonomy's label when it is loaded). */
const predicateWords = ({ tag, value }: Predicate, tax?: Taxonomy | null) =>
  `${tagName(tag)} = ${values(tag, tax).find(([v]) => v === value)?.[1] ?? value}`
/** 1.23 → "+23 % vs la normale". */
const vsTypical = (index: number) => {
  const p = Math.round((index - 1) * 100)
  return `${p > 0 ? '+' : p < 0 ? '−' : '±'}${Math.abs(p)} % vs la normale`
}

function EvidenceItem({ e }: { e: Evidence }) {
  if (e.feedback_id !== undefined)
    return (
      <li className="flex items-center gap-2">
        {e.thumbnail_url && <img src={e.thumbnail_url} alt="" className="h-10 w-6 shrink-0 rounded object-cover" />}
        <span className="min-w-0">
          Ton commentaire{e.text ? <> : « {e.text} »</> : ' (raisons seulement)'}
          {e.asset_id !== undefined && <> · <Link to={`/assets/${e.asset_id}`} className={link}>la vidéo</Link></>}
        </span>
      </li>
    )
  if (e.kind === 'audience_index')
    return (
      <li>
        Public : {e.n} publication{(e.n ?? 0) > 1 ? 's' : ''}
        {e.index != null && ` · ${vsTypical(e.index)}`}
        {e.verdict && ` · ${VERDICT[e.verdict]}`}
        {e.verdict === 'needs_n' && e.note && ` (${e.note})`}
      </li>
    )
  if (e.kind === 'conflict')
    return (
      <li className="rounded-control bg-warn/12 px-2 py-1 text-warn">
        Conflit : {e.detail}
        {e.with != null && <> · <a href={`#learning-${e.with}`} className="underline">voir cette règle</a></>}
      </li>
    )
  return <li>{e.note ?? e.detail ?? JSON.stringify(e)}</li>
}

type Act = (id: number, action: 'confirm' | 'retire' | 'reactivate') => void

function LearningCard({ l, tax, onEdit, act }: { l: Learning; tax?: Taxonomy | null; onEdit: () => void; act: Act }) {
  const contradicted = l.status === 'contradicted'
  return (
    <Card as="li" id={`learning-${l.id}`} className={`text-sm ${contradicted ? 'border-danger!' : ''} ${l.status === 'retired' ? 'opacity-70' : ''}`}>
      <div className="flex flex-wrap items-center gap-1.5">
        <Chip tone={KIND[l.kind][0]}>{KIND[l.kind][1]}</Chip>
        <Chip>{ORIGIN[l.origin]}</Chip>
        <Chip tone={CONFIDENCE[l.confidence][0]}>{CONFIDENCE[l.confidence][1]}</Chip>
        {l.status !== 'active' && <Chip tone={contradicted ? 'danger' : 'neutral'}>{contradicted ? 'Contredite par les chiffres' : STATUS.retired}</Chip>}
      </div>
      <p className="mt-2 text-base font-medium">{l.statement}</p>
      {l.scope.tag && l.scope.value && <p className="mt-1 text-muted">Quand {predicateWords(l.scope as Predicate, tax)}</p>}
      {l.evidence.length > 0 && (
        <ul aria-label="Preuves" className="mt-2 space-y-1 text-xs text-muted">
          {l.evidence.map((e, i) => <EvidenceItem key={i} e={e} />)}
        </ul>
      )}
      <div className="mt-3 flex flex-wrap gap-2">
        <Button size="sm" onClick={onEdit}>Modifier</Button>
        {l.confidence !== 'owner' && <Button size="sm" onClick={() => act(l.id, 'confirm')}>Confirmer</Button>}
        {l.status !== 'retired' && <Button size="sm" variant="ghost" onClick={() => act(l.id, 'retire')}>Retirer</Button>}
        {l.status !== 'active' && <Button size="sm" variant="ghost" onClick={() => act(l.id, 'reactivate')}>Réactiver</Button>}
      </div>
    </Card>
  )
}

/** Add a rule (no `rule`) or edit one; any change makes it yours. */
function RuleSheet({ rule, tax, onClose, onSaved }: { rule?: Learning; tax?: Taxonomy | null; onClose: () => void; onSaved: () => void }) {
  const [statement, setStatement] = useState(rule?.statement ?? '')
  const [kind, setKind] = useState<LearningKind>(rule?.kind ?? 'dont')
  const [tag, setTag] = useState(rule?.scope.tag ?? '')
  const [value, setValue] = useState(rule?.scope.value ?? '')
  const [error, setError] = useState<string>()
  const [busy, setBusy] = useState(false)
  const options = values(tag, tax)
  const submit = async (ev: FormEvent) => {
    ev.preventDefault()
    const input = { statement, kind, predicate: tag ? { tag, value } : null }
    setBusy(true)
    try {
      await (rule ? editLearning(rule.id, input) : addRule(input))
      onSaved()
    } catch (e) {
      setError(errorMessage(e))
      setBusy(false)
    }
  }
  return (
    <Sheet title={rule ? 'Modifier la règle' : 'Ajouter une règle'} onClose={onClose}>
      <form onSubmit={submit} className="mt-3 space-y-3 text-sm">
        <label className="block">
          <span className="font-medium">La règle</span>
          <textarea value={statement} onChange={(e) => setStatement(e.target.value)} rows={3} required
            placeholder="Ne jamais commencer par un carton de titre lent" className={`${field} mt-1 w-full py-2`} />
        </label>
        <label className="block">
          <span className="font-medium">Type</span>
          <select value={kind} onChange={(e) => setKind(e.target.value as LearningKind)} className={`${field} mt-1 w-full`}>
            <option value="do">À faire</option><option value="dont">À éviter</option><option value="hypothesis">Idée à tester</option>
          </select>
        </label>
        <fieldset className="grid grid-cols-2 gap-2">
          <legend className="col-span-2 font-medium">Seulement quand (facultatif : les chiffres peuvent alors la vérifier)</legend>
          <select aria-label="Condition" value={tag} className={field}
            onChange={(e) => { setTag(e.target.value); setValue(values(e.target.value, tax)[0]?.[0] ?? '') }}>
            <option value="">Toujours</option>
            {TAGS.map(([t, l]) => <option key={t} value={t}>{l}</option>)}
          </select>
          {tag && (
            <select aria-label="Valeur" value={value} onChange={(e) => setValue(e.target.value)} className={field}>
              {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          )}
        </fieldset>
        {rule && rule.confidence !== 'owner' && <p className="text-xs text-muted">L’enregistrer en fait ta règle : l’agent ne pourra plus la changer.</p>}
        {error && <p role="alert" className="text-danger">{error}</p>}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>Annuler</Button>
          <Button type="submit" variant="primary" loading={busy}>Enregistrer</Button>
        </div>
      </form>
    </Sheet>
  )
}

export default function Learnings() {
  const toast = useToast()
  const [filters, setFilters] = useState<LearningFilters>({})
  const [version, setVersion] = useState(0)
  const [sheet, setSheet] = useState<{ rule?: Learning }>()
  const [refreshing, setRefreshing] = useState(false)
  const s = useLoad(() => listLearnings(filters), `${JSON.stringify(filters)}|${version}`)
  const tax = useLoad(getTaxonomy, 'taxonomy').data
  const reload = () => setVersion((v) => v + 1)
  const pick = (key: keyof LearningFilters, value: string) =>
    setFilters(({ [key]: was, ...rest }) => (was === value ? rest : { ...rest, [key]: value }))
  const act: Act = (id, action) =>
    setLearning(id, action).then(reload, (e: unknown) => toast({ message: `Impossible d’enregistrer : ${errorMessage(e)}` }))
  const refresh = () => {
    setRefreshing(true)
    refreshLearnings().then(
      (r) => { toast({ message: `${r.evaluated} règle${r.evaluated > 1 ? 's vérifiées' : ' vérifiée'} avec les chiffres.` }); reload() },
      (e: unknown) => toast({ message: `Impossible de vérifier : ${errorMessage(e)}` }),
    ).finally(() => setRefreshing(false))
  }
  const filtered = Object.keys(filters).length > 0
  return (
    <section>
      <PageHeader title="Apprentissages" actions={<>
        <Button size="sm" variant="ghost" loading={refreshing} onClick={refresh}>Vérifier les chiffres</Button>
        <Button size="sm" variant="primary" onClick={() => setSheet({})}>Ajouter une règle</Button>
      </>}>
        Ce que le studio a appris de ton goût et de ton public. Tes modifications l’emportent toujours.
      </PageHeader>
      <div className="space-y-2">
        {FILTERS.map(([key, title, labels]) => (
          <div key={key} role="group" aria-label={title} className="flex flex-wrap items-center gap-2">
            <span className="w-full text-xs font-medium text-muted sm:w-24">{title}</span>
            {Object.entries(labels).map(([v, l]) => (
              <Chip key={v} pressed={filters[key] === v} onClick={() => pick(key, v)}>{l}</Chip>
            ))}
          </div>
        ))}
      </div>
      <div className="mt-5">
        <Body s={s} empty={() => false}>
          {(rows) => rows.length === 0
            ? (filtered
                ? <EmptyState title="Rien ne correspond à ces filtres." />
                : <EmptyState title="Pas encore d’apprentissages" action={<Button variant="primary" onClick={() => setSheet({})}>Ajouter une règle</Button>}>
                    L’agent les écrit à partir de tes commentaires et des chiffres. Tu peux ajouter tes propres règles, comme « jamais de rouge ».
                  </EmptyState>)
            : (
              <ul className="space-y-3">
                {rows.map((l) => <LearningCard key={l.id} l={l} tax={tax} onEdit={() => setSheet({ rule: l })} act={act} />)}
              </ul>
            )}
        </Body>
      </div>
      {sheet && <RuleSheet rule={sheet.rule} tax={tax} onClose={() => setSheet(undefined)} onSaved={() => { setSheet(undefined); reload() }} />}
    </section>
  )
}
