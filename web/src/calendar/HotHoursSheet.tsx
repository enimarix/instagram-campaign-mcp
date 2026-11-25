import { useEffect, useState } from 'react'
import { errorMessage, getHotHours, reschedulePost, type HotHours } from '../api/client'
import { inputValue, localDate } from '../inbox/ui'
import { Button } from '../ui/Button'
import { Sheet } from '../ui/Sheet'
import { field } from '../ui/styles'
import { dayLabel } from './when'

type Props = {
  post: { id: number; publish_at: string }
  onSaved: () => void // after a reschedule went through
  onClose: () => void
}

// Reschedule a pending post (owner, 169): days × hours of the next two weeks, each hour shaded
// by followers online (the planner's audience data), the best ones 🔥, hours of other queued
// posts taken. Picking an hour fills the time; its minutes stay editable before Save.
export default function HotHoursSheet({ post, onSaved, onClose }: Props) {
  const [grid, setGrid] = useState<HotHours | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [day, setDay] = useState(() => localDate(new Date(post.publish_at)))
  const [when, setWhen] = useState(() => inputValue(new Date(post.publish_at)))

  useEffect(() => {
    getHotHours().then(setGrid, (e: unknown) => setError(errorMessage(e)))
  }, [])

  const days = grid?.days.filter((d) => d.hours.length) ?? []
  const shown = days.find((d) => d.date === day) ?? days[0]
  const save = async () => {
    setError(null)
    try {
      await reschedulePost(post.id, new Date(when).toISOString())
      onSaved()
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  return (
    <Sheet title="Changer l’heure" onClose={onClose}>
      {error && <p role="alert" className="mt-2 text-sm text-danger">{error}</p>}
      {grid && (
        <p className="mt-1 text-xs text-muted">
          {grid.has_data
            ? '🔥 = le plus d’abonnés en ligne (4 dernières semaines). Plus la couleur est forte, plus il y a d’abonnés en ligne.'
            : `Pas encore de données d’audience : 🔥 marque les créneaux de publication prévus (${grid.posting_windows}).`}
        </p>
      )}
      <div role="group" aria-label="Jour" className="mt-3 flex gap-1 overflow-x-auto pb-1">
        {days.map((d) => (
          <Button key={d.date} size="sm" variant={d === shown ? 'primary' : 'secondary'}
            aria-pressed={d === shown} className="shrink-0" onClick={() => setDay(d.date)}>
            {dayLabel(d.date)}
          </Button>
        ))}
      </div>
      <div role="group" aria-label="Heure" className="mt-2 grid grid-cols-4 gap-1">
        {shown?.hours.map((h) => {
          const taken = h.taken.some((id) => id !== post.id)
          const at = inputValue(new Date(h.publish_at))
          const picked = when.slice(0, 13) === at.slice(0, 13)
          return (
            <button key={h.publish_at} type="button" disabled={taken}
              aria-label={`${h.local.slice(11, 16)}${h.hot ? ' chaude' : ''}${taken ? ' prise' : ''}`}
              aria-pressed={picked}
              title={h.followers == null ? undefined : `${Math.round(h.followers)} abonnés en ligne`}
              onClick={() => setWhen(at)}
              style={{ backgroundColor: `color-mix(in oklab, var(--color-accent) ${Math.round(h.score * 45)}%, var(--color-surface-2))` }}
              className={`min-h-11 rounded-control text-xs tabular-nums disabled:opacity-40 ${picked ? 'ring-2 ring-accent' : ''}`}>
              {h.local.slice(11, 16)}{h.hot && ' 🔥'}
              {taken && <span className="block text-[10px] text-muted">prise</span>}
            </button>
          )
        })}
      </div>
      <label className="mt-3 block text-xs font-medium">
        Nouvelle heure
        <input type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)}
          className={`${field} mt-1 block w-full px-2 font-normal`} />
      </label>
      <div className="mt-3 flex justify-end gap-2">
        <Button variant="ghost" onClick={onClose}>Fermer</Button>
        <Button variant="primary" disabled={!when} onClick={save}>Enregistrer</Button>
      </div>
    </Sheet>
  )
}
