// Shared helpers of the web pages (styles live in ../ui/).
/** Only http(s) links are rendered: agent-written URLs could carry `javascript:`. */
export const safeUrl = (url?: string | null) => (url && /^https?:\/\//i.test(url) ? url : null)

/** "2026-11-18T11:00:00+01:00" → "2026-11-18 11:00": the owner's wall-clock time as sent. */
export const wallClock = (iso: string) => iso.slice(0, 16).replace('T', ' ')

const pad = (n: number) => String(n).padStart(2, '0')
/** A Date as YYYY-MM-DD in the browser's time zone. */
export const localDate = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
/** A Date as a <input type="datetime-local"> value, in the browser's time zone. */
export const inputValue = (d: Date) => `${localDate(d)}T${pad(d.getHours())}:${pad(d.getMinutes())}`
