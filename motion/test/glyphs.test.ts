// Every character the scripts use is drawable in every template font (step 162: the pixel
// font drew « → » and « ~ » as « ? »): the webfonts / TTFs through their cmaps and the faces'
// unicode-ranges (src/lib/faces.ts), the cutaway bitmap font through its glyph table.
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { test } from "node:test";
import { brotliDecompressSync } from "node:zlib";
import { missingGlyphs } from "../src/cutaway/pixelfont.ts";
import { FAMILIES, type Face, SYMBOLS_FILE } from "../src/lib/faces.ts";

/** The agent's usual punctuation, on top of what the example props use. */
const PUNCTUATION = "«»’…–—→~%€°×÷";

const chars = new Set(PUNCTUATION);
const collect = (v: unknown): void => {
  if (typeof v === "string") {
    if (!/^https?:/.test(v)) for (const c of v) chars.add(c);
  } else if (v && typeof v === "object") Object.values(v).forEach(collect);
};
const props = new URL("../props/", import.meta.url);
for (const name of readdirSync(props).filter((n) => n.endsWith(".json")).sort()) collect(JSON.parse(readFileSync(new URL(name, props), "utf8")));
const TEXT = [...chars].filter((c) => c >= " ").join("");

/** A font file's tables by tag (TTF / OTF, or WOFF2: one brotli stream; cmap is never transformed). */
const tables = (buf: Buffer): Record<string, Buffer> => {
  const out: Record<string, Buffer> = {};
  if (buf.toString("latin1", 0, 4) !== "wOF2") {
    for (let i = 0; i < buf.readUInt16BE(4); i++) {
      const o = 12 + 16 * i;
      const at = buf.readUInt32BE(o + 8);
      out[buf.toString("latin1", o, o + 4)] = buf.subarray(at, at + buf.readUInt32BE(o + 12));
    }
    return out;
  }
  // Known tags by index (WOFF2 spec §5.1), as far as cmap's neighbours need.
  const KNOWN = ["cmap", "head", "hhea", "hmtx", "maxp", "name", "OS/2", "post", "cvt ", "fpgm", "glyf", "loca", "prep", "CFF ", "VORG", "EBDT", "EBLC", "gasp", "hdmx", "kern", "LTSH", "PCLT", "VDMX", "vhea", "vmtx", "BASE", "GDEF", "GPOS", "GSUB", "EBSC", "JSTF", "MATH", "CBDT", "CBLC", "COLR", "CPAL", "SVG ", "sbix", "acnt", "avar", "bdat", "bloc", "bsln", "cvar", "fdsc", "feat", "fmtx", "fvar", "gvar", "hsty", "just", "lcar", "mort", "morx", "opbd", "prop", "trak", "Zapf", "Silf", "Glat", "Gloc", "Feat", "Sill"];
  let p = 48;
  const base128 = () => {
    let v = 0;
    for (;;) {
      const b = buf[p++];
      v = v * 128 + (b & 127);
      if (!(b & 128)) return v;
    }
  };
  const dir: [string, number][] = [];
  for (let i = 0; i < buf.readUInt16BE(12); i++) {
    const flags = buf[p++];
    const tag = (flags & 63) === 63 ? buf.toString("latin1", p, (p += 4)) : KNOWN[flags & 63];
    let len = base128();
    if (tag === "glyf" || tag === "loca" ? flags >> 6 === 0 : flags >> 6 !== 0) len = base128();
    dir.push([tag, len]);
  }
  const data = brotliDecompressSync(buf.subarray(p, p + buf.readUInt32BE(20)));
  let off = 0;
  for (const [tag, len] of dir) out[tag] = data.subarray(off, (off += len));
  return out;
};

/** Code points a font file maps to a glyph (cmap formats 4 and 12). */
const cmaps = new Map<string, Set<number>>();
const cmap = (file: string): Set<number> => {
  const hit = cmaps.get(file);
  if (hit) return hit;
  const c = tables(readFileSync(new URL(`../public/${file}`, import.meta.url))).cmap;
  const set = new Set<number>();
  for (let i = 0; i < c.readUInt16BE(2); i++) {
    const off = c.readUInt32BE(8 + 8 * i);
    const format = c.readUInt16BE(off);
    if (format === 4) {
      const segs = c.readUInt16BE(off + 6) / 2;
      const ends = off + 14;
      const starts = ends + 2 * segs + 2;
      const deltas = starts + 2 * segs;
      const ranges = deltas + 2 * segs;
      for (let s = 0; s < segs; s++) {
        const [start, end, range] = [c.readUInt16BE(starts + 2 * s), c.readUInt16BE(ends + 2 * s), c.readUInt16BE(ranges + 2 * s)];
        for (let ch = start; ch <= end && ch !== 0xffff; ch++) {
          const g = range ? c.readUInt16BE(ranges + 2 * s + range + 2 * (ch - start)) : 1;
          if (g) set.add(ch);
        }
      }
    } else if (format === 12) {
      for (let k = 0; k < c.readUInt32BE(off + 12); k++) {
        const o = off + 16 + 12 * k;
        for (let ch = c.readUInt32BE(o); ch <= c.readUInt32BE(o + 4); ch++) set.add(ch);
      }
    }
  }
  cmaps.set(file, set);
  return set;
};

/** Does a unicode-range ("U+0000-00FF, U+0131") include code point `cp`? None = everything. */
const inRange = (range: string | undefined, cp: number) =>
  !range ||
  range.split(",").some((r) => {
    const [a, b = a] = r.trim().slice(2).split("-").map((h) => parseInt(h, 16));
    return cp >= a && cp <= b;
  });

const draws = (f: Face, cp: number) => inRange(f.unicodeRange, cp) && cmap(f.file).has(cp);

test("the checked text holds the scripts' characters and the agent's punctuation", () => {
  for (const c of "«»’…–—→~%€°×÷éèàçÉœ") assert.ok(TEXT.includes(c), c);
});

test("every template family draws every character, each from exactly one of its faces", () => {
  for (const [key, { faces, symbols }] of Object.entries(FAMILIES)) {
    const extra: Face = { file: SYMBOLS_FILE, unicodeRange: symbols };
    const missing: string[] = [];
    for (const c of TEXT) {
      const cp = c.codePointAt(0)!;
      if (c === " " || c === " " || c === " ") continue; // spaces are drawn by every face's layout
      if (!faces.some((f) => draws(f, cp)) && !draws(extra, cp)) missing.push(`${c} U+${cp.toString(16).toUpperCase()}`);
    }
    assert.deepEqual(missing, [], `${key}: no face draws these (add them to its symbols range or the symbols file)`);
    // The symbols face only takes what the family's own faces lack: no load-order race.
    for (let cp = 0; cp < 0x2300; cp++) {
      if (inRange(symbols, cp)) assert.ok(!faces.some((f) => draws(f, cp)), `${key}: U+${cp.toString(16)} is drawn by its own face and the symbols face`);
    }
  }
});

test("the cutaway bitmap font has a glyph for every character (nothing draws as « ? »)", () => {
  assert.deepEqual(missingGlyphs(TEXT), []);
  assert.deepEqual(missingGlyphs("TOURNE ~24 H → 1,6 G/KG ≈ 9,99 €"), []);
  assert.deepEqual(missingGlyphs("ñ"), []);
  assert.deepEqual(missingGlyphs("☃"), ["☃"]);
});
