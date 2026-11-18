// A tiny markdown renderer for the agent's text (headings, lists, quotes, bold, italic,
// code, links). It builds React elements only: raw HTML in the text shows as text, never runs.
import type { ReactNode } from 'react'
import { safeUrl } from '../inbox/ui'
import { link } from './styles'

// italic: *x*, or _x_ outside a word (hook_type stays as is)
const INLINE = /\*\*(.+?)\*\*|`([^`]+)`|\[([^\]]+)\]\(([^)\s]+)\)|\*([^*\s][^*]*)\*|(?<!\w)_([^_]+)_(?!\w)/g

function inline(text: string): ReactNode[] {
  const out: ReactNode[] = []
  let last = 0
  for (const m of text.matchAll(INLINE)) {
    out.push(text.slice(last, m.index))
    const [, bold, code, label, url, star, under] = m
    const em = star ?? under
    const href = url && safeUrl(url)
    out.push(
      bold ? <strong key={m.index}>{inline(bold)}</strong>
        : code ? <code key={m.index} className="rounded bg-surface-2 px-1 text-[0.9em]">{code}</code>
          : label ? (href ? <a key={m.index} href={href} target="_blank" rel="noopener noreferrer" className={link}>{label}</a> : label)
            : <em key={m.index}>{inline(em)}</em>)
    last = m.index + m[0].length
  }
  out.push(text.slice(last))
  return out
}

type Block = { kind: 'h' | 'p' | 'ul' | 'ol' | 'quote'; lines: string[] }
const KINDS: [Block['kind'], RegExp][] = [['h', /^#{1,6}\s+/], ['ul', /^[-*+]\s+/], ['ol', /^\d+[.)]\s+/], ['quote', /^>\s?/]]

/** Consecutive lines of one kind form a block; a heading is always its own block. */
function blocks(text: string): Block[] {
  const out: Block[] = []
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim()
    if (!line) {
      out.push({ kind: 'p', lines: [] })
      continue
    }
    const [kind, re] = KINDS.find(([, r]) => r.test(line)) ?? ['p', /^/]
    const prev = out.at(-1)
    if (prev && prev.kind === kind && kind !== 'h') prev.lines.push(line.replace(re, ''))
    else out.push({ kind, lines: [line.replace(re, '')] })
  }
  return out.filter((b) => b.lines.length)
}

export function Markdown({ text, className = '' }: { text: string; className?: string }) {
  return (
    <div className={`max-w-prose space-y-2 text-sm leading-relaxed ${className}`}>
      {blocks(text).map((b, i) => {
        const items = b.lines.map((l, j) => <li key={j}>{inline(l)}</li>)
        if (b.kind === 'h') return <h3 key={i} className="pt-1 text-base font-semibold">{inline(b.lines[0])}</h3>
        if (b.kind === 'ul') return <ul key={i} className="list-disc space-y-0.5 pl-5">{items}</ul>
        if (b.kind === 'ol') return <ol key={i} className="list-decimal space-y-0.5 pl-5">{items}</ol>
        if (b.kind === 'quote') return <blockquote key={i} className="border-l-2 border-line pl-3 text-muted">{inline(b.lines.join(' '))}</blockquote>
        return <p key={i}>{inline(b.lines.join(' '))}</p>
      })}
    </div>
  )
}
