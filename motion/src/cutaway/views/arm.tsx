// Arm view (step 142): the whole arm in side view with the skin cut away, curling a dumbbell.
// The biceps shortens and bulges as the forearm comes up (sparkling as it fires), the triceps
// relaxes behind the bone. One curl per cycle.
import { C } from "../palette";
import { type View, type ViewState, LINE, pulse, rad, Sparkles } from "./common";

const S = [-60, -170] as const; // shoulder
const E = [-20, 190] as const; // elbow
const FORE = 270;

type V2 = readonly [number, number];
const add = (a: V2, b: V2, k = 1): V2 => [a[0] + b[0] * k, a[1] + b[1] * k];

const geometry = (phase: number) => {
  const c = pulse(phase);
  const a = rad(14 + 116 * c);
  const dir: V2 = [Math.sin(a), Math.cos(a)];
  const front: V2 = [Math.cos(a), -Math.sin(a)]; // the forearm's front side
  const wrist = add(E, dir, FORE);
  const O: V2 = [-30, -130];
  const I = add(add(E, dir, 55), front, 16);
  const mid: V2 = [(O[0] + I[0]) / 2, (O[1] + I[1]) / 2];
  const len = Math.hypot(I[0] - O[0], I[1] - O[1]);
  const n: V2 = [-(I[1] - O[1]) / len, (I[0] - O[0]) / len]; // to the front (+x)
  const bulge = 44 + 44 * c;
  const tO: V2 = [-92, -120];
  const tI: V2 = add(E, [-30, 22]);
  const tMid: V2 = [(tO[0] + tI[0]) / 2, (tO[1] + tI[1]) / 2];
  return { c, dir, front, wrist, O, I, mid, n, bulge, tO, tI, tMid };
};

/** A lens-shaped muscle from `a` to `b`, bulging `out` toward `nn`. */
const lens = (a: V2, b: V2, m: V2, nn: V2, out: number, back: number) =>
  `M${a[0]} ${a[1]}Q${m[0] + nn[0] * out * 2} ${m[1] + nn[1] * out * 2} ${b[0]} ${b[1]}Q${m[0] - nn[0] * back} ${m[1] - nn[1] * back} ${a[0]} ${a[1]}Z`;

const Capsule = ({ a, b, w }: { a: V2; b: V2; w: number }) => (
  <>
    <line x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} stroke={C.cream} strokeWidth={w + 16} strokeLinecap="round" />
    <line x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} stroke={C.violet} strokeWidth={w} strokeLinecap="round" />
  </>
);

const Draw = ({ phase, f }: ViewState) => {
  const { c, dir, front, wrist, O, I, mid, n, bulge, tO, tI, tMid } = geometry(phase);
  const side: V2 = [dir[1], -dir[0]];
  const elbowTip = add(E, [-28, 22]);
  const grip = add(wrist, dir, 34);
  return (
    <g>
      {/* Skin, cut away: a glassy capsule over the upper arm and the forearm, the shoulder cap. */}
      <circle cx={S[0] - 10} cy={S[1] - 20} r={120} fill={C.cream} />
      <circle cx={S[0] - 10} cy={S[1] - 20} r={112} fill={C.violet} />
      <Capsule a={S} b={E} w={210} />
      <Capsule a={E} b={wrist} w={150} />
      <circle cx={S[0] - 10} cy={S[1] - 20} r={84} fill={C.copperDark} stroke={C.ink} {...LINE} />
      {/* Bones: humerus, radius and ulna. */}
      <line x1={S[0]} y1={S[1]} x2={E[0]} y2={E[1]} stroke={C.ink} strokeWidth={50} strokeLinecap="round" />
      <line x1={S[0]} y1={S[1]} x2={E[0]} y2={E[1]} stroke={C.cream} strokeWidth={34} strokeLinecap="round" />
      {[-15, 15].map((k) => {
        const a = add(E, side, k);
        const b = add(wrist, side, k * 0.7);
        return (
          <g key={k}>
            <line x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} stroke={C.ink} strokeWidth={28} strokeLinecap="round" />
            <line x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} stroke={C.cream} strokeWidth={16} strokeLinecap="round" />
          </g>
        );
      })}
      <circle cx={elbowTip[0]} cy={elbowTip[1]} r={30} fill={C.cream} stroke={C.ink} {...LINE} />
      {/* Triceps behind the bone, biceps in front with its fibres. */}
      <path d={lens(tO, tI, tMid, [-1, 0], 40 - 12 * c, 8)} fill={C.copperDark} stroke={C.ink} {...LINE} />
      <path d={lens(O, I, mid, n, bulge, 12)} fill={C.copper} stroke={C.ink} {...LINE} />
      {[0.3, 0.55, 0.8].map((k) => (
        <path key={k} d={`M${O[0]} ${O[1]}Q${mid[0] + n[0] * bulge * 2 * k} ${mid[1] + n[1] * bulge * 2 * k} ${I[0]} ${I[1]}`} fill="none" stroke={C.copperLight} strokeWidth={7} />
      ))}
      <Sparkles cx={mid[0] + n[0] * bulge * 0.6} cy={mid[1] + n[1] * bulge * 0.6} rx={bulge * 0.55} ry={120} n={26} seed={11} f={f} on={0.2 + 0.8 * c} color={C.tealLight} />
      {/* Tendons. */}
      <line x1={O[0]} y1={O[1]} x2={S[0] + 10} y2={S[1] - 40} stroke={C.white} strokeWidth={14} />
      <line x1={I[0]} y1={I[1]} x2={E[0] + dir[0] * 85} y2={E[1] + dir[1] * 85} stroke={C.white} strokeWidth={14} />
      {/* Fist round the dumbbell's handle; the bar runs across, plates on both ends. */}
      {[-1, 1].map((k) => {
        const p = add(grip, front, k * 92);
        const q = add(grip, front, k * 120);
        return (
          <g key={k}>
            <line x1={grip[0]} y1={grip[1]} x2={q[0]} y2={q[1]} stroke={C.ink} strokeWidth={30} />
            <line x1={grip[0]} y1={grip[1]} x2={q[0]} y2={q[1]} stroke={C.steel} strokeWidth={16} />
            <line x1={p[0]} y1={p[1]} x2={q[0]} y2={q[1]} stroke={C.ink} strokeWidth={134} />
            <line x1={p[0] + front[0] * 6 * k} y1={p[1] + front[1] * 6 * k} x2={q[0] - front[0] * 6 * k} y2={q[1] - front[1] * 6 * k} stroke={C.steelDark} strokeWidth={118} />
            <line x1={p[0] + front[0] * 10 * k} y1={p[1] + front[1] * 10 * k} x2={q[0] - front[0] * 10 * k} y2={q[1] - front[1] * 10 * k} stroke={C.steel} strokeWidth={60} />
          </g>
        );
      })}
      <circle cx={grip[0]} cy={grip[1]} r={52} fill={C.peach} stroke={C.ink} {...LINE} />
      <circle cx={grip[0] - dir[0] * 10} cy={grip[1] - dir[1] * 10} r={22} fill={C.orange} />
    </g>
  );
};

export const arm: View<"arm"> = {
  Draw,
  anchors: ({ phase }) => {
    const g = geometry(phase);
    return {
      biceps: [g.mid[0] + g.n[0] * g.bulge * 0.9, g.mid[1] + g.n[1] * g.bulge * 0.9],
      triceps: [g.tMid[0] - 44, g.tMid[1]],
      tendon: g.I,
      os: [(S[0] + E[0]) / 2, (S[1] + E[1]) / 2],
      coude: [E[0] - 28, E[1] + 22],
      haltere: add(g.wrist, g.dir, 34),
      avantbras: add(E, g.dir, FORE / 2),
    };
  },
};
