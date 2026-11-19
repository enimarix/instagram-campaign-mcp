// Sarcomere view (step 142, hero machine in review round 1): one sarcomere seen in
// perspective, a drum between two Z-discs (geared rings). Inside, the hexagonal lattice: seven
// thick myosin filaments (the centre one is the hero), twelve thin actin strands anchored on the
// discs. Myosin heads are levers that attach, pull (a flash on each power stroke), let go when
// an ATP lands and recock; `stage` closes the discs (contraction). Fast playback smears the
// levers into blurred fans, like a spinning propeller.
import { C } from "../palette";
import { capsuleD, RAMPS, Shade, useDither } from "../shade";
import { type View, type ViewState, frac, rad, Spark, Sparkles } from "./common";

const R = 300; // disc radius
const ACT = 300; // actin length from its disc
const MYO = 240; // myosin half-length
/** Oblique projection: depth d (toward the viewer) shifts right and up. */
const proj = (x: number, y: number, d: number): [number, number] => [x + 0.42 * d, y - 0.18 * d];
const zOf = (stage: number) => 315 - 115 * stage;

type Fil = { y: number; d: number };
const polar = (r: number, deg: number): Fil => ({ y: r * Math.cos(rad(deg)), d: r * Math.sin(rad(deg)) });
/** Lattice spacing: myosin to its neighbouring actins. */
const GAP = 106;
const MYOSINS: Fil[] = [{ y: 0, d: 0 }, ...[0, 60, 120, 180, 240, 300].map((a) => polar(GAP * Math.sqrt(3), a))];
const ACTINS: Fil[] = [...[30, 90, 150, 210, 270, 330].map((a) => polar(GAP, a)), ...[30, 90, 150, 210, 270, 330].map((a) => polar(2 * GAP, a))];
const HEAD_X = [62, 108, 154, 200];
/** The outer filaments show fewer heads, and only those facing the viewer: the hero stays readable. */
const OUTER_X = [80, 150];

/** Each myosin's heads: toward its neighbouring actins (lattice distance 98), both halves. */
type Head = { m: number; dy: number; dd: number; x: number; side: number; offset: number };
const HEADS: Head[] = MYOSINS.flatMap((mf, m) =>
  ACTINS.filter((a) => Math.hypot(a.y - mf.y, a.d - mf.d) < GAP * 1.1 && (m === 0 || a.d - mf.d > -GAP * 0.3)).flatMap((a, n) => {
    const len = Math.hypot(a.y - mf.y, a.d - mf.d);
    return [1, -1].flatMap((side) =>
      (m === 0 ? HEAD_X : OUTER_X).map((hx, k) => ({ m, dy: (a.y - mf.y) / len, dd: (a.d - mf.d) / len, x: side * hx, side, offset: frac(k * 0.29 + n * 0.17 + m * 0.37 + (side > 0 ? 0 : 0.5)) })),
    );
  }),
);
/** The lead head (callout « tête », the steps, the flash): the hero's, right half, nearest the viewer and up. */
const LEAD = HEADS.reduce((best, h, i) => (h.m === 0 && h.side === 1 && h.x === HEAD_X[1] && h.dd - h.dy > HEADS[best].dd - HEADS[best].dy ? i : best), HEADS.findIndex((h) => h.m === 0));

/** Lever state at cycle position q: attach, pull (power stroke), release (ATP), recock. */
const leverAt = (q: number) => {
  const e = (t: number) => t * t * (3 - 2 * t);
  if (q < 0.25) return { tilt: 38, reach: 0.7 + 0.3 * e(q / 0.25), on: false, atp: 0, flash: 0 };
  if (q < 0.5) return { tilt: 38 - 70 * e((q - 0.25) / 0.25), reach: 1, on: true, atp: 0, flash: Math.max(0, 1 - (q - 0.25) / 0.09) };
  if (q < 0.75) return { tilt: -32, reach: 1 - 0.3 * e((q - 0.5) / 0.25), on: false, atp: Math.sin(Math.PI * ((q - 0.5) / 0.25)), flash: 0 };
  return { tilt: -32 + 70 * e((q - 0.75) / 0.25), reach: 0.7, on: false, atp: 0, flash: 0 };
};

/** A head's base and tip on screen at cycle position q. */
const headAt = (h: Head, q: number) => {
  const mf = MYOSINS[h.m];
  const r0 = h.m === 0 ? 32 : 19;
  const s = leverAt(q);
  const len = (GAP - r0 - 12) * s.reach;
  const t = rad(h.side * s.tilt);
  const base = proj(h.x, mf.y + h.dy * r0, mf.d + h.dd * r0);
  const tip = proj(h.x + Math.sin(t) * len, mf.y + h.dy * (r0 + Math.cos(t) * len), mf.d + h.dd * (r0 + Math.cos(t) * len));
  return { base, tip, ...s };
};

/** Depth shade 0 (far) .. 1 (near). */
const near = (d: number) => Math.min(1, Math.max(0, (d + 260) / 520));

/** A Z-disc: a geared ring at x, its face a translucent plate. `half` = back (d < 0) or front arc only. */
const discPts = (x: number, teeth: boolean, from = 0, to = 2 * Math.PI) => {
  const n = 64;
  const pts: string[] = [];
  for (let i = 0; i <= n; i++) {
    const t = from + ((to - from) * i) / n;
    const r = R + (teeth && i % 2 ? 18 : 0);
    const [px, py] = proj(x, r * Math.cos(t), r * Math.sin(t));
    pts.push(`${px.toFixed(1)},${py.toFixed(1)}`);
  }
  return pts.join(" ");
};

const Disc = ({ x, f, front }: { x: number; f: number; front: boolean }) => {
  // Back half (d < 0: t in [π, 2π]) behind the filaments, front half over them.
  const [a, b] = front ? [0, Math.PI] : [Math.PI, 2 * Math.PI];
  const pts = discPts(x, true, a, b);
  const runner = frac(f / 90);
  const [rx, ry] = proj(x, R * Math.cos(a + (b - a) * runner), R * Math.sin(a + (b - a) * runner));
  return (
    <g>
      {!front && <polygon points={discPts(x, false)} fill={C.violet} opacity={0.35} />}
      <polyline points={pts} fill="none" stroke={C.ink} strokeWidth={40} strokeLinejoin="round" />
      <polyline points={pts} fill="none" stroke={front ? RAMPS.bone[2] : RAMPS.bone[1]} strokeWidth={24} strokeLinejoin="round" />
      {front && <polyline points={discPts(x, true, 0.15, 1.2)} fill="none" stroke={RAMPS.bone[4]} strokeWidth={10} />}
      {!front && <polyline points={discPts(x, true, 3.6, 4.8)} fill="none" stroke={RAMPS.bone[0]} strokeWidth={10} />}
      {front && <rect x={rx - 7} y={ry - 7} width={14} height={14} fill={C.white} />}
    </g>
  );
};

const Actin = ({ a, z, f }: { a: Fil; z: number; f: number }) => {
  const k = near(a.d);
  const ramp = RAMPS.teal;
  const beads = [];
  for (const [x0, dir] of [[-z, 1], [z, -1]] as const) {
    for (let i = 0; i * 22 <= ACT; i++) {
      const x = x0 + dir * i * 22;
      const w = Math.sin(i * 0.6) * 7;
      const [p1x, p1y] = proj(x, a.y + w, a.d);
      const [p2x, p2y] = proj(x + 11 * dir, a.y - w, a.d);
      const r = 8 + 3 * k;
      beads.push(
        <circle key={`${x0}a${i}`} cx={p1x} cy={p1y} r={r} fill={ramp[1 + Math.round(k * 2)]} />,
        <circle key={`${x0}b${i}`} cx={p2x} cy={p2y} r={r} fill={ramp[Math.min(4, 2 + Math.round(k * 2) - (i % 2))]} />,
      );
    }
  }
  return (
    <g>
      {beads}
      {k > 0.6 && <Sparkles cx={proj(-z + ACT / 2, a.y, a.d)[0]} cy={proj(0, a.y, a.d)[1]} rx={ACT / 2} ry={12} n={8} seed={Math.round(a.y + a.d) + 900} f={f} color={C.tealLight} size={7} />}
    </g>
  );
};

const Myosin = ({ m }: { m: number }) => {
  const mf = MYOSINS[m];
  const hero = m === 0;
  const a = proj(-MYO, mf.y, mf.d);
  const b = proj(MYO, mf.y, mf.d);
  const w = hero ? 64 : 38;
  const k = near(mf.d);
  const ramp = hero ? RAMPS.steel : ([RAMPS.steel[0], RAMPS.steel[0], RAMPS.steel[1], RAMPS.steel[2 + Math.round(k)], RAMPS.steel[3 + Math.round(k)]] as const);
  return (
    <Shade d={capsuleD(a, b, w)} c={[(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]} size={w * 2.2} axis={Math.atan2(b[1] - a[1], b[0] - a[0]) * (180 / Math.PI)} ramp={ramp} spec={hero}>
      {/* The bare zone in the middle (no heads), and the tails' ribbing. */}
      <rect x={(a[0] + b[0]) / 2 - 22} y={(a[1] + b[1]) / 2 - w} width={44} height={2 * w} fill={RAMPS.steel[1]} />
    </Shade>
  );
};

const Lever = ({ h, q, lead, blur }: { h: Head; q: number; lead: boolean; blur: number }) => {
  const s = headAt(h, q);
  const hero = h.m === 0;
  const k = near(MYOSINS[h.m].d + h.dd * 60);
  const ramp = RAMPS.gold;
  const tone = hero ? (s.on ? ramp[4] : ramp[3]) : ramp[1 + Math.round(k * 2)];
  const size = hero ? 15 : 10;
  if (blur > 0) {
    // Too fast to see: the lever sweeps a blurred fan between its two extremes.
    const a = headAt(h, 0.3).tip;
    const b = headAt(h, 0.45).tip;
    return <polygon points={`${s.base[0]},${s.base[1]} ${a[0]},${a[1]} ${b[0]},${b[1]}`} fill={tone} opacity={0.25 + 0.2 * k} />;
  }
  return (
    <g>
      <line x1={s.base[0]} y1={s.base[1]} x2={s.tip[0]} y2={s.tip[1]} stroke={C.ink} strokeWidth={hero ? 16 : 11} strokeLinecap="round" />
      <line x1={s.base[0]} y1={s.base[1]} x2={s.tip[0]} y2={s.tip[1]} stroke={hero ? RAMPS.steel[3] : RAMPS.steel[1 + Math.round(k)]} strokeWidth={hero ? 8 : 5} strokeLinecap="round" />
      <ellipse cx={s.tip[0]} cy={s.tip[1]} rx={size * 1.25} ry={size} fill={lead ? C.hot : tone} stroke={C.ink} strokeWidth={5} vectorEffect="non-scaling-stroke" />
      {hero && <rect x={s.tip[0] - size * 0.6} y={s.tip[1] - size * 0.7} width={size * 0.5} height={size * 0.4} fill={ramp[4]} />}
      {hero && s.flash > 0 && (
        <>
          <circle cx={s.tip[0]} cy={s.tip[1]} r={20 + 50 * (1 - s.flash)} fill="none" stroke={C.sun} strokeWidth={8 * s.flash} />
          <Spark x={s.tip[0]} y={s.tip[1]} r={44 * s.flash} color={C.yellow} />
        </>
      )}
      {(hero || k > 0.7) && s.atp > 0 && <Spark x={s.tip[0] + h.side * 10} y={s.tip[1] - 16} r={(hero ? 26 : 16) * s.atp} color={C.tealLight} core={C.white} />}
    </g>
  );
};

const Draw = ({ phase, stage, rate, f }: ViewState) => {
  const z = zOf(stage);
  const dither = useDither();
  const blur = rate > 3 ? 1 : 0;
  // Painter's order: far filaments first (then a dithered haze over them), heads with their
  // myosin; the hero filament last so its levers always read.
  const items = [
    ...ACTINS.map((a) => ({ d: a.d - 1, el: <Actin key={`a${a.y}${a.d}`} a={a} z={z} f={f} /> })),
    ...MYOSINS.map((mf, m) => ({
      d: mf.d,
      el: (
        <g key={`m${m}`}>
          {HEADS.map((h, i) => (h.m === m && h.dd < 0 ? <Lever key={i} h={h} q={frac(phase + h.offset)} lead={false} blur={blur} /> : null))}
          <Myosin m={m} />
          {HEADS.map((h, i) => (h.m === m && h.dd >= 0 ? <Lever key={i} h={h} q={frac(phase + h.offset)} lead={i === LEAD} blur={blur} /> : null))}
        </g>
      ),
    })),
  ]
    .map((it, i) => (i === ACTINS.length ? { ...it, d: 9999 } : it))
    .sort((p, q) => p.d - q.d);
  const far = items.filter((i) => i.d < 0);
  const close = items.filter((i) => i.d >= 0);
  const top = [proj(-z, -R, 0), proj(z, -R, 0)];
  const bottom = [proj(-z, R, 0), proj(z, R, 0)];
  return (
    <g>
      {/* The drum: a glassy sarcolemma between the discs, a glow at its heart. */}
      <polygon points={`${top[0]} ${top[1]} ${bottom[1]} ${bottom[0]}`} fill={C.ink} opacity={0.55} />
      <g mask={dither(0.5)}>
        <ellipse cx={0} cy={0} rx={z + 60} ry={R * 0.75} fill={C.violet} />
      </g>
      <g mask={dither(0.25)}>
        <ellipse cx={0} cy={0} rx={230} ry={150} fill={C.yellow} />
      </g>
      <Disc x={-z} f={f} front={false} />
      <Disc x={z} f={f} front={false} />
      {far.map((i) => i.el)}
      <g mask={dither(0.5)}>
        <polygon points={`${top[0]} ${top[1]} ${bottom[1]} ${bottom[0]}`} fill={C.night} />
      </g>
      {close.map((i) => i.el)}
      <Disc x={-z} f={f} front />
      <Disc x={z} f={f} front />
      {[top, bottom].map(([a, b], i) => (
        <g key={i}>
          <line x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} stroke={C.ink} strokeWidth={22} />
          <line x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} stroke={i ? RAMPS.copper[1] : RAMPS.copper[3]} strokeWidth={12} />
        </g>
      ))}
    </g>
  );
};

export const sarcomere: View<"sarcomere"> = {
  Draw,
  anchors: ({ phase, stage }) => {
    const z = zOf(stage);
    const lead = HEADS[LEAD];
    return {
      zline: proj(z, -R - 10, 0),
      actine: proj(z - 110, -2 * GAP * Math.cos(rad(30)), 2 * GAP * Math.sin(rad(30))),
      myosine: proj(-150, 30, 0),
      tete: headAt(lead, frac(phase + lead.offset)).tip,
      mline: proj(0, -R, 0),
    };
  },
};

/** Where the lead head is in its cycle (0..1): steps « s'accroche, tire, lâche, recharge » follow it. */
export const leadCycle = (phase: number) => frac(phase + HEADS[LEAD].offset);
