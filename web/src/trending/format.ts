// The Trending page's words and formats (French: the owner's page, step 135).
import type { WorkMode, WorkOrder } from '../api/client'
import type { Tone } from '../ui/styles'

export const MODES: { id: WorkMode; label: string; hint: string }[] = [
  { id: 'inspired', label: 'Inspiré', hint: "Une vidéo originale sur la même idée : rien du Reel n'est repris." },
  { id: 'react', label: 'Réaction', hint: 'Un remix commenté du Reel, avec le crédit du créateur.' },
]
export const modeLabel = (m: WorkMode | null) => MODES.find((x) => x.id === m)?.label ?? null

/** Only Instagram's own embed pages go in an iframe. */
export const embedSrc = (url: string | null | undefined) =>
  url && url.startsWith('https://www.instagram.com/') ? url : null

const COMPACT = new Intl.NumberFormat('fr', { notation: 'compact', maximumFractionDigits: 1 })
export const compact = (n: number) => COMPACT.format(n)

const RTF = new Intl.RelativeTimeFormat('fr', { numeric: 'auto', style: 'short' })
const UNITS = [['day', 86400], ['hour', 3600], ['minute', 60]] as const
/** "il y a 2 h", "hier", "à l'instant". */
export function ago(iso: string, now = Date.now()) {
  const s = (new Date(iso).getTime() - now) / 1000
  for (const [unit, secs] of UNITS) if (Math.abs(s) >= secs) return RTF.format(Math.round(s / secs), unit)
  return "à l'instant"
}

/** The order's status chip; a blocked order that is not done shows Bloqué. */
export function orderStatus(o: Pick<WorkOrder, 'status' | 'blocked_reason'>): [string, Tone] {
  if (o.blocked_reason && !['in_feed', 'analysed', 'skipped'].includes(o.status)) return ['Bloqué', 'danger']
  return ORDER_STATUS[o.status]
}
const ORDER_STATUS: Record<WorkOrder['status'], [string, Tone]> = {
  needs_instruction: ["En attente d'instruction", 'warn'],
  scheduled: ['Programmé', 'info'],
  in_production: ['En production', 'explore'],
  in_feed: ['Dans ton feed', 'success'],
  analysed: ['Analysé', 'success'],
  skipped: ['Ignoré', 'neutral'],
}
/** The open order of a feed Reel (134: new or in_production). */
export const FEED_ORDER: Record<'new' | 'in_production', [string, Tone]> = {
  new: ['Envoyé au travail', 'info'],
  in_production: ['En production', 'explore'],
}
