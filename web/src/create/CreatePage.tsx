import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import {
  createVideo, errorMessage, getAsset, listStyleCatalog, listWorkOrders, restyleAsset,
  type Asset, type CatalogStyle, type WorkOrder,
} from '../api/client'
import { safeUrl } from '../inbox/ui'
import { StyleGallery } from '../styles/StyleGallery'
import { Button } from '../ui/Button'
import { Skeleton } from '../ui/Card'
import { Chip } from '../ui/Chip'
import { PageHeader } from '../ui/PageHeader'
import { Sheet } from '../ui/Sheet'
import { card, field, link } from '../ui/styles'
import { useToast } from '../ui/useToast'
import { Pile } from './Pile'
import {
  INSTRUCTION_MAX, instruction, LENGTH, MAX_STYLES, parsePrompt, planOrders, styleName, toggleStyle,
  type Address, type Draft, type Length,
} from './prompt'

const POLL_MS = 10_000 // while an order is still in the works
const OPEN: WorkOrder['status'][] = ['received', 'confirmed', 'needs_instruction', 'scheduled', 'in_production']

/** A studio video named in the prompt: its thumbnail and id, or « introuvable ». */
function VideoChip({ id, asset }: { id: number; asset: Asset | null | undefined }) {
  return (
    <li className="flex items-center gap-2 rounded-full border border-line bg-surface-2 py-1 pr-3 pl-1 text-xs">
      {asset?.thumbnail_url ? <img src={asset.thumbnail_url} alt="" className="size-8 rounded-full object-cover" />
        : <span aria-hidden className="size-8 rounded-full bg-line" />}
      <span className="font-semibold">#{id}</span>
      {asset === null ? <span className="text-danger">introuvable</span>
        : asset && <span className="max-w-40 truncate text-muted">{asset.caption ?? asset.status}</span>}
    </li>
  )
}

/** One choice of a small set, as chips; « Auto » (null) first. */
function Choice<T extends string>({ label, options, value, onChange }: {
  label: string; options: [T, string][]; value: T | null; onChange: (v: T | null) => void
}) {
  return (
    <div role="group" aria-label={label} className="flex flex-wrap items-center gap-2">
      <span className="text-sm font-medium">{label}</span>
      <Chip pressed={value === null} onClick={() => onChange(null)}>Auto</Chip>
      {options.map(([id, text]) => <Chip key={id} pressed={value === id} onClick={() => onChange(id)}>{text}</Chip>)}
    </div>
  )
}

/** The style picker: Auto, the favourites, the styles picked in the gallery; up to MAX_STYLES (one video each). */
function StylesField({ catalog, value, onChange, onGalleryClosed }: {
  catalog?: CatalogStyle[]; value: (string | null)[]; onChange: (v: (string | null)[]) => void; onGalleryClosed: () => void
}) {
  const [gallery, setGallery] = useState(false)
  const favs = (catalog ?? []).filter((s) => s.favourite && s.selectable).map((s) => s.id)
  const shown = [...favs, ...value.filter((id): id is string => id !== null && !favs.includes(id))]
  const full = value.length >= MAX_STYLES
  const close = () => { setGallery(false); onGalleryClosed() }
  return (
    <div>
      <p className="text-sm font-medium">Style <span className="font-normal text-muted">(plusieurs : une vidéo par style, {MAX_STYLES} au plus)</span></p>
      <div role="group" aria-label="Style" className="mt-1 flex flex-wrap gap-2">
        <Chip pressed={value.includes(null)} onClick={() => onChange(toggleStyle(value, null))}>Auto (l'IA choisit)</Chip>
        {shown.map((id) => (
          <Chip key={id} pressed={value.includes(id)} onClick={() => onChange(toggleStyle(value, id))}>{styleName(catalog, id)}</Chip>
        ))}
        <Button onClick={() => setGallery(true)}>Tous les styles</Button>
      </div>
      {full && <p className="mt-1 text-xs text-muted">{MAX_STYLES} styles au plus : retire-en un pour en choisir un autre.</p>}
      {gallery && (
        <Sheet title="Tous les styles" wide onClose={close}>
          <div className="mt-3">
            <StyleGallery selectedId={null} onSelect={(id) => { onChange(value.includes(id) ? value : toggleStyle(value, id)); close() }} />
          </div>
        </Sheet>
      )}
    </div>
  )
}

const EMPTY: Draft = { text: '', styles: [null], address: null, length: null }

/** /create « Créer » (174): prompt new videos (text, #IDs of our videos, a Reel link), pick
 * one or more styles, send; below, la pile: every order and where it stands, refreshed live. */
export default function CreatePage() {
  const [draft, setDraft] = useState<Draft>(EMPTY)
  const [assets, setAssets] = useState<Record<number, Asset | null>>({})
  const [catalog, setCatalog] = useState<CatalogStyle[]>()
  const [orders, setOrders] = useState<WorkOrder[]>()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [pileError, setPileError] = useState<string | null>(null)
  const toast = useToast()
  const set = (patch: Partial<Draft>) => setDraft((d) => ({ ...d, ...patch }))

  const loadCatalog = useCallback(() => listStyleCatalog().then(setCatalog, () => setCatalog([])), [])
  const reload = useCallback(() => listWorkOrders('mine').then((o) => {
    setOrders(o)
    setPileError(null)
  }, (e: unknown) => setPileError(errorMessage(e))), [])
  useEffect(() => { void loadCatalog(); void reload() }, [loadCatalog, reload])
  useEffect(() => {
    if (!orders?.some((o) => OPEN.includes(o.status))) return
    const t = setInterval(() => void reload(), POLL_MS) // a failed reload does not stop it
    return () => clearInterval(t)
  }, [orders, reload])

  const { ids, reel } = parsePrompt(draft.text)
  const key = ids.join(',')
  const asked = useRef(new Set<number>())
  useEffect(() => { // each id once: its thumbnail, or null (no such video)
    for (const id of key ? key.split(',').map(Number) : []) {
      if (asked.current.has(id)) continue
      asked.current.add(id)
      getAsset(id).then((a) => setAssets((m) => ({ ...m, [id]: a })), () => setAssets((m) => ({ ...m, [id]: null })))
    }
  }, [key])

  const plan = draft.text.trim() ? planOrders(draft) : []
  const length = instruction(draft).length
  const missing = ids.filter((id) => assets[id] === null)
  const tooLong = plan[0]?.kind === 'create' && length > INSTRUCTION_MAX
  const blocked = !plan.length || missing.length > 0 || tooLong

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    const failed: string[] = []
    const left = new Set<string | null>()
    for (const o of plan) {
      try {
        if (o.kind === 'restyle') await restyleAsset(o.assetId, { style: o.style, ...(o.note && { note: o.note }) })
        else await createVideo({ instruction: o.instruction, style: o.style })
      } catch (err) {
        failed.push(`${o.kind === 'restyle' ? `#${o.assetId}, ` : ''}${styleName(catalog, o.style)} : ${errorMessage(err)}`)
        left.add(o.style)
      }
    }
    setBusy(false)
    const sent = plan.length - failed.length
    if (sent) toast({ message: sent > 1 ? `${sent} vidéos dans la pile.` : 'Vidéo dans la pile.' })
    if (failed.length) setError(failed.join('\n'))
    // what went through is never sent twice: with one order per style only the failed styles
    // stay; a restyle of several videos (orders per video and style) is cleared once one went
    const perStyle = plan.length === draft.styles.length
    if (!failed.length || (sent && !perStyle)) setDraft(EMPTY)
    else if (sent) set({ styles: draft.styles.filter((s) => left.has(s)) })
    void reload()
  }

  const reelHref = safeUrl(reel)
  return (
    <>
      <PageHeader title="Créer">Demande une vidéo : elle rejoint la pile, l'IA l'écrit, le studio la rend, puis elle arrive dans l'Inbox.</PageHeader>
      <form lang="fr" onSubmit={(e) => void submit(e)} className={`${card} space-y-4 p-4`}>
        <label className="block text-sm font-medium">Quelle vidéo ?
          <textarea value={draft.text} rows={4} onChange={(e) => set({ text: e.target.value })}
            placeholder="Ex. : pourquoi on a faim le soir en sèche. Ou #17 pour refaire une de nos vidéos, ou colle un lien de Reel."
            className={`${field} mt-1 block w-full py-2 text-base`} />
        </label>
        {(ids.length > 0 || reelHref) && (
          <ul aria-label="Références" className="flex flex-wrap gap-2">
            {ids.map((id) => <VideoChip key={id} id={id} asset={assets[id]} />)}
            {reelHref && (
              <li className="flex items-center rounded-full border border-line bg-surface-2 px-3 py-1 text-xs">
                <a href={reelHref} target="_blank" rel="noopener noreferrer" className={link}>Reel Instagram</a>
              </li>
            )}
          </ul>
        )}
        {plan[0]?.kind === 'restyle' && <p className="text-xs text-muted">Même vidéo, autre style : chaque vidéo citée est refaite dans le style choisi.</p>}
        <StylesField catalog={catalog} value={draft.styles} onChange={(styles) => set({ styles })} onGalleryClosed={() => void loadCatalog()} />
        <Choice label="Adresse" options={[['tu', 'Tu'], ['vous', 'Vous']] as [Address, string][]} value={draft.address}
          onChange={(address) => set({ address })} />
        <Choice label="Durée" options={Object.entries(LENGTH).map(([id, [text]]) => [id as Length, text])} value={draft.length}
          onChange={(length) => set({ length })} />
        {tooLong && <p className="text-sm text-danger">Trop long : {length}/{INSTRUCTION_MAX} caractères.</p>}
        {missing.length > 0 && <p className="text-sm text-danger">Pas de vidéo {missing.map((i) => `#${i}`).join(', ')} dans le studio.</p>}
        {error && <p role="alert" className="text-sm whitespace-pre-line text-danger">{error}</p>}
        <Button type="submit" variant="primary" size="lg" loading={busy} disabled={blocked} className="w-full">
          {plan.length > 1 ? `Envoyer (${plan.length} vidéos)` : 'Envoyer'}
        </Button>
      </form>

      <h2 className="mt-8 mb-3 text-lg font-semibold">La pile</h2>
      {pileError && <p role="alert" className="text-sm text-danger">{pileError}</p>}
      {orders === undefined ? !pileError && <Skeleton className="h-40" />
        : <Pile orders={orders} catalog={catalog} onChanged={() => void reload()} />}
    </>
  )
}
