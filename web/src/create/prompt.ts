// « Créer » (step 174): what the owner typed -> the orders to send; the pile's words.
import type { CatalogStyle, WorkOrder } from '../api/client'
import type { Tone } from '../ui/styles'

export const MAX_STYLES = 4
export const INSTRUCTION_MAX = 500 // work_orders.INSTRUCTION_MAX

export type Address = 'tu' | 'vous'
export type Length = 'court' | 'moyen' | 'long'
export const ADDRESS: Record<Address, string> = { tu: 'Tutoiement (tu).', vous: 'Vouvoiement (vous).' }
export const LENGTH: Record<Length, [string, string]> = {
  court: ['Court (~20 s)', 'Durée visée : environ 20 s.'],
  moyen: ['Moyen (~40 s)', 'Durée visée : environ 40 s.'],
  long: ['Long (~60 s)', 'Durée visée : environ 60 s.'],
}

// #17 or a pasted asset link (…/assets/17); an Instagram Reel or post link
const ASSET_REF = /(?:#|\/assets\/)(\d+)\b/g
const ASSET_LINK = /\S*\/assets\/\d+\S*/g
const REEL = /https?:\/\/(?:www\.)?instagram\.com\/(?:reels?|p)\/[\w-]+\/?\S*/

/** The studio videos it names, the Reel link and the owner's own words (the rest). */
export function parsePrompt(text: string) {
  const ids = [...new Set([...text.matchAll(ASSET_REF)].map((m) => Number(m[1])))]
  const reel = text.match(REEL)?.[0] ?? null
  const words = text.replace(REEL, '').replace(ASSET_LINK, '').replace(/#\d+\b/g, '').trim()
  return { ids, reel, words }
}

export type Draft = { text: string; styles: (string | null)[]; address: Address | null; length: Length | null }
export type Planned =
  | { kind: 'restyle'; assetId: number; style: string | null; note?: string }
  | { kind: 'create'; instruction: string; style: string | null }

/** The instruction a create order carries: the owner's text, what its references are, the address and length. */
export function instruction(d: Draft) {
  const { ids, reel } = parsePrompt(d.text)
  return [
    d.text.trim(),
    ids.length > 0 && `(${ids.map((i) => `#${i}`).join(', ')} : vidéo${ids.length > 1 ? 's' : ''} du studio, id d'asset ; base-toi dessus.)`,
    reel && '(Le lien Instagram est un Reel de référence.)',
    d.address && ADDRESS[d.address],
    d.length && LENGTH[d.length][1],
  ].filter(Boolean).join(' ')
}

/** One order per style (null: Auto). Only video IDs and no words: « même vidéo, autre style »
 * of each (restyle); otherwise a new video whose instruction names them. */
export function planOrders(d: Draft): Planned[] {
  const { ids, reel, words } = parsePrompt(d.text)
  const styles = d.styles.length ? d.styles : [null]
  if (ids.length && !words && !reel) {
    const note = [d.address && ADDRESS[d.address], d.length && LENGTH[d.length][1]].filter(Boolean).join(' ') || undefined
    return ids.flatMap((assetId) => styles.map((style) => ({ kind: 'restyle' as const, assetId, style, note })))
  }
  const text = instruction(d)
  return styles.map((style) => ({ kind: 'create' as const, instruction: text, style }))
}

/** Toggle a style (null: Auto) in the selection; none left = Auto. Auto alone gives way to the first style picked. */
export function toggleStyle(list: (string | null)[], id: string | null): (string | null)[] {
  if (list.includes(id)) {
    const rest = list.filter((s) => s !== id)
    return rest.length ? rest : [null]
  }
  if (list.length === 1 && list[0] === null && id !== null) return [id]
  return list.length >= MAX_STYLES ? list : [...list, id]
}

export const styleName = (catalog: CatalogStyle[] | undefined, id: string | null) =>
  id ? (catalog?.find((s) => s.id === id)?.label ?? id) : "Auto (l'IA choisit)"

/** Where the order is: waiting -> the AI writes / the Lemo film is made -> render -> in the Inbox,
 * or refused (the AI) / failed (the film engine). */
export function stage(o: WorkOrder): [string, Tone] {
  const film = o.style?.startsWith('lemo:')
  switch (o.status) {
    case 'received': return ['À confirmer dans Reçus', 'warn']
    case 'confirmed': return ['Attend ton « Lancer » (Planning)', 'info']
    case 'scheduled': return o.blocked_reason ? ['En attente (bloqué)', 'warn'] : ['En attente', 'info']
    case 'in_production':
      if (o.video_status === 'rendering') return ['Rendu en cours', 'explore']
      if (o.video_status === 'failed') return ['Rendu échoué', 'danger']
      if (o.video_status) return ['Rendu', 'explore']
      return film ? ['Le film se fabrique', 'explore'] : ["L'IA écrit", 'explore']
    case 'in_feed': return ["Dans l'Inbox", 'success']
    case 'analysed': return ['Analysé', 'success']
    case 'skipped': return film ? ['Échoué', 'danger'] : ["Refusé par l'IA", 'danger']
  }
}
