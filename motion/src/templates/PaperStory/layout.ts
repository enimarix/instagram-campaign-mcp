// PaperStory staging (step 131): where each scene's pieces sit and when they move, in frames
// from the scene's start. Pure, so `node --test` checks it (test/paperstory.test.ts).
import { DARK_SHEETS, type SheetId } from "../../paper/palette.ts";
import { type Beat, LABEL_SIZE, type LabelProp, type PaperStoryProps } from "./schema.ts";

/** Centre of the first strip: just under the top of the safe area (269 px). */
export const LABEL_TOP = 340;
const LABEL_GAP = 16;
/** A strip's height at font size `size` (padding .24 + .28 em, line 1 em). */
export const labelHeight = (size: number) => size * 1.52;
export const sizeOf = (l: LabelProp) => LABEL_SIZE[typeof l === "string" ? "m" : l.size];

/** Centre y of each stacked strip and the bottom of the stack. */
export const labelStack = (labels: LabelProp[]) => {
  const ys: number[] = [];
  let bottom = LABEL_TOP - LABEL_GAP;
  for (const l of labels) {
    const h = labelHeight(sizeOf(l));
    ys.push(bottom + LABEL_GAP + h / 2);
    bottom += LABEL_GAP + h;
  }
  return { ys, bottom };
};

/** Hook strips pop in at these seconds: the first is there from frame 0 (readable before any tap). */
export const HOOK_POP_S = [0, 0.3, 0.8];
/** The Reel cover: once the last hook strip has landed. */
export const coverFrame = (p: PaperStoryProps, fps: number) => Math.round((HOOK_POP_S[p.hook.labels.length - 1] + 0.3) * fps);

/** When strip `i` of `n` pops in a `len`-frame beat. App list beats show one strip at a time, in turn. */
export const labelStart = (i: number, n: number, len: number, fps: number, oneByOne: boolean) =>
  oneByOne ? Math.round((i * len) / n) + Math.round(0.1 * fps) : Math.round(0.15 * fps + i * Math.min(0.75 * fps, len * 0.18));

/** The sheet of scene `index` (0 = hook): its own, else hook navy, problem sky, first app mint, later app cream, payoff = the hook's. */
export const sheetOf = (p: PaperStoryProps, index: number): SheetId => {
  const hookSheet = p.hook.sheet ?? "navy";
  if (index === 0) return hookSheet;
  const b = p.beats[index - 1];
  if (b.sheet) return b.sheet;
  if (b.kind === "problem") return "sky";
  if (b.kind === "payoff") return hookSheet;
  return p.beats.findIndex((x) => x.kind === "app") === index - 1 ? "mint" : "cream";
};
export const isDark = (s: SheetId) => DARK_SHEETS.includes(s);

/** The transition into scene `index` (1..n): tear, wipe, tear… (the owner's rhythm). */
export const transitionInto = (index: number): "tear" | "wipe" => (index % 2 ? "tear" : "wipe");
/** Tear runs this long after the cut; a wipe covers the cut ± half of WIPE_S. */
export const TEAR_S = 0.6;
export const WIPE_S = 0.7;

/** Problem option `i` of `n`: [start, verdict] frames in a `len`-frame beat. */
export const optionTimes = (i: number, n: number, len: number, fps: number) => {
  const slot = (len * 0.85) / n;
  const start = Math.round(len * 0.1 + i * slot);
  return { start, verdict: start + Math.round(Math.min(0.75 * fps, slot * 0.5)) };
};

/** App phone beat: the phone pops, the ring counts, the button is tapped. */
export const phoneTimes = (len: number, fps: number) => ({
  pop: Math.round(0.2 * fps),
  count: [Math.round(0.4 * fps), Math.round(1.2 * fps)] as const,
  tap: Math.round(len * 0.55),
});

/** App list beat: rows fly in, locks close, grams solve, the total lands. */
export const rowTimes = (n: number, len: number, fps: number) => {
  const gap = Math.min(0.3 * fps, (len * 0.3) / n);
  return {
    row: (i: number) => Math.round(len * 0.08 + i * gap),
    lock: (k: number) => Math.round(len * 0.42 + k * 0.1 * fps),
    solve: [Math.round(len * 0.55), Math.round(len * 0.75)] as const,
    total: Math.round(len * 0.8),
  };
};
/** Rows' centre y (rows are 124 px tall): 160 px apart from 630, 5 rows 128 apart from 600, all above the total at 1240. */
export const rowY = (i: number, n: number) => (n > 4 ? 600 + i * 128 : 630 + i * 160);

/** Payoff: the ring counts, then the stamp lands (with confetti). */
export const payoffTimes = (len: number) => ({ count: [Math.round(len * 0.05), Math.round(len * 0.3)] as const, stamp: Math.round(len * 0.36) });

/** Payoff: the stamp under the strips, the ring under the stamp (at least at 820). */
export const payoffPlaces = (b: Extract<Beat, { kind: "payoff" }>) => {
  const stampY = labelStack(b.labels).bottom + 90;
  return { stampY, ringY: Math.max(820, stampY + (b.stamp ? 330 : 260)) };
};

/** The first number in `text` ("2 236", "2 238 kcal"), else null. */
export const numberIn = (text?: string) => {
  const m = /\d[\d   ]*(?:[.,]\d+)?/.exec(text ?? "");
  return m ? Number(m[0].replace(/[\s  ]/g, "").replace(",", ".")) : null;
};

/** The payoff ring's fill: value / of when both are numbers (≤ 1), else full. */
export const payoffRatio = (b: Extract<Beat, { kind: "payoff" }>) => {
  const v = numberIn(b.value);
  const of = numberIn(b.of);
  return v !== null && of ? Math.min(1, v / of) : 1;
};
