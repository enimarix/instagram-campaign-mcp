// Shared helpers of the web pages (styles live in ../ui/).
import type { Asset, Vocabulary } from '../api/client'
import { dayLabel, slotLabel } from '../calendar/when'

/** Only http(s) links are rendered: agent-written URLs could carry `javascript:`. */
export const safeUrl = (url?: string | null) => (url && /^https?:\/\//i.test(url) ? url : null)

/** "2026-11-18T11:00:00+01:00" → "aujourd’hui 11:00", "demain 11:00" or "mer. 18 nov. 11:00":
 * the owner's wall-clock time as sent, today/tomorrow as the browser sees them. */
export function wallClock(iso: string, now = new Date()) {
  const [day, time] = [iso.slice(0, 10), iso.slice(11, 16)]
  const tomorrow = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1)
  return day === localDate(now) ? `aujourd’hui ${time}` : day === localDate(tomorrow) ? `demain ${time}` : slotLabel(iso)
}

const pad = (n: number) => String(n).padStart(2, '0')
/** A Date as YYYY-MM-DD in the browser's time zone. */
export const localDate = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
/** A Date as a <input type="datetime-local"> value, in the browser's time zone. */
export const inputValue = (d: Date) => `${localDate(d)}T${pad(d.getHours())}:${pad(d.getMinutes())}`
/** Seconds as "0:07", a moment of the video. */
export const clock = (s: number) => `${Math.floor(s / 60)}:${pad(Math.floor(s % 60))}`
/** Shown for AI-made videos (GOAL §5.6): the publish sends Instagram's AI label. */
export const AI_LABEL_LINE = 'Publiée avec l’étiquette IA d’Instagram'
/** What the owner confirms before a `commentary` video is queued (GOAL.md §5.1). */
export const COMMENTARY_CONFIRMATION =
  'J’ai vérifié cette vidéo de réaction : mon avis en est une part importante et le créateur est crédité.'

/** A video's status, verdict and rights in the owner's words. */
const STATUS: Record<string, string> = {
  rendering: 'en rendu', ready: 'à décider', failed: 'échouée', needs_reaction: 'réaction à faire',
  revision_requested: 'renvoyée pour changements', approved: 'approuvée', scheduled: 'programmée',
  publish_check: 'en vérification avant publication', published: 'publiée', archived: 'archivée',
}
const VERDICT: Record<string, string> = { liked: 'gardée', disliked: 'refusée' }
const RIGHTS: Record<string, string> = {
  own: 'à nous', licensed: 'sous licence', public_domain: 'domaine public', cc: 'Creative Commons',
  permission: 'avec permission', commentary: 'commentaire', unknown: 'inconnus',
}
const word = (map: Record<string, string>) => (v: string) => map[v] ?? v.replace('_', ' ')
export const statusLabel = word(STATUS)
export const verdictLabel = word(VERDICT)
export const rightsLabel = word(RIGHTS)
/** "2026-11-30" → "à publier avant le lun. 30 nov." */
export const bestBeforeLabel = (d: string) => `à publier avant le ${dayLabel(d)}`

/** "Changé : « shorter hook »" on a revised video (133): the owner's own words, else the
 * labels of the reasons they picked; null when the video is not a revision. */
export function changeLabel(req: Asset['change_request'], reasons: Vocabulary['values'] = []) {
  const words = req && (req.text?.trim() ||
    req.reason_codes.map((c) => reasons.find((r) => r.id === c)?.label ?? c).join(', '))
  return words ? `Changé : « ${words} »` : null
}
