import { useEffect, useId, useRef, type ReactNode } from 'react'

type Props = { title: string; onClose: () => void; children: ReactNode; wide?: boolean } // wide: a gallery, from md up

// A bottom sheet on a phone, a centred dialog from md up. A native modal <dialog> traps
// focus and makes the page behind it inert; Esc and a tap on the backdrop close it, and
// every close lands in onClose through the dialog's `close` event.
export function Sheet({ title, onClose, children, wide }: Props) {
  const ref = useRef<HTMLDialogElement>(null)
  const id = useId()

  useEffect(() => {
    if (!ref.current?.open) ref.current?.showModal()
  }, [])

  return (
    <dialog
      ref={ref}
      onClose={(e) => e.target === ref.current && onClose()} // React bubbles a nested sheet's close
      aria-labelledby={id}
      onKeyDown={(e) => {
        if (e.key !== 'Escape') return
        e.preventDefault() // one close path for browsers and jsdom alike
        e.stopPropagation() // a sheet opened from a sheet: Esc closes only the top one
        ref.current?.close()
      }}
      onClick={(e) => e.target === ref.current && ref.current.close()}
      className={`mx-auto mt-auto mb-0 max-h-[90dvh] w-full max-w-full animate-sheet-in rounded-t-sheet bg-surface p-0 text-fg shadow-overlay md:mb-auto ${wide ? 'md:max-w-4xl' : 'md:max-w-md'} md:rounded-sheet`}
    >
      <div className="p-5 pb-[max(1.25rem,env(safe-area-inset-bottom))]">
        <div aria-hidden className="mx-auto -mt-2 mb-3 h-1 w-10 rounded-full bg-line md:hidden" />
        <h2 id={id} className="text-lg font-semibold">{title}</h2>
        {children}
      </div>
    </dialog>
  )
}
