// Shared Tailwind classes for the inbox: 44 px touch targets and a visible focus ring.
export const button =
  'min-h-11 rounded-lg px-3 text-sm font-medium focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600 disabled:opacity-40'
export const chip = 'rounded-full px-2 py-0.5 text-xs font-medium'

/** "2026-11-18T11:00:00+01:00" → "2026-11-18 11:00": the owner's wall-clock time as sent. */
export const wallClock = (iso: string) => iso.slice(0, 16).replace('T', ' ')

const pad = (n: number) => String(n).padStart(2, '0')
/** A Date as YYYY-MM-DD in the browser's time zone. */
export const localDate = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
/** A Date as a <input type="datetime-local"> value, in the browser's time zone. */
export const inputValue = (d: Date) => `${localDate(d)}T${pad(d.getHours())}:${pad(d.getMinutes())}`
