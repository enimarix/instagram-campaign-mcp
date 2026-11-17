import type { KeyboardEvent, ReactNode } from 'react'

type Props<T extends string> = {
  label: string
  tabs: { id: T; label: ReactNode }[]
  value: T
  onChange: (id: T) => void
}

/** A segmented tab bar (role tablist); arrow keys move between tabs. */
export function Tabs<T extends string>({ label, tabs, value, onChange }: Props<T>) {
  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    const step = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0
    if (!step) return
    const i = (tabs.findIndex((t) => t.id === value) + step + tabs.length) % tabs.length
    onChange(tabs[i].id)
    e.currentTarget.querySelectorAll<HTMLElement>('[role=tab]')[i]?.focus()
  }
  return (
    <div role="tablist" aria-label={label} onKeyDown={onKeyDown} className="flex gap-1 rounded-control bg-surface-2 p-1">
      {tabs.map((t) => {
        const on = t.id === value
        return (
          <button key={t.id} type="button" role="tab" aria-selected={on} tabIndex={on ? 0 : -1}
            onClick={() => onChange(t.id)}
            className={`min-h-11 flex-1 rounded-[0.5rem] px-3 text-sm font-medium transition ${
              on ? 'bg-surface text-fg shadow-card' : 'text-muted hover:text-fg'
            }`}>
            {t.label}
          </button>
        )
      })}
    </div>
  )
}
