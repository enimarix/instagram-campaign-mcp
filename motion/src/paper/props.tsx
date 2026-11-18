// Paper props (step 131), redrawn in SVG from the owner's paper.js: foods as round cut-out
// stickers (in their macro colours), the fridge, the clock, the phone with the app's screen
// rebuilt in vectors, a plate, a lock, cross and check marks, a receipt slip and paper
// confetti. Every piece is an SVG group for a scene's <svg> (which holds <CutDefs />).
import type { ReactNode } from "react";
import { frenchSpaces } from "../lib/french";
import { seeded } from "../lib/game";
import { cutRect, HAND_FONT, LABEL_FONT, wobble } from "./kit";
import { BRAND, CREAM, INK, MACRO, type PaperFoodId, RED } from "./palette.ts";

const T = (x: number, y: number, s = 1, rot = 0) => `translate(${x} ${y}) rotate(${rot}) scale(${s})`;

/** The foods drawn in a 200 px box centred on 0, 0. */
const FOOD_ART: Record<PaperFoodId, ReactNode> = {
  pizza: (
    <g transform="rotate(-12)">
      <path d="M-72,-58 L72,-58 L0,84Z" fill="#FFD36B" />
      <path d="M-80,-76 Q0,-96 80,-76 L76,-52 Q0,-70 -76,-52Z" fill="#D9963F" />
      {[[-26, -28], [24, -22], [0, 22]].map(([x, y]) => (
        <circle key={x} cx={x} cy={y} r={14} fill={RED} />
      ))}
    </g>
  ),
  apple: (
    <g>
      <path d="M0,-44 C-30,-70 -82,-56 -78,4 C-74,60 -36,84 0,70 C36,84 74,60 78,4 C82,-56 30,-70 0,-44Z" fill="#E5484D" />
      <path d="M-4,-44 Q-2,-70 10,-84" stroke="#7A5233" strokeWidth={9} strokeLinecap="round" fill="none" />
      <path d="M10,-70 Q40,-96 58,-72 Q32,-56 10,-70Z" fill="#3C9D5D" />
      <ellipse cx={-38} cy={-14} rx={10} ry={22} fill="rgba(255,255,255,.35)" />
    </g>
  ),
  drumstick: (
    <g transform="rotate(-35)">
      <rect x={-12} y={10} width={24} height={70} rx={10} fill="#FFF3E0" />
      <circle cx={-12} cy={82} r={14} fill="#FFF3E0" />
      <circle cx={12} cy={82} r={14} fill="#FFF3E0" />
      <path d="M0,-84 C52,-84 62,-20 30,22 Q0,40 -30,22 C-62,-20 -52,-84 0,-84Z" fill="#B5652E" />
      <ellipse cx={-14} cy={-46} rx={12} ry={22} fill="rgba(255,255,255,.25)" />
    </g>
  ),
  pasta: (
    <g>
      <path d="M-84,-6 Q-70,74 0,78 Q70,74 84,-6Z" fill="#F28C5B" />
      <path d="M-70,-10 Q-50,-56 -10,-50 Q20,-74 50,-46 Q78,-40 70,-10Z" fill="#F7D774" />
      <path d="M-46,-26 q12,-16 24,0 t24,0 t24,0" stroke="#E0B84A" strokeWidth={6} fill="none" strokeLinecap="round" />
      <circle cx={30} cy={-40} r={10} fill={RED} />
      <ellipse cx={0} cy={-6} rx={84} ry={12} fill="#D9734A" />
    </g>
  ),
  egg: (
    <g>
      <path d={wobble(0, 6, 80, 5, 66)} fill="#FFFFFF" stroke="#EFE6D6" strokeWidth={4} />
      <circle cx={8} cy={0} r={32} fill="#FFC21A" />
      <circle cx={-2} cy={-10} r={9} fill="rgba(255,255,255,.6)" />
    </g>
  ),
  avocado: (
    <g transform="rotate(10) scale(0.78) translate(-95 -122)">
      <path d="M95 10 C140 10 168 96 176 150 C186 210 146 234 95 234 C44 234 4 210 14 150 C22 96 50 10 95 10Z" fill="#2F6B3A" />
      <path d="M95 26 C132 26 156 100 162 150 C170 202 138 220 95 220 C52 220 20 202 28 150 C34 100 58 26 95 26Z" fill="#CFE6A0" />
      <circle cx={95} cy={156} r={40} fill="#8A5A3B" />
      <circle cx={82} cy={142} r={10} fill="#A8754F" />
    </g>
  ),
  rice: (
    <g>
      <path d="M-62,-16 Q-50,-74 0,-74 Q50,-74 62,-16Z" fill="#FFFFFF" />
      {[[-30, -40], [-6, -56], [18, -42], [36, -26], [-40, -22], [4, -30]].map(([x, y]) => (
        <ellipse key={`${x}${y}`} cx={x} cy={y} rx={7} ry={4} fill="#EDE3D1" transform={`rotate(${x} ${x} ${y})`} />
      ))}
      <path d="M-84,-16 Q-74,72 0,74 Q74,72 84,-16Z" fill={MACRO.kcal} />
      <path d="M-70,10 L70,10" stroke="rgba(255,255,255,.5)" strokeWidth={8} />
    </g>
  ),
  cheese: (
    <g>
      <path d="M-80,40 L80,40 L80,-6 L-60,-56Z" fill="#F5C242" />
      <path d="M-80,40 L-60,-56 L-80,-30Z" fill="#E3AC2C" />
      {[[-20, 6, 12], [36, 20, 9], [44, -6, 7], [-46, 26, 7]].map(([x, y, r]) => (
        <circle key={x} cx={x} cy={y} r={r} fill="#D99A1E" />
      ))}
    </g>
  ),
  bread: (
    <g>
      <path d="M-70,74 L-70,-20 Q-92,-40 -78,-62 Q-60,-86 0,-84 Q60,-86 78,-62 Q92,-40 70,-20 L70,74Z" fill="#C98A4B" />
      <path d="M-56,62 L-56,-20 Q-74,-36 -64,-52 Q-48,-70 0,-68 Q48,-70 64,-52 Q74,-36 56,-20 L56,62Z" fill="#F6DDB0" />
    </g>
  ),
  yogurt: (
    <g>
      <path d="M-56,-50 L56,-50 L44,74 L-44,74Z" fill="#FFFFFF" stroke="#EFE6D6" strokeWidth={4} />
      <rect x={-62} y={-66} width={124} height={22} rx={8} fill={MACRO.protein} />
      <path d="M-50,0 L50,0 L47,30 L-47,30Z" fill="#FFB3C1" />
    </g>
  ),
};

/** A food on a round white sticker (paper.js sticker), `size` px wide. */
export const FoodSticker = ({ food, x, y, size, rot = 0, seed = 1 }: { food: PaperFoodId; x: number; y: number; size: number; rot?: number; seed?: number }) =>
  size <= 1 ? null : (
    <g transform={T(x, y, size / 200, rot)}>
      <path d={wobble(0, 0, 118, seed)} fill="#FFFFFF" filter="url(#cut15)" />
      <g transform="scale(0.82)">{FOOD_ART[food]}</g>
    </g>
  );

/** The fridge (p1_21h.html), centre (x, y), 360 × 800 at scale 1; `open` 0..1 swings the door. */
export const Fridge = ({ x, y, s, open, foods = [] }: { x: number; y: number; s: number; open: number; foods?: PaperFoodId[] }) => {
  const w = 360 * Math.max(0.06, Math.cos(open * 1.35));
  return (
    <g transform={T(x, y, s)}>
      <rect x={-180} y={-400} width={360} height={800} rx={40} fill="#DDE5EC" filter="url(#cut2)" />
      {open > 0 && (
        <>
          <rect x={-160} y={-380} width={320} height={760} rx={30} fill="#FFF4CC" />
          {[-160, 40, 220].map((sy) => (
            <rect key={sy} x={-160} y={sy} width={320} height={10} fill="#E7D9A8" />
          ))}
          {foods.slice(0, 3).map((food, i) => (
            <FoodSticker key={i} food={food} x={[-70, 60, -50][i]} y={[-240, -60, 130][i]} size={96} seed={i + 3} />
          ))}
        </>
      )}
      <rect x={-180} y={-400} width={w} height={800} rx={40} fill="#F2F6F9" filter="url(#cut2)" />
      {w > 60 && (
        <>
          <rect x={-180 + w - 40} y={-180} width={14} height={140} rx={7} fill="#AAB4BF" />
          <rect x={-180} y={-90} width={w} height={8} fill="rgba(0,0,0,.06)" />
        </>
      )}
    </g>
  );
};

/** A wall clock (paper.js clock), radius r, showing `hour`:`minute`. */
export const Clock = ({ x, y, r, hour, minute }: { x: number; y: number; r: number; hour: number; minute: number }) => {
  const ah = (((hour % 12) + minute / 60) / 12) * 360;
  const am = (minute / 60) * 360;
  return (
    <g transform={T(x, y)}>
      <path d={wobble(0, 0, r, 21)} fill="#FFFFFF" filter="url(#cut15)" />
      {Array.from({ length: 12 }, (_, k) => {
        const a = (k / 12) * Math.PI * 2;
        return <line key={k} x1={Math.cos(a) * r * 0.78} y1={Math.sin(a) * r * 0.78} x2={Math.cos(a) * r * 0.9} y2={Math.sin(a) * r * 0.9} stroke={INK} strokeWidth={k % 3 ? 4 : 8} strokeLinecap="round" />;
      })}
      <line x1={0} y1={0} x2={0} y2={-r * 0.5} stroke={INK} strokeWidth={14} strokeLinecap="round" transform={`rotate(${ah})`} />
      <line x1={0} y1={0} x2={0} y2={-r * 0.75} stroke={MACRO.protein} strokeWidth={8} strokeLinecap="round" transform={`rotate(${am})`} />
      <circle r={12} fill={INK} />
    </g>
  );
};

/** A plate (paper.js plate), radius 260 × 120 at scale 1. */
export const Plate = ({ x, y, s, children }: { x: number; y: number; s: number; children?: ReactNode }) => (
  <g transform={T(x, y, s)}>
    <path d={wobble(0, 0, 260, 31, 120)} fill="#FFFFFF" filter="url(#cut15)" />
    <ellipse rx={200} ry={90} fill="none" stroke="#E5DCCB" strokeWidth={6} />
    {children}
  </g>
);

/** A progress ring (track + arc), `p` 0..1 clockwise from 12 o'clock. */
export const Ring = ({ r, p, color, width = r * 0.2 }: { r: number; p: number; color: string; width?: number }) => {
  const c = 2 * Math.PI * r;
  return (
    <g>
      <circle r={r} fill="none" stroke="#E5DCCB" strokeWidth={width} />
      <circle r={r} fill="none" stroke={color} strokeWidth={width} strokeLinecap="round" strokeDasharray={`${c * Math.min(1, Math.max(0, p))} ${c}`} transform="rotate(-90)" />
    </g>
  );
};

const text = (s: string, x: number, y: number, size: number, color: string, o: { weight?: number; anchor?: "start" | "middle" | "end"; family?: string } = {}) => (
  <text x={x} y={y} fontFamily={o.family ?? LABEL_FONT} fontWeight={o.weight ?? 700} fontSize={size} fill={color} textAnchor={o.anchor ?? "middle"} dominantBaseline="central">
    {frenchSpaces(s)}
  </text>
);

export type PhoneScreen = {
  /** The ring's progress, 0..1. */
  ring: number;
  value: string;
  unit: string;
  /** Macro bars (protein, fat, carbs), 0..1 each. */
  bars: [number, number, number];
  button: string;
  /** Button pressed (scaled down). */
  pressed: boolean;
};

/**
 * The phone with the app's day screen rebuilt in vectors (p1_21h.html sC): « Aujourd'hui »,
 * the calorie ring with the number left, macro bars, the green button. Centre (x, y), 440 ×
 * 880 at scale 1; `sy` squashes it vertically for the pop-in.
 */
export const Phone = ({ x, y, s, sy = 1, screen }: { x: number; y: number; s: number; sy?: number; screen: PhoneScreen }) => (
  <g transform={`translate(${x} ${y + 440 * s}) scale(${s} ${s * sy}) translate(0 -440)`}>
    <rect x={-220} y={-440} width={440} height={880} rx={54} fill="#1E232B" filter="url(#cut2)" />
    <rect x={-204} y={-424} width={408} height={848} rx={40} fill={CREAM} />
    <rect x={-50} y={-412} width={100} height={26} rx={13} fill="#1E232B" />
    {text("Aujourd'hui", 0, -330, 34, "#8b7d6b", { weight: 600 })}
    <g transform="translate(0 -130)">
      <Ring r={130} p={screen.ring} color={MACRO.kcal} />
    </g>
    {text(screen.value, 0, -150, screen.value.length > 5 ? 56 : 72, INK)}
    {text(screen.unit, 0, -88, 28, "#8b7d6b", { weight: 600 })}
    {[MACRO.protein, MACRO.fat, MACRO.carbs].map((c, i) => (
      <g key={c}>
        <rect x={-150} y={60 + i * 46} width={300} height={22} rx={11} fill="#E5DCCB" />
        {screen.bars[i] > 0 && <rect x={-150} y={60 + i * 46} width={300 * Math.min(1, screen.bars[i])} height={22} rx={11} fill={c} />}
      </g>
    ))}
    <g transform={`translate(0 276) scale(${screen.pressed ? 0.94 : 1})`}>
      <rect x={-170} y={-45} width={340} height={90} rx={45} fill={BRAND} filter="url(#cut1)" />
      {text(screen.button, 0, 0, screen.button.length > 20 ? 26 : 30, "#FFFFFF")}
    </g>
  </g>
);

/** A padlock (paper.js lockP), `lk` 1 = shut. */
export const Lock = ({ x, y, s }: { x: number; y: number; s: number }) => (
  <g transform={T(x, y, s)}>
    <path d="M-22,-4 L-22,-18 A22,22 0 0 1 22,-18 L22,-14" stroke="#B07A00" strokeWidth={10} strokeLinecap="round" fill="none" />
    <rect x={-32} y={-14} width={64} height={48} rx={10} fill="#F5B90A" filter="url(#cut05)" />
    <circle cy={8} r={7} fill="#8A5A00" />
  </g>
);

/** A red paper cross (paper.js xmark), 160 px at scale 1. */
export const XMark = ({ x, y, s }: { x: number; y: number; s: number }) =>
  s <= 0 ? null : (
    <g transform={T(x, y, s)} filter="url(#cut1)">
      {[45, -45].map((r, i) => (
        <path key={r} d={cutRect(-80, -16, 160, 32, 3 + i, 3)} fill={RED} transform={`rotate(${r})`} />
      ))}
    </g>
  );

/** A green paper check mark (paper.js check). */
export const Check = ({ x, y, s, color = BRAND }: { x: number; y: number; s: number; color?: string }) =>
  s <= 0 ? null : (
    <g transform={T(x, y, s)} filter="url(#cut1)">
      <path d="M-70,0 L-24,44 L74,-58 L56,-76 L-24,6 L-52,-20Z" fill={color} />
    </g>
  );

/** A torn receipt slip (paper.js slip): « environ » handwritten over the number. */
export const Slip = ({ x, y, rot, small, big, color = INK }: { x: number; y: number; rot: number; small: string; big: string; color?: string }) => {
  const zig = Array.from({ length: 12 }, (_, i) => `${165 - i * 30},${70 + (i % 2 ? 18 : 0)}`).join(" L");
  return (
    <g transform={T(x, y, 1, rot)}>
      <path d={`M-165,-88 L165,-88 L165,70 L${zig}Z`} fill="#FFFFFF" filter="url(#cut15)" />
      {text(small, -140, -44, 44, "#8b7d6b", { family: HAND_FONT, anchor: "start" })}
      {text(big, -140, 18, Math.min(58, Math.floor(290 / (big.length * 0.56))), color, { anchor: "start" })}
    </g>
  );
};

/** Paper confetti burst from (x, y) at frame `start`: seeded bits in the macro colours, falling. */
export const Confetti = ({ x, y, f, start, fps, n = 36 }: { x: number; y: number; f: number; start: number; fps: number; n?: number }) => {
  const t = (f - start) / fps;
  if (t < 0 || t > 1.8) return null;
  const colors = [BRAND, MACRO.protein, MACRO.fat, MACRO.kcal, "#A78BFA", CREAM];
  return (
    <g>
      {Array.from({ length: n }, (_, i) => {
        const a = seeded(7, i) * Math.PI * 2;
        const v = 300 + seeded(8, i) * 1200;
        const px = x + Math.cos(a) * v * t;
        const py = y + Math.sin(a) * v * t + 0.5 * 1600 * t * t;
        const size = 14 + seeded(9, i) * 16;
        const spin = (seeded(10, i) - 0.5) * 720 * t;
        return <rect key={i} x={-size / 2} y={-size / 4} width={size} height={size / 2} fill={colors[i % colors.length]} opacity={1 - Math.max(0, t - 1.3) / 0.5} transform={`translate(${px.toFixed(1)} ${py.toFixed(1)}) rotate(${spin.toFixed(0)})`} />;
      })}
    </g>
  );
};
