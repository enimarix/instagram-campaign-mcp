// Draws the pixel blossom tree (src/editorial/blossom.ts) at a frame: bark and blossoms as one
// SVG path per colour (thousands of 4 px squares, cheap to draw), the crown under them in two
// depths, bark with shadow / lit sides and grain, petals falling at three depths (far ones
// behind the crown, near ones big and out of focus), and the gust's wind lines. Plus the flat, sparse tree of the « sans méthode »
// panel.
import { BARK, BLOSSOM, WHITE } from "./palette.ts";
import { seeded } from "../lib/game.ts";
import { easeOut, span } from "../voxel/anim.ts";
import { GUST_RANGE, petalsAt, PX, snap, swayAt, TREE } from "./blossom.ts";

const sq = (x: number, y: number, w: number, h = w) => `M${x} ${y}h${w}v${h}h${-w}z`;

/** A quadratic point. */
const quad = (b: (typeof TREE.branches)[number], t: number) => {
  const m = 1 - t;
  return [m * m * b.x0 + 2 * m * t * b.cx + t * t * b.x1, m * m * b.y0 + 2 * m * t * b.cy + t * t * b.y1];
};

export type TreeState = {
  frame: number;
  /** 0 bare … 1 full bloom. */
  bloom: number;
  /** 0..1: how much of the branches has grown (the first appearance). */
  grow?: number;
  /** −1 leans back … +1 full push. */
  gust?: number;
  /** Falling petals at once. */
  petals?: number;
  /** Frames since the gust's chapter started and its length: wind lines across the crown. */
  wind?: { f: number; len: number };
};

export const Tree = ({ x, y, s, frame, bloom, grow = 1, gust = 0, petals = 6, wind }: TreeState & { x: number; y: number; s: number }) => {
  // Drawn in this order: base, shadow side, lit side, highlight flecks, bark grain.
  const bark: string[] = ["", "", "", "", ""];
  TREE.branches.forEach((b, bi) => {
    const steps = Math.max(2, Math.ceil(Math.hypot(b.x1 - b.x0, b.y1 - b.y0) / (PX * 0.7)));
    for (let i = 0; i <= steps; i++) {
      const t = i / steps;
      const o = b.o0 + (b.o1 - b.o0) * t;
      if (o > grow * 1.25) break;
      const [px, py] = quad(b, t);
      const { dx, dy } = swayAt(-py, px, frame, gust);
      // The trunk flares at its foot.
      const flare = b.depth === 4 && t < 0.14 ? 1 + (0.14 - t) * 4 : 1;
      const w = Math.max(PX, snap((b.w0 + (b.w1 - b.w0) * t) * flare));
      const X = snap(px + dx - w / 2);
      const Y = snap(py + dy);
      bark[0] += sq(X, Y, w, PX * 2);
      const shade = Math.max(PX, snap(w * 0.3));
      bark[1] += sq(X, Y, shade, PX * 2);
      if (w >= PX * 4) bark[2] += sq(X + w - snap(w * 0.25) - PX, Y, snap(w * 0.25), PX * 2);
      if (w >= PX * 5 && i % 4 === 0) bark[3] += sq(X + w - 2 * PX, Y, PX, PX);
      // Grain: dark flecks inside the thicker limbs.
      if (w >= PX * 5 && seeded(bi * 31 + 5, i) < 0.35) bark[4] += sq(X + shade + snap(seeded(bi * 31 + 6, i) * (w - shade - 2 * PX)), Y, PX, PX * 3);
    }
  });
  const open = Math.max(0, Math.min(1, (grow - 0.85) / 0.15)) * bloom;
  const fill: string[] = BLOSSOM.map(() => "");
  let white = "";
  for (const fl of TREE.flowers) {
    const g = (open - fl.u) / 0.06;
    if (g <= 0) continue;
    const { dx, dy } = swayAt(-fl.y, fl.x, frame, gust);
    const X = snap(fl.x + dx);
    const Y = snap(fl.y + dy);
    if (g < 1) {
      fill[fl.shade - 1] += sq(X, Y, PX); // a bud
      continue;
    }
    // A five-petal pixel flower: a plus of petals around its heart (white on the lit side).
    fill[fl.shade] += sq(X - PX, Y, PX) + sq(X + PX, Y, PX) + sq(X, Y - PX, PX) + sq(X, Y + PX, PX);
    if (fl.white) white += sq(X, Y, PX);
    else fill[Math.max(0, fl.shade - 2)] += sq(X, Y, PX);
  }
  // The crown under the blossoms, as pixel discs in two depths, filling in as the tree blooms.
  const fullness = Math.max(0, Math.min(1, (open - 0.25) / 0.6));
  const crown = ["", ""];
  for (const c of TREE.clusters) {
    const { dx, dy } = swayAt(-c.y, c.x, frame, gust);
    [0.78, 0.5].forEach((k, layer) => {
      const r = c.r * k * fullness;
      const [cx, cy] = [c.x + dx + layer * 8, c.y + dy - layer * 10];
      for (let yy = -r; yy <= r; yy += PX) {
        const half = snap(Math.sqrt(Math.max(0, r * r - yy * yy)));
        if (half > 0) crown[layer] += sq(snap(cx) - half, snap(cy + yy), 2 * half, PX);
      }
    });
  }
  const fall = petalsAt(frame, Math.round(petals * Math.min(1, bloom * 1.5)), bloom, Math.max(0, gust));
  const petal = (p: (typeof fall)[number], i: number) => {
    const h = Math.max(PX, snap(p.size * Math.abs(p.flip)));
    return <rect key={i} x={snap(p.x)} y={snap(p.y)} width={p.size} height={h} fill={BLOSSOM[p.color]} opacity={p.o} />;
  };
  return (
    <g transform={`translate(${x} ${y}) scale(${s})`} shapeRendering="crispEdges">
      <defs>
        <filter id="petalBlur" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="2.2" />
        </filter>
      </defs>
      {fall.filter((p) => p.z < 0.35).map(petal)}
      <path d={crown[0]} fill={BLOSSOM[0]} />
      <path d={crown[1]} fill={BLOSSOM[1]} />
      {bark.map((d, i) => (
        <path key={`b${i}`} d={d} fill={BARK[[1, 0, 2, 3, 0][i]]} />
      ))}
      {fill.map((d, i) => (
        <path key={`f${i}`} d={d} fill={BLOSSOM[i]} />
      ))}
      <path d={white} fill={WHITE} />
      {fall.filter((p) => p.z >= 0.35 && p.z < 0.8).map(petal)}
      <g filter="url(#petalBlur)">{fall.filter((p) => p.z >= 0.8).map(petal)}</g>
      {wind && <WindLines f={wind.f} len={wind.len} />}
    </g>
  );
};

/** The gust made visible: white streaks with a curl at the head, sweeping left to right across the crown. */
const WindLines = ({ f, len }: { f: number; len: number }) => {
  const start = Math.round(len * (GUST_RANGE[0] - 0.06));
  return (
    <g fill="none" stroke={WHITE} strokeLinecap="round" strokeWidth={6}>
      {[0, 1, 2, 3, 4].map((k) => {
        const q = span(f, start + k * 3, 18);
        if (q <= 0 || q >= 1) return null;
        const y = -330 - 85 * k + (k % 2) * 30;
        const head = -520 + 1040 * easeOut(q);
        const tail = head - 320 * Math.sin(Math.PI * q);
        const curl = k % 2 === 0 && q > 0.25 && q < 0.85;
        return (
          <g key={k} opacity={Math.sin(Math.PI * q)}>
            <path d={`M${tail} ${y + 10}Q${(tail + head) / 2} ${y - 14} ${head} ${y}`} />
            {curl && <path d={`M${head} ${y}a18 18 0 1 0 -18 -18a10 10 0 1 1 10 10`} strokeWidth={5} />}
          </g>
        );
      })}
    </g>
  );
};

/** The « sans méthode » tree: flat vector, a pale crown with a few dots, no light, barely moving. */
export const FlatTree = ({ x, y, s, frame }: { x: number; y: number; s: number; frame: number }) => {
  const sway = Math.sin(frame / 40) * 3;
  return (
    <g transform={`translate(${x} ${y}) scale(${s})`}>
      <path d="M-16 0L-10 -170L-90 -260M-10 -170L0 -300M-4 -200L80 -270" stroke="#8C6A5A" strokeWidth={22} strokeLinecap="round" fill="none" />
      <ellipse cx={sway} cy={-330} rx={260} ry={150} fill="#F4A9C8" />
      {[-150, -60, 40, 140, -100, 10, 110].map((dx, i) => (
        <circle key={i} cx={dx + sway} cy={-330 + (i > 3 ? 60 : -40)} r={14} fill="#FBD3E4" />
      ))}
    </g>
  );
};
