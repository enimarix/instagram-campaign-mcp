// Word-by-word captions and the presenter's mouth (step 154). The voice gives one timing per
// line; inside a line each word gets its share of the time by its length (a pause after
// punctuation), like a reader. Pure, so `node --test` runs it (test/macro3d.test.ts).

export type Word = { text: string; start: number; end: number };

/** Weight of a word in its line: its letters, plus a pause after punctuation. */
const weight = (w: string) => Array.from(w.replace(/[^\p{L}\p{N}]/gu, "")).length + 1.5 + (/[.!?…]$/.test(w) ? 3 : /[,;:]$/.test(w) ? 1.5 : 0);

/** A number's thousands stay one word (« 7 700 »). */
const glue = (text: string) => text.replace(/(\d) (?=\d{3}(?!\d))/g, "$1\u00a0");
/** Words split at plain spaces (not \s: a no-break space keeps « ? » and « 7 700 » whole). */
const split = (text: string) => glue(text).split(/[ \t\n]+/).filter(Boolean);

/** The words of `line` spoken from `start` to `end` (seconds), each with its own span. */
export const wordTimes = (line: string, start: number, end: number): Word[] => {
  const words = split(line);
  const total = words.reduce((n, w) => n + weight(w), 0) || 1;
  let t = start;
  return words.map((text) => {
    const d = ((end - start) * weight(text)) / total;
    const w = { text, start: t, end: t + d };
    t += d;
    return w;
  });
};

/** Characters a caption chunk holds at most (two short lines at the caption size). */
export const CHUNK_CHARS = 26;

/**
 * The line in on-screen chunks (word indexes [from, to)): a chunk ends after punctuation (once
 * it holds a few letters) or before it would pass CHUNK_CHARS, never inside the key phrase
 * (`keep`: its word indexes).
 */
export const chunksOf = (words: readonly { text: string }[], keep: readonly number[] = []): [number, number][] => {
  const out: [number, number][] = [];
  let from = 0;
  let chars = 0;
  words.forEach((w, i) => {
    const len = Array.from(w.text).length;
    const inKey = keep.includes(i) && keep.includes(i - 1);
    if (i > from && chars + 1 + len > CHUNK_CHARS && !inKey) {
      out.push([from, i]);
      from = i;
      chars = 0;
    }
    chars += (chars ? 1 : 0) + len;
    if (/[.!?…,;:]$/.test(w.text) && i + 1 < words.length && chars > 6 && !(keep.includes(i) && keep.includes(i + 1))) {
      out.push([from, i + 1]);
      from = i + 1;
      chars = 0;
    }
  });
  if (from < words.length) out.push([from, words.length]);
  return out;
};

/** Word indexes of `key` inside `words` (case and punctuation ignored), or [] when it is not there. */
export const keyIndexes = (words: readonly { text: string }[], key?: string): number[] => {
  if (!key) return [];
  const norm = (s: string) => s.toLowerCase().replace(/[^\p{L}\p{N}]/gu, "");
  const want = split(key).map(norm); // « % » stays a word of its own (norm "")
  for (let i = 0; i + want.length <= words.length; i++) {
    if (want.every((k, j) => norm(words[i + j].text) === k)) return want.map((_, j) => i + j);
  }
  return [];
};

export type Mouth = "closed" | "small" | "open" | "round" | "wide";

/**
 * The mouth while `line` is read from `start` to `end`, at `t` seconds: the letter being said
 * (its estimated position) picks the shape: a o u round or open, i e wide, m b p closed.
 * Closed outside the line.
 */
export const mouthAt = (line: string, start: number, end: number, t: number): Mouth => {
  if (t < start || t >= end) return "closed";
  const letters = Array.from(line.toLowerCase().normalize("NFD").replace(/[^a-z ]/g, ""));
  const c = letters[Math.min(letters.length - 1, Math.floor(((t - start) / (end - start)) * letters.length))];
  if (c === undefined || c === " ") return "small";
  if ("ou".includes(c)) return "round";
  if (c === "a") return "open";
  if ("ie".includes(c)) return "wide";
  if ("mbp".includes(c)) return "closed";
  return "small";
};
