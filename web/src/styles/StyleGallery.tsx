import { useEffect, useMemo, useState } from 'react'
import { errorMessage, listStyleCatalog, setStyleFavourite, type CatalogStyle, type StyleFamily } from '../api/client'
import { Button } from '../ui/Button'
import { EmptyState, Skeleton } from '../ui/Card'
import { Chip } from '../ui/Chip'
import { StarIcon } from '../ui/icons'
import { Sheet } from '../ui/Sheet'
import { field, link } from '../ui/styles'
import { useToast } from '../ui/useToast'

const FAMILY: Record<StyleFamily, string> = { studio: 'Studio', lemo: 'Lemo' }

/** Words in the name, essence, category or tags (the server's `q`, done here: the list is small). */
function matches(s: CatalogStyle, q: string) {
  const hay = [s.id, s.label, s.essence ?? '', s.category ?? '', ...s.tags].join(' ').toLowerCase()
  return q.toLowerCase().split(/\s+/).filter(Boolean).every((w) => hay.includes(w))
}

/** The poster, or a placeholder card with the style's name when none was fetched. */
function Poster({ style, className = '' }: { style: CatalogStyle; className?: string }) {
  const box = `aspect-video w-full rounded-control object-cover ${className}`
  return style.preview.poster ? <img src={style.preview.poster} alt="" loading="lazy" className={`${box} bg-surface-2`} />
    : (
      <div aria-hidden className={`${box} grid place-items-center bg-gradient-to-br from-accent/25 via-surface-2 to-explore/25 p-3 text-center text-sm font-semibold`}>
        {style.label}
      </div>
    )
}

function Star({ style, onToggle }: { style: CatalogStyle; onToggle: () => void }) {
  return (
    <button type="button" aria-pressed={style.favourite} aria-label={`Favori : ${style.label}`} title="Favori"
      onClick={(e) => { e.stopPropagation(); onToggle() }}
      className={`grid size-11 shrink-0 place-items-center rounded-full transition hover:bg-surface-2 ${style.favourite ? 'text-warn' : 'text-muted'}`}>
      <StarIcon fill={style.favourite ? 'currentColor' : 'none'} />
    </button>
  )
}

function StyleCard({ style, onOpen, onToggle, selected }: {
  style: CatalogStyle; onOpen: () => void; onToggle: () => void; selected?: boolean
}) {
  return (
    <li className={`flex flex-col overflow-hidden rounded-card border bg-surface shadow-card ${selected ? 'border-accent' : 'border-line/60'}`}>
      <button type="button" onClick={onOpen} aria-label={style.label} className="block text-left">
        <Poster style={style} className="rounded-none" />
      </button>
      <div className="flex items-start gap-1 p-2 pl-3">
        <button type="button" onClick={onOpen} tabIndex={-1} className="min-w-0 flex-1 text-left">
          <p className="truncate text-sm font-semibold">{style.label}</p>
          {style.essence && <p className="line-clamp-2 text-xs text-muted">{style.essence}</p>}
          <p className="mt-1 flex flex-wrap gap-1">
            <Chip tone={style.family === 'studio' ? 'accent' : 'explore'}>{FAMILY[style.family]}</Chip>
            {!style.selectable && <Chip tone="warn" title={style.why_not ?? undefined}>Non disponible</Chip>}
          </p>
        </button>
        <Star style={style} onToggle={onToggle} />
      </div>
    </li>
  )
}

function Detail({ style, onClose, onToggle, onSelect }: {
  style: CatalogStyle; onClose: () => void; onToggle: () => void; onSelect?: (id: string) => void
}) {
  const { poster, clip } = style.preview
  return (
    <Sheet title={style.label} onClose={onClose}>
      <div className="mt-3 space-y-3">
        {clip ? <video src={clip} poster={poster ?? undefined} controls muted playsInline preload="metadata"
          className="aspect-video w-full rounded-control bg-black" />
          : <Poster style={style} />}
        <p className="flex flex-wrap items-center gap-1">
          <Chip tone={style.family === 'studio' ? 'accent' : 'explore'}>{FAMILY[style.family]}</Chip>
          {style.category && <Chip>{style.category}</Chip>}
          {style.tags.map((t) => <Chip key={t}>{t}</Chip>)}
        </p>
        {style.essence && <p className="text-sm">{style.essence}</p>}
        {style.why_not && <p className="text-sm text-warn">{style.why_not}</p>}
        {style.credit && (
          <p className="text-xs text-muted">
            Aperçu : <a className={link} href={style.credit.url} target="_blank" rel="noreferrer">{style.credit.text}</a>,{' '}
            <a className={link} href={style.credit.licence_url} target="_blank" rel="noreferrer">{style.credit.licence}</a>
          </p>
        )}
        <div className="flex gap-2">
          <Button onClick={onToggle} aria-pressed={style.favourite}>
            <StarIcon fill={style.favourite ? 'currentColor' : 'none'} />
            {style.favourite ? 'Retirer des favoris' : 'Ajouter aux favoris'}
          </Button>
          {onSelect && (
            <Button variant="primary" disabled={!style.selectable} onClick={() => onSelect(style.id)}>
              Choisir ce style
            </Button>
          )}
        </div>
      </div>
    </Sheet>
  )
}

/** Every style (studio + Lemo-Opuscar) as cards: search, family and category filters, the
 * « Favoris » row first, a tap opens the detail sheet. With `onSelect` it is a picker (174):
 * the sheet gets « Choisir ce style » (only for selectable styles). */
export function StyleGallery({ onSelect, selectedId }: { onSelect?: (id: string) => void; selectedId?: string | null }) {
  const [all, setAll] = useState<CatalogStyle[]>()
  const [error, setError] = useState<string | null>(null)
  const [q, setQ] = useState('')
  const [family, setFamily] = useState<StyleFamily | null>(null)
  const [category, setCategory] = useState<string | null>(null)
  const [open, setOpen] = useState<string | null>(null)
  const toast = useToast()

  useEffect(() => {
    let live = true
    listStyleCatalog().then((s) => live && setAll(s), (e: unknown) => live && setError(errorMessage(e)))
    return () => { live = false }
  }, [])

  const categories = useMemo(() => [...new Set((all ?? [])
    .filter((s) => !family || s.family === family).map((s) => s.category).filter((c): c is string => !!c))], [all, family])
  const shown = (all ?? []).filter((s) => (!family || s.family === family) && (!category || s.category === category) && matches(s, q))
  const favs = shown.filter((s) => s.favourite)
  const rest = shown.filter((s) => !s.favourite)
  const current = all?.find((s) => s.id === open)

  const toggle = (s: CatalogStyle) => {
    const flip = (fav: boolean) => setAll((list) => list?.map((x) => (x.id === s.id ? { ...x, favourite: fav } : x)))
    flip(!s.favourite) // optimistic; put back if the server refuses
    setStyleFavourite(s.id, !s.favourite).catch((e: unknown) => {
      flip(s.favourite)
      toast({ message: `Favori non enregistré : ${errorMessage(e)}` })
    })
  }
  const grid = (list: CatalogStyle[]) => (
    <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
      {list.map((s) => <StyleCard key={s.id} style={s} selected={s.id === selectedId}
        onOpen={() => setOpen(s.id)} onToggle={() => toggle(s)} />)}
    </ul>
  )

  if (error) return <p role="alert" className="text-sm text-danger">Styles indisponibles : {error}</p>
  if (!all) return <Skeleton className="h-64" />
  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <input type="search" aria-label="Chercher un style" placeholder="Chercher : aquarelle, cartoon, carte…"
          value={q} onChange={(e) => setQ(e.target.value)} className={`${field} w-full`} />
        <div role="group" aria-label="Famille" className="flex gap-2 overflow-x-auto pb-1 [&>*]:shrink-0">
          <Chip pressed={family === null} onClick={() => { setFamily(null); setCategory(null) }}>Tous</Chip>
          {(Object.keys(FAMILY) as StyleFamily[]).map((f) => (
            <Chip key={f} pressed={family === f} onClick={() => { setFamily(f); setCategory(null) }}>{FAMILY[f]}</Chip>
          ))}
        </div>
        {categories.length > 0 && (
          <div role="group" aria-label="Catégorie" className="flex gap-2 overflow-x-auto pb-1 [&>*]:shrink-0">
            {categories.map((c) => (
              <Chip key={c} pressed={category === c} onClick={() => setCategory(category === c ? null : c)}>{c}</Chip>
            ))}
          </div>
        )}
      </div>
      {favs.length > 0 && (
        <section aria-label="Favoris">
          <h2 className="mb-2 font-semibold">Favoris</h2>
          {grid(favs)}
        </section>
      )}
      <section aria-label="Tous les styles">
        {favs.length > 0 && <h2 className="mb-2 font-semibold">Tous les styles</h2>}
        {rest.length ? grid(rest) : !favs.length && <EmptyState title="Aucun style">Rien ne correspond à ce filtre.</EmptyState>}
      </section>
      {current && <Detail style={current} onClose={() => setOpen(null)} onToggle={() => toggle(current)} onSelect={onSelect} />}
    </div>
  )
}
