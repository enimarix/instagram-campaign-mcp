import { MoonIcon, SunIcon } from './icons'
import { useTheme, type Theme } from './theme'

const OPTIONS: [Theme, string, typeof SunIcon][] = [['dark', 'Dark', MoonIcon], ['light', 'Light', SunIcon]]

/** Dark / Light switch; the choice is kept in this browser. */
export function ThemeToggle() {
  const [theme, setTheme] = useTheme()
  return (
    <div role="group" aria-label="Theme" className="inline-flex gap-1 rounded-control bg-surface-2 p-1">
      {OPTIONS.map(([t, label, Icon]) => (
        <button key={t} type="button" aria-pressed={theme === t} onClick={() => setTheme(t)}
          className={`inline-flex min-h-11 items-center gap-2 rounded-[0.5rem] px-3 text-sm font-medium transition ${
            theme === t ? 'bg-surface text-fg shadow-card' : 'text-muted hover:text-fg'
          }`}>
          <Icon className="size-4" />{label}
        </button>
      ))}
    </div>
  )
}
