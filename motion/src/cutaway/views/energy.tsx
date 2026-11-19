// Energy views (step 142): where fat goes. The fat cell: a fat droplet filling the cell, the
// nucleus squeezed to its edge; as `stage` rises the droplet empties into the blood as fatty
// acids (zigzag chains riding the blood cells down the vessel). The mitochondrion: fatty acids
// and O₂ flow in, the cristae spark as they burn, ATP rises out, CO₂ and water leave.
import { C } from "../palette";
import { type View, type ViewState, frac, LINE, pulse, Spark, Sparkles } from "./common";

type P = readonly [number, number];
const lerp = (a: P, b: P, t: number): P => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];

/** A fatty acid: a zigzag carbon chain with its head. */
const FattyAcid = ({ x, y, k = 1 }: { x: number; y: number; k?: number }) => (
  <g transform={`translate(${x} ${y}) scale(${k})`}>
    <polyline points="-40,0 -22,-10 -4,0 14,-10 32,0" fill="none" stroke={C.ink} strokeWidth={16} strokeLinejoin="round" />
    <polyline points="-40,0 -22,-10 -4,0 14,-10 32,0" fill="none" stroke={C.yellow} strokeWidth={8} strokeLinejoin="round" />
    <circle cx={40} cy={-2} r={11} fill={C.copperLight} stroke={C.ink} {...LINE} />
  </g>
);

const Atom = ({ x, y, r, fill }: { x: number; y: number; r: number; fill: string }) => <circle cx={x} cy={y} r={r} fill={fill} stroke={C.ink} {...LINE} />;
const O2 = ({ x, y }: { x: number; y: number }) => (
  <>
    <Atom x={x - 13} y={y} r={15} fill={C.tealLight} />
    <Atom x={x + 13} y={y} r={15} fill={C.tealLight} />
  </>
);
const CO2 = ({ x, y }: { x: number; y: number }) => (
  <>
    <Atom x={x - 26} y={y} r={14} fill={C.tealLight} />
    <Atom x={x + 26} y={y} r={14} fill={C.tealLight} />
    <Atom x={x} y={y} r={17} fill={C.steelDeep} />
  </>
);
const H2O = ({ x, y }: { x: number; y: number }) => (
  <>
    <Atom x={x - 18} y={y + 14} r={10} fill={C.white} />
    <Atom x={x + 18} y={y + 14} r={10} fill={C.white} />
    <Atom x={x} y={y} r={18} fill={C.hudBlue} />
  </>
);

// --- The fat cell.
const R = 260;
const VESSEL = 380;
const ACIDS = 7;

const fatOf = (stage: number) => ({ rd: 228 * (1 - 0.55 * stage), nucleus: [R * 0.8 * Math.cos(-0.75), R * 0.8 * Math.sin(-0.75)] as P });

/** Fatty acid `k` along its way: out of the droplet, through the membrane, down the vessel. */
const acidAt = (phase: number, stage: number, k: number): P => {
  const q = frac(phase * 0.6 + k / ACIDS);
  const a = -0.5 + (k % 4) * 0.33;
  const { rd } = fatOf(stage);
  const start: P = [-20 + Math.cos(a) * rd, 10 + Math.sin(a) * rd];
  const entry: P = [VESSEL, Math.sin(a) * R * 0.7];
  return q < 0.5 ? lerp(start, entry, q / 0.5) : lerp(entry, [VESSEL, 560], (q - 0.5) / 0.5);
};

export const fat: View<"fat"> = {
  Draw: ({ phase, stage, f }: ViewState) => {
    const { rd, nucleus } = fatOf(stage);
    return (
      <g>
        <rect x={VESSEL - 70} y={-400} width={140} height={960} fill={C.copperDark} stroke={C.ink} {...LINE} />
        <rect x={VESSEL - 52} y={-400} width={104} height={960} fill={C.copper} />
        {Array.from({ length: 8 }, (_, k) => {
          const y = ((k * 120 + phase * 600) % 960) - 400;
          return <ellipse key={k} cx={VESSEL + (k % 2 ? 18 : -18)} cy={y} rx={30} ry={16} fill={C.red} stroke={C.ink} {...LINE} />;
        })}
        <circle cx={0} cy={0} r={R} fill={C.mauve} stroke={C.cream} strokeWidth={14} />
        <circle cx={-20} cy={10} r={rd} fill={C.orange} stroke={C.yellowDark} {...LINE} />
        <path d={`M${-20 + rd} ${10}A${rd} ${rd} 0 0 1 ${-20 - rd} ${10}A${rd} ${rd * 0.55} 0 0 0 ${-20 + rd} ${10}Z`} fill={C.yellowDark} opacity={0.55} />
        <circle cx={-20 - rd * 0.35} cy={10 - rd * 0.4} r={rd * 0.28} fill={C.sun} />
        <Sparkles cx={-20} cy={10} rx={rd * 0.8} ry={rd * 0.8} n={30} seed={51} f={f} color={C.yellow} />
        <ellipse cx={nucleus[0]} cy={nucleus[1]} rx={52} ry={22} transform={`rotate(-40 ${nucleus[0]} ${nucleus[1]})`} fill={C.steel} stroke={C.ink} {...LINE} />
        {stage > 0.02 && Array.from({ length: ACIDS }, (_, k) => {
          const [x, y] = acidAt(phase, stage, k);
          return <FattyAcid key={k} x={x} y={y} k={0.9} />;
        })}
      </g>
    );
  },
  anchors: ({ phase, stage }) => {
    const { rd, nucleus } = fatOf(stage);
    return { cellule: [-R * 0.72, -R * 0.72], goutte: [-20 - rd * 0.3, 10 + rd * 0.3], noyau: nucleus, acides: acidAt(phase, Math.max(stage, 0.3), 1), sang: [VESSEL, 330] };
  },
};

// --- The mitochondrion.
const CRISTAE = [-270, -180, -90, 0, 90, 180, 270];

export const mito: View<"mito"> = {
  Draw: ({ phase, f }: ViewState) => {
    const q = (i: number, n: number) => frac(phase * 0.5 + i / n);
    return (
      <g>
        <ellipse cx={0} cy={0} rx={390} ry={190} fill={C.copper} stroke={C.cream} strokeWidth={14} />
        <path d="M-330 -60A390 190 0 0 1 330 -60" fill="none" stroke={C.copperLight} strokeWidth={14} strokeLinecap="round" />
        <path d="M-300 120A390 190 0 0 0 300 120" fill="none" stroke={C.copperDark} strokeWidth={18} strokeLinecap="round" />
        <ellipse cx={0} cy={0} rx={352} ry={154} fill={C.copperDark} stroke={C.copperLight} strokeWidth={8} />
        {CRISTAE.map((x, k) => {
          const top = k % 2 === 0;
          const edge = 154 * Math.sqrt(Math.max(0, 1 - (x / 352) ** 2));
          const y0 = top ? -edge : edge;
          const y1 = top ? 40 : -40;
          return <rect key={x} x={x - 20} y={Math.min(y0, y1)} width={40} height={Math.abs(y1 - y0)} rx={20} fill={C.copperLight} stroke={C.copperDark} strokeWidth={6} />;
        })}
        <Sparkles cx={0} cy={0} rx={300} ry={110} n={36} seed={61} f={f} color={C.tealLight} size={8} />
        {[0, 1, 2].map((k) => (
          <Spark key={k} x={-110 + k * 110} y={k % 2 ? 50 : -40} r={30 * pulse(phase + k / 3)} color={C.yellow} />
        ))}
        {/* In: fatty acids and oxygen from the left. */}
        {[0, 1, 2].map((i) => {
          const t = q(i, 3);
          return <FattyAcid key={`fa${i}`} x={-640 + t * 520} y={-60} />;
        })}
        {[0, 1, 2].map((i) => {
          const t = q(i + 0.5, 3);
          return <O2 key={`o${i}`} x={-640 + t * 520} y={70} />;
        })}
        {/* Out: CO₂ and water to the right, ATP up. */}
        {[0, 1, 2].map((i) => {
          const t = q(i, 3);
          return <CO2 key={`c${i}`} x={140 + t * 520} y={-70 - t * 90} />;
        })}
        {[0, 1].map((i) => {
          const t = q(i + 0.25, 2);
          return <H2O key={`w${i}`} x={140 + t * 520} y={80 + t * 40} />;
        })}
        {[0, 1].map((i) => {
          const t = q(i + 0.6, 2);
          return <Spark key={`atp${i}`} x={-20 + t * 60} y={-60 - t * 380} r={26} color={C.yellow} />;
        })}
      </g>
    );
  },
  anchors: () => ({ mitochondrie: [-250, -150], crete: [-90, 0], o2: [-470, 70], co2: [460, -150], eau: [460, 110], atp: [20, -300] }),
};
