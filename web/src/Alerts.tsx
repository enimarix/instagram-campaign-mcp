import { useEffect, useState } from 'react'
import { Link } from 'react-router'
import { dismissAlert, getAlerts, type Alert } from './api/client'
import { Button, IconButton } from './ui/Button'
import { EmptyState } from './ui/Card'
import { Chip } from './ui/Chip'
import { BellIcon } from './ui/icons'
import { Sheet } from './ui/Sheet'
import { link } from './ui/styles'

const POLL_MS = 60_000
const TONE = { info: 'info', warn: 'warn', error: 'danger' } as const
const LABEL = { info: 'Info', warn: 'Warning', error: 'Problem' } as const

/** The header bell (step 098): what needs attention, polled every minute while the page is visible. */
export default function Alerts() {
  const [alerts, setAlerts] = useState<Alert[]>([])
  const [open, setOpen] = useState(false)

  useEffect(() => {
    let timer: ReturnType<typeof setInterval> | undefined
    const load = () => getAlerts().then(setAlerts, () => {}) // keep the last list on a failed poll
    const sync = () => {
      clearInterval(timer)
      timer = undefined
      if (document.visibilityState === 'hidden') return
      load()
      timer = setInterval(load, POLL_MS)
    }
    sync()
    document.addEventListener('visibilitychange', sync)
    return () => {
      clearInterval(timer)
      document.removeEventListener('visibilitychange', sync)
    }
  }, [])

  function dismiss(id: string) {
    setAlerts((list) => list.filter((a) => a.id !== id))
    dismissAlert(id).catch(() => getAlerts().then(setAlerts, () => {}))
  }

  const n = alerts.length
  return (
    <>
      <IconButton variant="ghost" className="relative" onClick={() => setOpen(true)}
        label={n ? `Alerts: ${n} need${n === 1 ? 's' : ''} attention` : 'Alerts'}
        icon={<>
          <BellIcon />
          {n > 0 && (
            <span aria-hidden
              className="absolute top-1 right-1 grid min-w-5 place-items-center rounded-full bg-danger px-1 text-[11px] leading-5 font-bold text-on-accent">
              {n > 99 ? '99+' : n}
            </span>
          )}
        </>} />
      {open && (
        <Sheet title="Alerts" onClose={() => setOpen(false)}>
          {n === 0 ? (
            <div className="mt-4"><EmptyState title="All good">Nothing needs your attention.</EmptyState></div>
          ) : (
            <ul className="mt-3 max-h-[65dvh] divide-y divide-line/60 overflow-y-auto">
              {alerts.map((a) => (
                <li key={a.id} className="py-3">
                  <div className="flex items-start gap-2">
                    <Chip tone={TONE[a.severity]} className="mt-0.5 shrink-0">{LABEL[a.severity]}</Chip>
                    <div className="min-w-0 flex-1">
                      <p className="font-medium">{a.title}</p>
                      <p className="mt-0.5 text-sm break-words text-muted">{a.detail}</p>
                      <div className="mt-1 flex items-center gap-3">
                        <Link to={a.link} aria-label={`Open: ${a.title}`} className={`${link} text-sm`} onClick={() => setOpen(false)}>Open</Link>
                        {a.since && <span className="text-xs text-muted">{new Date(a.since).toLocaleString()}</span>}
                      </div>
                    </div>
                    <Button size="sm" variant="ghost" onClick={() => dismiss(a.id)}
                      aria-label={`Dismiss: ${a.title}`}>Dismiss</Button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Sheet>
      )}
    </>
  )
}
