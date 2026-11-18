// Shared helpers of the web pages (styles live in ../ui/).
/** Only http(s) links are rendered: agent-written URLs could carry `javascript:`. */
export const safeUrl = (url?: string | null) => (url && /^https?:\/\//i.test(url) ? url : null)

/** "2026-11-18T11:00:00+01:00" → "today 11:00", "tomorrow 11:00" or "2026-11-18 11:00": the
 * owner's wall-clock time as sent, today/tomorrow as the browser sees them. */
export function wallClock(iso: string, now = new Date()) {
  const [day, time] = [iso.slice(0, 10), iso.slice(11, 16)]
  const tomorrow = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1)
  return day === localDate(now) ? `today ${time}` : day === localDate(tomorrow) ? `tomorrow ${time}` : `${day} ${time}`
}

const pad = (n: number) => String(n).padStart(2, '0')
/** A Date as YYYY-MM-DD in the browser's time zone. */
export const localDate = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
/** A Date as a <input type="datetime-local"> value, in the browser's time zone. */
export const inputValue = (d: Date) => `${localDate(d)}T${pad(d.getHours())}:${pad(d.getMinutes())}`
/** Seconds as "0:07", a moment of the video. */
export const clock = (s: number) => `${Math.floor(s / 60)}:${pad(Math.floor(s % 60))}`
/** What the owner confirms before a `commentary` video is queued (GOAL.md §5.1). */
export const COMMENTARY_CONFIRMATION =
  'I checked this reaction video: my own take is a substantial part and the creator is credited.'
