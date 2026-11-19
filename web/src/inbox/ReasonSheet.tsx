import { useEffect, useRef, useState } from 'react'
import type { CommentIn, Vocabulary } from '../api/client'
import { StylePicker } from '../launch/StylePicker'
import { Button } from '../ui/Button'
import { Chip } from '../ui/Chip'
import { Sheet } from '../ui/Sheet'
import { field } from '../ui/styles'
import { clock } from './ui'

type Props = {
  reasons: Vocabulary['values']
  /** Change: the playback time when the sheet opened, for the optional pin. Without it the
   * sheet is Decline's: the motive the agent learns from (133), no pin. */
  at?: number
  onSave: (fb: CommentIn) => void
  onClose: () => void
  /** Change only: « même vidéo, autre style » (138), a new work order, this video stays.
   * style null: another one the AI picks; `style` here: the video's own (not offered). */
  onRestyle?: (style: string | null) => void
  style?: string | null
}

// Change or Decline: what is wrong (chips and/or text, at least one), for Change
// optionally pinned to a moment. Change asks for a new version (wants_changes); the agent
// reworks it. Decline's text is a big field that phone dictation fills.
export default function ReasonSheet({ reasons, at, onSave, onClose, onRestyle, style }: Props) {
  const decline = at === undefined
  const [picked, setPicked] = useState<string[]>([])
  const [restyling, setRestyling] = useState(false) // the style buttons load when opened
  const [newStyle, setNewStyle] = useState<string | null>(null)
  const [text, setText] = useState('')
  const [pin, setPin] = useState(false)
  const input = useRef<HTMLTextAreaElement>(null)

  // Desktop: type the motive at once. Deferred: the Sheet opens its dialog (and moves the
  // focus into it) after this effect. Not on a phone, where the keyboard would cover the chips.
  useEffect(() => {
    if (!decline || !window.matchMedia?.('(pointer: fine)').matches) return
    const t = setTimeout(() => input.current?.focus())
    return () => clearTimeout(t)
  }, [decline])

  const toggle = (id: string) =>
    setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]))

  return (
    <Sheet title={decline ? 'Why decline?' : 'What should change?'} onClose={onClose}>
      <div role="group" aria-label="Reasons" className="mt-4 flex flex-wrap gap-2">
        {reasons.map((r) => (
          <Chip key={r.id} tone="danger" pressed={picked.includes(r.id)} onClick={() => toggle(r.id)}>
            {r.label}
          </Chip>
        ))}
        {!decline && <Chip tone="accent" pressed={pin} onClick={() => setPin((p) => !p)}>at {clock(at)}</Chip>}
      </div>
      <textarea ref={input} aria-label={decline ? 'Pourquoi ?' : 'What to change'} value={text}
        onChange={(e) => setText(e.target.value)} rows={decline ? 4 : 2}
        placeholder={decline ? 'Pourquoi ?' : 'Same video, shorter hook…'}
        className={`${field} mt-3 block w-full py-2 ${decline ? 'min-h-32 md:min-h-0' : ''}`} />
      <div className="mt-5 grid grid-cols-2 gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant={decline ? 'danger' : 'primary'} disabled={!picked.length && !text.trim()}
          onClick={() => onSave({
            reason_codes: picked,
            ...(text.trim() && { text: text.trim() }),
            ...(pin && !decline && { video_time_s: at }),
            ...(!decline && { wants_changes: true }),
          })}>
          {decline ? 'Decline' : 'Send for changes'}
        </Button>
      </div>
      {!decline && onRestyle && (
        <details lang="fr" onToggle={(e) => setRestyling(e.currentTarget.open)}
          className="mt-5 rounded-control border border-line p-3">
          <summary className="min-h-6 cursor-pointer font-medium">Même vidéo, autre style</summary>
          {restyling && (
            <div className="mt-2 space-y-3">
              <StylePicker value={newStyle} onChange={setNewStyle} autoLabel="Au choix de l'IA" exclude={style} />
              <Button variant="primary" className="w-full" onClick={() => onRestyle(newStyle)}>Refaire dans ce style</Button>
            </div>
          )}
        </details>
      )}
    </Sheet>
  )
}
