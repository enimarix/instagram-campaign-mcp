// Shared by the analytics pages (078, 079): fetch state and number formats.
import { useEffect, useState } from 'react'
import { errorMessage } from '../api/client'
import type { Tone } from '../ui/styles'

// Chip tone per post verdict; the others are neutral.
export const VERDICT_TONE: Record<string, Tone | undefined> = { winner: 'success', promising: 'warn', weak: 'danger' }

export const num = (n: number | null | undefined) => (n == null ? '–' : n.toLocaleString('en'))
export const pct = (r: number | null | undefined) => (r == null ? '–' : `${Math.round(r * 100)} %`)

/** An instant in the browser's time zone, without seconds: "Nov 18, 2026, 2:00 AM". */
export const dateTime = (iso: string) => new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
/** A taxonomy or API id in plain words: "hook_type" → "Hook type", "REELS" → "Reels". */
export const humanize = (id: string) => {
  const s = id.replace(/_/g, ' ').toLowerCase()
  return s.charAt(0).toUpperCase() + s.slice(1)
}
/** The agent's playbooks in the owner's words; unknown ones keep their file name. */
const PLAYBOOKS: Record<string, string> = {
  'daily-produce': 'Daily videos', 'daily-revise': 'Change requests', 'daily-learn': 'Nightly analysis',
}
export const playbookName = (id: string) => PLAYBOOKS[id] ?? id

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
