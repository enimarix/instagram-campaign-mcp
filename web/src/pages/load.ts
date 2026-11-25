// Shared by the analytics pages (078, 079): fetch state and number formats.
import { useEffect, useState } from 'react'
import { errorMessage, type AgentRun, type RetentionFinding } from '../api/client'
import type { Tone } from '../ui/styles'

// Chip tone per post verdict; the others are neutral.
export const VERDICT_TONE: Record<string, Tone | undefined> = { winner: 'success', promising: 'warn', weak: 'danger' }
/** A post's verdict (src/scoring.py) in the owner's words; an unknown one keeps its id. */
const VERDICT: Record<string, string> = {
  winner: 'gagnante', promising: 'prometteuse', average: 'moyenne', weak: 'faible', inconclusive: 'pas concluante',
  no_signal: 'sans signal', too_early: 'trop tôt', incomplete: 'incomplète', no_baseline: 'sans référence',
}
export const postVerdict = (v: string) => VERDICT[v] ?? v.replace('_', ' ')
/** Instagram's post types (the `group` of a post), Reel and Stories kept as Instagram says them. */
export const POST_TYPES: Record<string, string> = { REELS: 'Reels', TRIAL: 'Reels d’essai', FEED: 'Fil', STORY: 'Stories' }

// Chip tone and label per retention finding (111).
export const FINDING: Record<RetentionFinding['kind'], [Tone, string]> = {
  hook: ['warn', 'Accroche'], exit: ['neutral', 'Sortie'], payoff: ['warn', 'Chute'], strong: ['success', 'Point fort'],
}

// The tag dimensions of src/learning/breakdowns.py, in plain words (080, 084).
export const TAGS = [
  ['track', 'Piste'], ['pillar', 'Pilier'], ['hook_type', 'Type d’accroche'], ['template', 'Modèle'], ['style', 'Style'],
  ['strategy', 'Explorer / exploiter'], ['hour', 'Heure de publication'], ['duration', 'Durée'],
]
/** A tag dimension in plain words ("hook_type" → "Type d’accroche"). */
export const tagName = (id: string) => TAGS.find(([t]) => t === id)?.[1] ?? humanize(id)
// The fixed tag values of breakdowns.py; taxonomy values come from the taxonomy as they are.
const TAG_VALUES: Record<string, string> = { untagged: 'Sans tag', unknown: 'Inconnue', explore: 'Explorer', exploit: 'Exploiter' }
/** A tag value in plain words: the hour as "18:00", a template id as is, the rest humanized. */
export const tagValue = (tag: string, v: string | number) =>
  tag === 'hour' ? `${v}:00` : tag === 'template' ? String(v) : TAG_VALUES[v] ?? humanize(String(v))

export const num = (n: number | null | undefined) => (n == null ? '–' : n.toLocaleString('fr-FR'))
export const pct = (r: number | null | undefined) => (r == null ? '–' : `${Math.round(r * 100)} %`)

/** An instant in the browser's time zone, without seconds: "18 nov. 2026, 02:00". */
export const dateTime = (iso: string) => new Date(iso).toLocaleString('fr-FR', { dateStyle: 'medium', timeStyle: 'short' })
/** At most n characters, cut on a word (when the last space is past n/2), with … when cut. */
export const clip = (s: string, n: number) => {
  if (s.length <= n) return s
  const cut = s.lastIndexOf(' ', n - 1)
  return s.slice(0, cut > n / 2 ? cut : n - 1).trimEnd() + '…'
}
/** A taxonomy or API id in plain words: "hook_type" → "Hook type", "REELS" → "Reels". */
export const humanize = (id: string) => {
  const s = id.replace(/_/g, ' ').toLowerCase()
  return s.charAt(0).toUpperCase() + s.slice(1)
}
/** The agent's playbooks in the owner's words; unknown ones keep their file name. */
const PLAYBOOKS: Record<string, string> = {
  'daily-learn': 'Analyse de la nuit', 'daily-produce': 'Vidéos du jour', 'daily-revise': 'Tes changements',
  'check-renders': 'Vérifier les rendus', 'weekly-ads': 'Pubs de la semaine',
}
export const playbookName = (id: string) => PLAYBOOKS[id] ?? id
/** An agent run's status chip (Agent page, Settings' agent schedule). */
export const RUN_STATUS: Record<AgentRun['status'], [Tone, string]> = {
  running: ['info', 'en cours'], succeeded: ['success', 'réussi'], failed: ['danger', 'échoué'], cancelled: ['neutral', 'annulé'],
}

const pad = (n: number) => String(n).padStart(2, '0')
/** 754 → "12:34", 3725 → "1:02:05". */
export function clock(seconds: number) {
  const t = Math.floor(seconds)
  const h = Math.floor(t / 3600)
  const m = Math.floor((t % 3600) / 60)
  return h ? `${h}:${pad(m)}:${pad(t % 60)}` : `${m}:${pad(t % 60)}`
}

export type Load<T> = { data?: T; error?: string }
/** Fetches on mount and whenever `key` changes; a late answer for an old key is dropped. */
export function useLoad<T>(load: () => Promise<T>, key: unknown): Load<T> {
  const [state, setState] = useState<Load<T>>({})
  useEffect(() => {
    let live = true
    load().then((data) => live && setState({ data }), (e: unknown) => live && setState({ error: errorMessage(e) }))
    return () => {
      live = false
    }
    // `load` is a fresh closure each render; it only depends on `key`
    // oxlint-disable-next-line react-hooks/exhaustive-deps
  }, [key])
  return state
}
