import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Button, IconButton } from './Button'
import { Card, EmptyState, Skeleton, Stat } from './Card'
import { Chip } from './Chip'
import { Sheet } from './Sheet'
import { Tabs } from './Tabs'
import { ThemeToggle } from './ThemeToggle'
import { ToastProvider } from './Toast'
import { useToast } from './useToast'

// jsdom has no modal dialogs
HTMLDialogElement.prototype.showModal = function () { this.open = true }
HTMLDialogElement.prototype.close = function () {
  this.open = false
  this.dispatchEvent(new Event('close'))
}

afterEach(() => {
  cleanup()
  localStorage.clear()
  delete document.documentElement.dataset.theme
})

describe('Button', () => {
  it('renders variants and turns loading into a disabled, busy button', () => {
    render(<><Button variant="primary">Go</Button><Button variant="danger" loading>Delete</Button></>)
    expect(screen.getByRole('button', { name: 'Go' }).className).toContain('bg-accent')
    const busy = screen.getByRole('button', { name: 'Delete' }) as HTMLButtonElement
    expect(busy.className).toContain('bg-danger')
    expect(busy.disabled).toBe(true)
    expect(busy.getAttribute('aria-busy')).toBe('true')
    expect(busy.type).toBe('button')
  })

  it('names an icon button by its label', () => {
    const onClick = vi.fn()
    render(<IconButton label="Mute" icon={<svg />} onClick={onClick} />)
    fireEvent.click(screen.getByRole('button', { name: 'Mute' }))
    expect(onClick).toHaveBeenCalledOnce()
  })
})

describe('Chip', () => {
  it('is a label, or a pressed toggle with onClick', () => {
    const onClick = vi.fn()
    render(<><Chip tone="success">winner</Chip><Chip pressed onClick={onClick}>7 d</Chip></>)
    expect(screen.getByText('winner').className).toContain('text-success')
    const toggle = screen.getByRole('button', { name: '7 d' })
    expect(toggle.getAttribute('aria-pressed')).toBe('true')
    fireEvent.click(toggle)
    expect(onClick).toHaveBeenCalledOnce()
  })
})

describe('Card, Stat, EmptyState, Skeleton', () => {
  it('render their content', () => {
    render(
      <>
        <Card as="section" aria-label="Box">inside</Card>
        <dl><Stat label="Followers" value="1,200" sub="+3 in 7 d" /></dl>
        <EmptyState title="No runs yet">Start one.</EmptyState>
        <Skeleton />
      </>,
    )
    expect(within(screen.getByRole('region', { name: 'Box' })).getByText('inside')).toBeTruthy()
    expect(screen.getByText('Followers').tagName).toBe('DT')
    expect(screen.getByText('1,200').tagName).toBe('DD')
    expect(screen.getByText('No runs yet')).toBeTruthy()
    expect(screen.getByText('Loading…')).toBeTruthy()
  })
})

describe('Sheet', () => {
  it('opens as a modal dialog and closes on Escape', () => {
    const onClose = vi.fn()
    render(<Sheet title="Pick" onClose={onClose}><p>body</p></Sheet>)
    const dialog = screen.getByRole('dialog', { name: 'Pick' }) as HTMLDialogElement
    expect(dialog.open).toBe(true)
    fireEvent.keyDown(dialog, { key: 'Escape' })
    expect(dialog.open).toBe(false)
    expect(onClose).toHaveBeenCalledOnce()
  })
})

describe('Tabs', () => {
  function Demo() {
    const [tab, setTab] = useState<'a' | 'b'>('a')
    return <Tabs label="View" value={tab} onChange={setTab} tabs={[{ id: 'a', label: 'A' }, { id: 'b', label: 'B' }]} />
  }
  it('selects on click and with the arrow keys', () => {
    render(<Demo />)
    const selected = () => screen.getByRole('tab', { selected: true }).textContent
    expect(selected()).toBe('A')
    fireEvent.click(screen.getByRole('tab', { name: 'B' }))
    expect(selected()).toBe('B')
    fireEvent.keyDown(screen.getByRole('tablist', { name: 'View' }), { key: 'ArrowRight' })
    expect(selected()).toBe('A')
  })
})

describe('Toast', () => {
  function Demo({ onUndo }: { onUndo: () => void }) {
    const toast = useToast()
    return <button type="button" onClick={() => toast({ message: 'Approved', action: { label: 'Undo', onClick: onUndo } })}>go</button>
  }
  it('shows a message whose Undo calls back and closes it', () => {
    const onUndo = vi.fn()
    render(<ToastProvider><Demo onUndo={onUndo} /></ToastProvider>)
    fireEvent.click(screen.getByRole('button', { name: 'go' }))
    expect(screen.getByRole('status').textContent).toContain('Approved')
    fireEvent.click(screen.getByRole('button', { name: 'Undo' }))
    expect(onUndo).toHaveBeenCalledOnce()
    expect(screen.queryByRole('status')).toBeNull()
  })

  it('goes away by itself', () => {
    vi.useFakeTimers()
    try {
      render(<ToastProvider><Demo onUndo={() => {}} /></ToastProvider>)
      fireEvent.click(screen.getByRole('button', { name: 'go' }))
      expect(screen.getByRole('status')).toBeTruthy()
      act(() => vi.advanceTimersByTime(5000))
      expect(screen.queryByRole('status')).toBeNull()
    } finally {
      vi.useRealTimers()
    }
  })
})

describe('ThemeToggle', () => {
  it('starts dark and stores the light choice', () => {
    render(<ThemeToggle />)
    expect(screen.getByRole('button', { name: 'Dark' }).getAttribute('aria-pressed')).toBe('true')
    fireEvent.click(screen.getByRole('button', { name: 'Light' }))
    expect(document.documentElement.dataset.theme).toBe('light')
    expect(localStorage.getItem('studio.theme')).toBe('light')
    expect(screen.getByRole('button', { name: 'Light' }).getAttribute('aria-pressed')).toBe('true')
  })
})
