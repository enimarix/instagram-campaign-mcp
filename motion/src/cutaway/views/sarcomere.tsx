// Sarcomere view (step 142): the muscle's smallest motor. Two Z-lines, thin actin strands
// anchored on them, thick myosin filaments in the middle whose heads cycle: attach to the
// actin, pull (power stroke), let go when an ATP lands (a spark), recock. `stage` closes the
// Z-lines (contraction); fast playback blurs the heads.
import { C } from "../palette";
import { type View, type ViewState, frac, ghosts, LINE, rad, Spark } from "./common";

const MYO_Y = [-220, 0, 220];
const ACTIN_Y = [-278, -162, -58, 58, 162, 278];
const ACTIN_LEN = 290;
const HEADS = [0, 1, 2, 3, 4].map((k) => 50 + k * 40);

const zOf = (stage: number) => 360 - 130 * stage;

/** One head's tip and state at cycle position q (0..1): attach, pull, release (ATP), recock. */
const headAt = (q: number) => {
  const e = (t: number) => t * t * (3 - 2 * t);
  if (q < 0.25) return { tilt: 35, len: 30 + 14 * e(q / 0.25), on: false, atp: 0 };
  if (q < 0.5) return { tilt: 35 - 65 * e((q - 0.25) / 0.25), len: 44, on: true, atp: 0 };
  if (q < 0.75) return { tilt: -30, len: 44 - 14 * e((q - 0.5) / 0.25), on: false, atp: Math.sin(Math.PI * ((q - 0.5) / 0.25)) };
  return { tilt: -30 + 65 * e((q - 0.75) / 0.25), len: 30, on: false, atp: 0 };
};

type Head = { x: number; y: number; dir: number; side: number; offset: number };
const ALL: Head[] = MYO_Y.flatMap((y, m) =>
  [1, -1].flatMap((side) =>
    HEADS.flatMap((hx, k) =>
      [-1, 1].map((dir) => ({ x: side * hx, y, dir, side, offset: frac(k * 0.27 + m * 0.37 + (dir > 0 ? 0.13 : 0) + (side > 0 ? 0 : 0.61) - 0.27) })),
    ),
  ),
);
/** The head the callout « tête » and the steps follow: top filament, right half, second head, upward. */
const LEAD = ALL.findIndex((h) => h.y === MYO_Y[0] && h.side === 1 && h.x === HEADS[1] && h.dir === -1);

const tipOf = (h: Head, q: number) => {
  const s = headAt(q);
  const a = rad(h.side * s.tilt);
  const bx = h.x;
  const by = h.y + h.dir * 15;
  return { bx, by, tx: bx + Math.sin(a) * s.len, ty: by + h.dir * Math.cos(a) * s.len, ...s };
};

const Actin = ({ x0, x1, y }: { x0: number; x1: number; y: number }) => {
  const beads = [];
  const step = 19;
  const n = Math.floor(Math.abs(x1 - x0) / step);
  const dir = Math.sign(x1 - x0);
  for (let i = 0; i <= n; i++) {
    const x = x0 + dir * i * step;
    const w = Math.sin(i * 0.55) * 7;
    beads.push(<circle key={`a${i}`} cx={x} cy={y + w} r={10} fill={C.teal} />, <circle key={`b${i}`} cx={x + step / 2} cy={y - w} r={10} fill={i % 2 ? C.tealLight : C.teal} />);
  }
  return <g>{beads}</g>;
};

const ZLine = ({ x }: { x: number }) => {
  const pts = Array.from({ length: 17 }, (_, i) => `${x + (i % 2 ? 14 : -14)},${-310 + i * 38.75}`).join(" ");
  return (
    <g>
      <polyline points={pts} fill="none" stroke={C.ink} strokeWidth={30} strokeLinejoin="miter" />
      <polyline points={pts} fill="none" stroke={C.cream} strokeWidth={16} strokeLinejoin="miter" />
    </g>
  );
};

const Draw = ({ phase, stage, rate }: ViewState) => {
  const z = zOf(stage);
  const g = ghosts(rate);
  return (
    <g>
      {/* The myofibril, cut open: a dark slice with copper cut edges. */}
      <rect x={-z - 70} y={-330} width={2 * z + 140} height={660} fill={C.ink} opacity={0.6} />
      {[-342, 318].map((y) => (
        <g key={y}>
          <rect x={-z - 70} y={y} width={2 * z + 140} height={24} fill={C.copper} stroke={C.ink} {...LINE} />
          <rect x={-z - 60} y={y + 4} width={2 * z + 120} height={6} fill={C.copperLight} />
        </g>
      ))}
      <line x1={0} y1={-312} x2={0} y2={312} stroke={C.violet} strokeWidth={10} strokeDasharray="20 14" />
      {ACTIN_Y.map((y) => (
        <g key={y}>
          <Actin x0={-z} x1={-z + ACTIN_LEN} y={y} />
          <Actin x0={z} x1={z - ACTIN_LEN} y={y} />
        </g>
      ))}
      {MYO_Y.map((y) => (
        <g key={y}>
          <rect x={-232} y={y - 15} width={464} height={30} rx={14} fill={C.steel} stroke={C.ink} {...LINE} />
          <rect x={-224} y={y - 9} width={448} height={6} fill={C.white} opacity={0.5} />
          <rect x={-30} y={y - 15} width={60} height={30} fill={C.steelDark} />
        </g>
      ))}
      {ALL.map((h, i) =>
        Array.from({ length: g.n }, (_, j) => {
          const t = tipOf(h, frac(phase + h.offset - j * g.spread));
          const lead = i === LEAD;
          return (
            <g key={`${i}-${j}`} opacity={j ? 0.45 / j : 1}>
              <line x1={t.bx} y1={t.by} x2={t.tx} y2={t.ty} stroke={C.steelDark} strokeWidth={10} />
              <ellipse cx={t.tx} cy={t.ty} rx={13} ry={10} fill={t.on ? C.yellow : lead ? C.hot : C.yellowDark} stroke={C.ink} {...LINE} />
              {j === 0 && t.atp > 0 && <Spark x={t.tx + h.side * 6} y={t.ty + h.dir * 18} r={24 * t.atp} color={C.yellow} />}
            </g>
          );
        }),
      )}
      <ZLine x={-z} />
      <ZLine x={z} />
    </g>
  );
};

export const sarcomere: View<"sarcomere"> = {
  Draw,
  anchors: ({ phase, stage }) => {
    const z = zOf(stage);
    const lead = ALL[LEAD];
    const t = tipOf(lead, frac(phase + lead.offset));
    return { zline: [z, -300], actine: [z - 120, -162], myosine: [-150, 220], tete: [t.tx, t.ty], mline: [0, -300] };
  },
};

/** Where the lead head is in its cycle (0..1): steps « s'accroche, tire, lâche, recharge » follow it. */
export const leadCycle = (phase: number) => frac(phase + ALL[LEAD].offset);
