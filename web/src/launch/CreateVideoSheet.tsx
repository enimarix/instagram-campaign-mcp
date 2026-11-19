import { useState, type FormEvent } from 'react'
import { createVideo, errorMessage } from '../api/client'
import { Button } from '../ui/Button'
import { Sheet } from '../ui/Sheet'
import { field } from '../ui/styles'
import { StylePicker } from './StylePicker'

/** « Créer une vidéo » (step 138): a topic or an instruction, a style (or Auto) -> a work
 * order the AI starts at once; it shows in Mes envois. */
export default function CreateVideoSheet({ onClose, onSent }: { onClose: () => void; onSent: () => void }) {
  const [text, setText] = useState('')
  const [style, setStyle] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await createVideo({ instruction: text.trim(), style })
      onSent()
    } catch (err) {
      setError(errorMessage(err))
      setBusy(false)
    }
  }

  return (
    <Sheet title="Créer une vidéo" onClose={onClose}>
      <form lang="fr" onSubmit={(e) => void submit(e)} className="mt-3 space-y-3">
        <label className="block text-sm font-medium">Le sujet ou ta consigne
          <textarea required value={text} maxLength={500} rows={5} onChange={(e) => setText(e.target.value)}
            placeholder="Ex. : pourquoi on a faim le soir en sèche (tu peux dicter)"
            className={`${field} mt-1 block w-full py-2 text-base`} />
        </label>
        <p className="text-right text-xs text-muted tabular-nums">{text.length}/500</p>
        <StylePicker value={style} onChange={setStyle} />
        {error && <p role="alert" className="text-sm text-danger">{error}</p>}
        <Button type="submit" variant="primary" size="lg" loading={busy} disabled={!text.trim()} className="w-full">
          Envoyer à l'IA
        </Button>
      </form>
    </Sheet>
  )
}
