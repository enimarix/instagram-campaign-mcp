import { createContext, useContext } from 'react'

export type ToastInput = {
  message: string
  action?: { label: string; onClick: () => void } // e.g. Undo
  duration?: number // ms, default 5000
}

export const ToastContext = createContext<(t: ToastInput) => void>(() => {})

/** `toast({ message, action })` shows a toast; ToastProvider (App) renders them. */
export const useToast = () => useContext(ToastContext)
