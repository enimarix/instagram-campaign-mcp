import { useState } from 'react'

export type Theme = 'dark' | 'light'
// index.html reads the same key before the first paint (no flash of the wrong theme).
const KEY = 'studio.theme'

const current = (): Theme => (document.documentElement.dataset.theme === 'light' ? 'light' : 'dark')

/** The theme on <html data-theme>, and a setter that also remembers it in localStorage. */
export function useTheme() {
  const [theme, set] = useState(current)
  function setTheme(t: Theme) {
    document.documentElement.dataset.theme = t
    localStorage.setItem(KEY, t)
    set(t)
  }
  return [theme, setTheme] as const
}
