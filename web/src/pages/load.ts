// Shared by the analytics pages (078, 079): fetch state and number formats.
import { useEffect, useState } from 'react'
import { errorMessage } from '../api/client'
import type { Tone } from '../ui/styles'

// Chip tone per post verdict; the others are neutral.
export const VERDICT_TONE: Record<string, Tone | undefined> = { winner: 'success', promising: 'warn', weak: 'danger' }

export const num = (n: number | null | undefined) => (n == null ? '–' : n.toLocaleString('en'))
export const pct = (r: number | null | undefined) => (r == null ? '–' : `${Math.round(r * 100)} %`)

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
