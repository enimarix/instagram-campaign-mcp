import { useCallback, useRef, useState, type ReactNode } from 'react'
import { ToastContext, type ToastInput } from './useToast'

const MAX = 3

/** Holds the toasts above the bottom tab bar (phone) or at the bottom (desktop). */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<(ToastInput & { id: number })[]>([])
  const nextId = useRef(0)

  const dismiss = (id: number) => setToasts((ts) => ts.filter((t) => t.id !== id))
  const show = useCallback((t: ToastInput) => {
    const id = ++nextId.current
    setToasts((ts) => [...ts.slice(1 - MAX), { ...t, id }])
    setTimeout(() => dismiss(id), t.duration ?? 5000)
  }, [])

  return (
    <ToastContext value={show}>
      {children}
      <div aria-live="polite"
        className="pointer-events-none fixed inset-x-0 bottom-[calc(5rem+env(safe-area-inset-bottom))] z-50 flex flex-col items-center gap-2 px-4 lg:bottom-6">
        {toasts.map((t) => (
          <div key={t.id} role="status"
            className="pointer-events-auto flex w-full max-w-sm animate-toast-in items-center gap-3 rounded-card border border-line bg-surface-2 py-1 pr-1 pl-4 text-sm shadow-overlay">
            <span className="flex-1 py-2">{t.message}</span>
            {t.action && (
              <button type="button" className="min-h-11 rounded-control px-3 font-semibold text-accent hover:bg-line"
                onClick={() => {
                  t.action!.onClick()
                  dismiss(t.id)
                }}>
                {t.action.label}
              </button>
            )}
          </div>
        ))}
      </div>
    </ToastContext>
  )
}
