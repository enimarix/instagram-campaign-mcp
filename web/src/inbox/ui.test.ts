import { describe, expect, it } from 'vitest'
import { changeLabel, wallClock } from './ui'

describe('wallClock', () => {
  const now = new Date(2026, 10, 30, 22, 0) // 30 Nov, local time: tomorrow crosses the month
  it('says today and tomorrow, else the date', () => {
    expect(wallClock('2026-11-30T18:57:00+01:00', now)).toBe('aujourd’hui 18:57')
    expect(wallClock('2026-12-01T09:00:00+01:00', now)).toBe('demain 09:00')
    expect(wallClock('2026-12-02T09:00:00+01:00', now)).toBe('mer. 2 déc. 09:00')
  })
})

describe('changeLabel', () => {
  const reasons = [{ id: 'weak_hook', label: 'Weak hook' }]
  it("quotes the owner's words, else their reasons; nothing on a first version", () => {
    expect(changeLabel({ text: ' Plus court ', reason_codes: ['weak_hook'] }, reasons)).toBe('Changé : « Plus court »')
    expect(changeLabel({ text: null, reason_codes: ['weak_hook', 'odd'] }, reasons)).toBe('Changé : « Weak hook, odd »')
    expect(changeLabel(null, reasons)).toBeNull()
    expect(changeLabel(undefined)).toBeNull()
  })
})
