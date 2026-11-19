// Marco, the macroBody coach (step 154): the Macro 3D style's presenter, our own character drawn
// in code. A friendly coach in his forties, white sweatband with an emerald stripe over a short
// quiff, trimmed beard, emerald tee with the mB tile, a whistle on a cord. Bust in the corner,
// he reacts to every line with a pose (cut on the beat), talks while the voice speaks, blinks
// and breathes.
import { MbTile } from "../endcards/base";
import type { Pose } from "./poses.ts";
import type { Mouth } from "./words.ts";

const SKIN = "#E9B48E";
const SKIN_DARK = "#C98E6B";
const SKIN_LINE = "#8A5A40";
const HAIR = "#3A2A20";
const SHIRT = "#10B981";
const SHIRT_DARK = "#0A8A60";
const SHIRT_LINE = "#06593F";
const BAND = "#F4F6F5";

type Pt = [number, number];
type Hand = "open" | "point" | "fist" | "thumb" | "palmup";
type Arm = { e: Pt; w: Pt; hand: Hand; twist?: number; flip?: boolean };
type Rig = { l: Arm; r: Arm; brows: number; look: Pt; lift?: number };

/** Shoulders (viewBox units). */
const SHOULDER_Y = 310;

const DOWN_L: Arm = { e: [66, 470], w: [70, 620], hand: "fist" };
const DOWN_R: Arm = { e: [334, 470], w: [330, 620], hand: "fist", flip: true };

/** Each pose: elbows and wrists (viewBox 400 x 520, shoulders at 88 / 312, 318), hands, brows, gaze. */
const RIGS: Record<Pose, Rig> = {
  explain: { l: { e: [62, 452], w: [146, 396], hand: "open", twist: -25 }, r: DOWN_R, brows: 0, look: [0, 0] },
  point: { l: { e: [24, 330], w: [52, 214], hand: "point", twist: 8 }, r: DOWN_R, brows: -3, look: [-3, -3] },
  stop: { l: { e: [40, 400], w: [96, 300], hand: "open", twist: 12 }, r: DOWN_R, brows: 4, look: [0, 0] },
  think: { l: DOWN_L, r: { e: [318, 470], w: [236, 288], hand: "fist", twist: -10, flip: true }, brows: 5, look: [4, -5] },
  temple: { l: { e: [36, 352], w: [92, 182], hand: "point", twist: 52 }, r: DOWN_R, brows: 3, look: [-2, -4] },
  shrug: { l: { e: [30, 430], w: [-6, 372], hand: "palmup" }, r: { e: [370, 430], w: [406, 372], hand: "palmup", flip: true }, brows: -7, look: [0, 0], lift: 10 },
  thumbs: { l: { e: [58, 456], w: [138, 388], hand: "thumb", twist: -32 }, r: DOWN_R, brows: -2, look: [0, 0] },
  wow: { l: { e: [30, 342], w: [62, 214], hand: "open", twist: -6 }, r: { e: [370, 342], w: [338, 214], hand: "open", twist: 6, flip: true }, brows: -8, look: [0, -1] },
};

const capsule = (a: Pt, b: Pt, width: number, color: string, line: string) => (
  <>
    <line x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} stroke={line} strokeWidth={width + 5} strokeLinecap="round" />
    <line x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} stroke={color} strokeWidth={width} strokeLinecap="round" />
  </>
);

/** A hand at the wrist, fingers along +local up (-y), drawn mitten-simple with knuckle lines. */
const HandShape = ({ hand, flip }: { hand: Hand; flip?: boolean }) => {
  const s = flip ? -1 : 1;
  const finger = (x: number, len: number, lean = 0) => capsule([x * s, -38], [(x + lean) * s, -38 - len], 12, SKIN, SKIN_LINE);
  const palm = <rect x={-22} y={-46} width={44} height={50} rx={18} fill={SKIN} stroke={SKIN_LINE} strokeWidth={2.5} />;
  if (hand === "open" || hand === "palmup") {
    return (
      <g transform={hand === "palmup" ? `rotate(${-80 * s})` : undefined}>
        {finger(-15, 30, -6)}
        {finger(-5, 38, -2)}
        {finger(6, 37, 2)}
        {finger(16, 29, 6)}
        {palm}
        {capsule([-18 * s, -12], [-36 * s, -36], 13, SKIN, SKIN_LINE)}
        <path d={`M${-12 * s} -16 Q 0 -8 ${12 * s} -18`} stroke={SKIN_DARK} strokeWidth={2} fill="none" />
      </g>
    );
  }
  return (
    <g>
      {hand === "point" && finger(-12, 46, 0)}
      {hand === "thumb" && capsule([-20 * s, -30], [-24 * s, -72], 15, SKIN, SKIN_LINE)}
      <rect x={-23} y={-48} width={46} height={52} rx={17} fill={SKIN} stroke={SKIN_LINE} strokeWidth={2.5} />
      {[-34, -24, -14].map((y) => (
        <path key={y} d={`M${-16} ${y} Q 0 ${y + 4} 16 ${y}`} stroke={SKIN_DARK} strokeWidth={2} fill="none" />
      ))}
      {hand !== "thumb" && <path d={`M${-20 * s} -6 Q ${-4 * s} -20 ${10 * s} -12`} stroke={SKIN_LINE} strokeWidth={2.5} fill="none" />}
    </g>
  );
};

const ArmShape = ({ shoulder, arm }: { shoulder: Pt; arm: Arm }) => {
  const sleeveEnd: Pt = [shoulder[0] + (arm.e[0] - shoulder[0]) * 0.55, shoulder[1] + (arm.e[1] - shoulder[1]) * 0.55];
  const deg = (Math.atan2(arm.w[1] - arm.e[1], arm.w[0] - arm.e[0]) * 180) / Math.PI + 90 + (arm.twist ?? 0);
  return (
    <g>
      {capsule(shoulder, arm.e, 48, SKIN, SKIN_LINE)}
      {capsule(arm.e, arm.w, 42, SKIN, SKIN_LINE)}
      {capsule(shoulder, sleeveEnd, 64, SHIRT, SHIRT_LINE)}
      <g transform={`translate(${arm.w[0]} ${arm.w[1]}) rotate(${deg})`}>
        <HandShape hand={arm.hand} flip={arm.flip} />
      </g>
    </g>
  );
};

const MouthShape = ({ mouth, smile }: { mouth: Mouth; smile: boolean }) => {
  if (mouth === "closed") {
    return <path d={smile ? "M176 210 Q 200 228 224 210" : "M180 214 Q 200 220 220 214"} stroke="#5A2A22" strokeWidth={4} fill="none" strokeLinecap="round" />;
  }
  const [w, h] = { small: [15, 7], open: [19, 16], round: [11, 13], wide: [22, 9] }[mouth];
  return (
    <g>
      <ellipse cx={200} cy={214} rx={w} ry={h} fill="#5A1E1E" stroke="#3E1512" strokeWidth={2.5} />
      <clipPath id="marco-mouth">
        <ellipse cx={200} cy={214} rx={w} ry={h} />
      </clipPath>
      <g clipPath="url(#marco-mouth)">
        <rect x={180} y={214 - h - 2} width={40} height={Math.min(8, h * 0.6)} fill="#F7F3EE" />
        <ellipse cx={200} cy={214 + h} rx={w * 0.7} ry={h * 0.55} fill="#D85A5A" />
      </g>
    </g>
  );
};

/** Marco at `pose`, mouth `mouth`, eyes shut when `blink`. */
export const Marco = ({ pose, mouth, blink }: { pose: Pose; mouth: Mouth; blink: boolean }) => {
  const rig = RIGS[pose];
  const lift = rig.lift ?? 0;
  const [lx, ly] = rig.look;
  const smile = pose === "thumbs" || pose === "explain" || pose === "point";
  const sl: Pt = [88, SHOULDER_Y - lift];
  const sr: Pt = [312, SHOULDER_Y - lift];
  return (
    <svg viewBox="0 0 400 520" width="100%" height="100%" style={{ overflow: "visible" }}>
      <defs>
        <linearGradient id="marco-shirt" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor={SHIRT_DARK} />
          <stop offset="0.35" stopColor={SHIRT} />
          <stop offset="0.7" stopColor="#22C993" />
          <stop offset="1" stopColor={SHIRT_DARK} />
        </linearGradient>
        <radialGradient id="marco-face" cx="0.45" cy="0.4" r="0.7">
          <stop offset="0" stopColor="#F3C6A2" />
          <stop offset="1" stopColor={SKIN} />
        </radialGradient>
      </defs>
      {/* tee and neck */}
      <path d={`M40 520 L46 ${350 - lift} Q 56 ${290 - lift} 120 ${278 - lift} L280 ${278 - lift} Q 344 ${290 - lift} 354 ${350 - lift} L360 520 Z`} fill="url(#marco-shirt)" stroke={SHIRT_LINE} strokeWidth={3} />
      <rect x={168} y={226} width={64} height={58} rx={22} fill={SKIN_DARK} />
      <path d="M160 278 Q 200 312 240 278" fill={SKIN} stroke={SKIN_LINE} strokeWidth={2.5} />
      <path d="M156 276 Q 200 320 244 276" fill="none" stroke={SHIRT_LINE} strokeWidth={8} strokeLinecap="round" />
      <g transform="translate(250 330)">
        <MbTile size={44} fill="#0B0B0B" />
      </g>
      {/* whistle on its cord */}
      <path d="M166 290 Q 172 356 184 404 M234 290 Q 214 356 190 404" stroke="#2F3A44" strokeWidth={3} fill="none" />
      <g transform="translate(176 402) rotate(-12)">
        <rect x={0} y={0} width={30} height={16} rx={8} fill="#C9D1D8" stroke="#6B7680" strokeWidth={2} />
        <rect x={26} y={3} width={14} height={8} rx={2} fill="#AEB8C1" stroke="#6B7680" strokeWidth={2} />
        <circle cx={9} cy={8} r={3} fill="#6B7680" />
      </g>
      {/* head */}
      <g>
        <path d="M120 150 Q 112 86 136 62 Q 150 30 186 34 Q 200 14 222 30 Q 262 26 272 62 Q 290 90 280 150 Z" fill={HAIR} />
        <ellipse cx={126} cy={162} rx={13} ry={20} fill={SKIN} stroke={SKIN_LINE} strokeWidth={2.5} />
        <ellipse cx={274} cy={162} rx={13} ry={20} fill={SKIN} stroke={SKIN_LINE} strokeWidth={2.5} />
        <path d="M130 120 Q 128 230 200 252 Q 272 230 270 120 Q 200 96 130 120 Z" fill="url(#marco-face)" stroke={SKIN_LINE} strokeWidth={3} />
        {/* beard and moustache */}
        <path d="M132 168 Q 138 236 200 254 Q 262 236 268 168 Q 260 206 236 214 Q 220 196 200 198 Q 180 196 164 214 Q 140 206 132 168 Z" fill={HAIR} opacity={0.92} />
        <path d="M172 204 Q 200 190 228 204 Q 214 200 200 202 Q 186 200 172 204 Z" fill={HAIR} />
        <MouthShape mouth={mouth} smile={smile} />
        {/* eyes */}
        {[172, 228].map((x) => (
          <g key={x}>
            {blink ? (
              <path d={`M${x - 13} 152 Q ${x} 158 ${x + 13} 152`} stroke="#3E2A20" strokeWidth={3.5} fill="none" strokeLinecap="round" />
            ) : (
              <>
                <ellipse cx={x} cy={151} rx={11} ry={11.5} fill="#FFFFFF" />
                <circle cx={x + lx} cy={152 + ly} r={7} fill="#5B3A1E" />
                <circle cx={x + lx} cy={152 + ly} r={3.4} fill="#1B1210" />
                <circle cx={x + lx + 2.5} cy={149 + ly} r={1.8} fill="#FFFFFF" />
                <path d={`M${x - 13} 148 Q ${x} 136 ${x + 13} 148`} stroke="#3E2A20" strokeWidth={4} fill="none" strokeLinecap="round" />
              </>
            )}
            <path
              d={`M${x - 16} ${130 + rig.brows * (x < 200 ? 1 : 0.6)} Q ${x} ${122 + rig.brows} ${x + 16} ${130 + rig.brows * (x < 200 ? 0.6 : 1)}`}
              stroke={HAIR}
              strokeWidth={7}
              fill="none"
              strokeLinecap="round"
            />
          </g>
        ))}
        <path d="M200 156 Q 194 178 190 184 Q 200 190 210 184" stroke={SKIN_LINE} strokeWidth={3} fill="none" strokeLinecap="round" />
        <ellipse cx={156} cy={186} rx={12} ry={7} fill="#E88B7A" opacity={0.35} />
        <ellipse cx={244} cy={186} rx={12} ry={7} fill="#E88B7A" opacity={0.35} />
        {/* the sweatband over the quiff: the silhouette */}
        <path d="M148 98 Q 150 52 186 46 Q 176 30 204 24 Q 196 40 222 40 Q 262 44 256 96 Q 236 70 206 72 Q 176 70 148 98 Z" fill="#4A3628" />
        <path d="M176 60 Q 196 44 228 52 M168 76 Q 200 58 240 70" stroke="#2A1D16" strokeWidth={3} fill="none" strokeLinecap="round" />
        <path d="M124 112 Q 200 78 276 112 L276 132 Q 200 100 124 132 Z" fill={BAND} stroke="#B9C2BE" strokeWidth={2.5} />
        <path d="M125 120 Q 200 87 275 120 L275 125 Q 200 93 125 125 Z" fill={SHIRT} />
      </g>
      {/* arms last: hands on the chin, at the temple and beside the head are in front of it */}
      <ArmShape shoulder={sl} arm={rig.l} />
      <ArmShape shoulder={sr} arm={rig.r} />
    </svg>
  );
};
