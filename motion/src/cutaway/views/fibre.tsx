// Fibre and repair views (step 142): one muscle fibre with its front cut away, showing the
// myofibrils striped with sarcomeres (dark A bands, light I bands, thin Z-lines) and nuclei on
// its surface; the bands close up as it contracts. The repair view is the same fibre after a
// workout: micro-tears glow, satellite cells come and fuse into them, new protein fills them
// (yellow, then muscle) and the fibre grows thicker with one more myofibril.
import type { ReactNode } from "react";
import { C } from "../palette";
import { type View, type ViewState, LINE, pulse } from "./common";

const X0 = -360;
const X1 = 300;
const CENTRE = -30;
const smooth = (t: number, a: number, b: number) => {
  const k = Math.min(1, Math.max(0, (t - a) / (b - a)));
  return k * k * (3 - 2 * k);
};

type FibreShape = { r: number; rods: number; newRod: number; c: number };

const rodYs = ({ r, rods }: FibreShape) => Array.from({ length: rods }, (_, k) => -0.7 * r + (k * 1.4 * r) / (rods - 1));
const period = (c: number) => 84 * (1 - 0.22 * c);

/** The fibre: body, striped myofibrils, nuclei, the cut section. */
const Fibre = ({ shape, children }: { shape: FibreShape; children?: ReactNode }) => {
  const { r, c, newRod, rods } = shape;
  const p = period(c);
  const h = Math.min(0.26 * r, (1.4 * r) / (rods - 1) - 10);
  const rx = 0.4 * r;
  return (
    <g>
      <ellipse cx={X0} cy={0} rx={rx} ry={r} fill={C.copperDark} stroke={C.ink} {...LINE} />
      <rect x={X0} y={-r} width={X1 - X0} height={2 * r} fill={C.copperDark} />
      <line x1={X0} y1={-r} x2={X1} y2={-r} stroke={C.cream} strokeWidth={12} />
      <line x1={X0} y1={r} x2={X1} y2={r} stroke={C.cream} strokeWidth={12} />
      {rodYs(shape).map((y, k) => {
        const fresh = k === rods - 1 && newRod < 1;
        if (fresh && newRod <= 0) return null;
        const bands = [];
        // Bands around the centre, closer together as the fibre contracts.
        for (let i = -9; i <= 9; i++) {
          const a = CENTRE + i * p;
          const aw = 0.56 * p;
          const x = Math.max(X0, a - aw / 2);
          const w = Math.min(X1, a + aw / 2) - x;
          if (w > 0) bands.push(<rect key={`a${i}`} x={x} y={y - h / 2} width={w} height={h} fill={C.copper} />);
          const z = a + p / 2;
          if (z > X0 && z < X1) bands.push(<rect key={`z${i}`} x={z - 3} y={y - h / 2} width={6} height={h} fill={C.ink} />);
        }
        return (
          <g key={k} opacity={fresh ? newRod : 1}>
            <rect x={X0 + 20} y={y - h / 2} width={X1 - X0 - 20} height={h} rx={h / 2} fill={fresh ? C.yellow : C.cream} />
            {!fresh && bands}
          </g>
        );
      })}
      {[-250, 0, 200].map((x) => (
        <ellipse key={x} cx={x} cy={-r + 4} rx={36} ry={15} fill={C.steel} stroke={C.ink} {...LINE} />
      ))}
      <ellipse cx={X1} cy={0} rx={rx} ry={r} fill={C.copper} stroke={C.cream} {...LINE} />
      {Array.from({ length: 5 }, (_, i) =>
        Array.from({ length: 3 }, (_, j) => <rect key={`${i}-${j}`} x={X1 + (j - 1) * rx * 0.45 - 6} y={(i - 2) * r * 0.32 - 6} width={12} height={12} fill={C.copperLight} />),
      )}
      {children}
    </g>
  );
};

const fibreShape = (phase: number): FibreShape => ({ r: 150, rods: 5, newRod: 1, c: 0.7 * pulse(phase) });

export const fibre: View<"fibre"> = {
  Draw: ({ phase }: ViewState) => <Fibre shape={fibreShape(phase)} />,
  anchors: ({ phase }) => {
    const s = fibreShape(phase);
    const ys = rodYs(s);
    const p = period(s.c);
    return { fibre: [-150, -s.r], myofibrille: [120, ys[1]], sarcomere: [CENTRE + p / 2, ys[3]], noyau: [0, -s.r + 4] };
  },
};

// --- Repair: the same fibre after training.
const TEARS = [-220, 30, 220];
const CELLS = [
  { tear: 0, from: [-280, -380], side: -1 },
  { tear: 1, from: [90, 400], side: 1 },
  { tear: 1, from: [-40, -400], side: -1 },
  { tear: 2, from: [280, 380], side: 1 },
] as const;

const repairOf = (stage: number) => ({
  shape: { r: 150 + 34 * smooth(stage, 0.6, 1), rods: 6, newRod: smooth(stage, 0.72, 0.95), c: 0 } as FibreShape,
  tears: 1 - smooth(stage, 0.5, 0.75),
  arrive: smooth(stage, 0.1, 0.45),
  fuse: smooth(stage, 0.45, 0.6),
  fill: smooth(stage, 0.5, 0.7),
  settle: smooth(stage, 0.8, 1),
});

const cellAt = (stage: number, k: number, f: number) => {
  const { shape, arrive } = repairOf(stage);
  const c = CELLS[k];
  const target = [TEARS[c.tear] + c.side * 18, c.side * (shape.r - 30)];
  const wob = Math.sin(f / 7 + k) * 5;
  return [c.from[0] + (target[0] - c.from[0]) * arrive + wob, c.from[1] + (target[1] - c.from[1]) * arrive] as const;
};

const crack = (x: number, r: number) =>
  Array.from({ length: 9 }, (_, i) => `${x + (i % 2 ? 16 : -16)},${-0.82 * r + (i * 1.64 * r) / 8}`).join(" ");

export const repair: View<"repair"> = {
  Draw: ({ stage, f }: ViewState) => {
    const s = repairOf(stage);
    const r = s.shape.r;
    return (
      <Fibre shape={s.shape}>
        {TEARS.map((x) => (
          <g key={x}>
            {s.tears > 0 && <rect x={x - 34} y={-0.86 * r} width={68} height={1.72 * r} fill={C.red} opacity={0.45 * s.tears * (0.75 + 0.25 * Math.sin(f / 4))} />}
            {s.tears > 0 && <polyline points={crack(x, r)} fill="none" stroke={C.ink} strokeWidth={14} opacity={s.tears} />}
            {s.fill > 0 && <rect x={x - 22} y={-0.8 * r} width={44} height={1.6 * r} fill={C.yellow} opacity={s.fill * (1 - s.settle)} />}
          </g>
        ))}
        {CELLS.map((_, k) => {
          const [x, y] = cellAt(stage, k, f);
          const rr = 36 * (1 - s.fuse);
          return rr > 1 && s.arrive > 0 ? (
            <g key={k}>
              <circle cx={x} cy={y} r={rr} fill={C.teal} stroke={C.ink} {...LINE} />
              <circle cx={x} cy={y} r={rr * 0.45} fill={C.tealDark} />
            </g>
          ) : null;
        })}
      </Fibre>
    );
  },
  anchors: ({ stage, f }) => {
    const s = repairOf(stage);
    return { fibre: [-150, -s.shape.r], dechirure: [TEARS[1], -0.3 * s.shape.r], cellule: cellAt(stage, 1, f), proteine: [TEARS[1], 0.3 * s.shape.r] };
  },
};
