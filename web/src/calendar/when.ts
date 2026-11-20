// Owner-local dates of the Calendar page, as the server sends them ("2026-11-24T11:54:00+01:00").

/** "2026-11-24" → the browser's short day label, e.g. "Tue 24 Nov". */
export const dayLabel = (iso: string) =>
  new Date(`${iso}T00:00`).toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' })

/** An owner-local ISO time → "Tue 24 Nov 11:54" (the wall clock as sent). */
export const slotLabel = (local: string) => `${dayLabel(local.slice(0, 10))} ${local.slice(11, 16)}`
