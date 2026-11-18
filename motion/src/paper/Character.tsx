// A flat cut-out character (the owner's paper.js person()): Inès, Paul, Sam or Léa, feet at
// (0, 0), about 830 px tall at scale 1. Expressions (neutral, worried, happy, surprised) and
// small gestures (wave, phone in hand, shrug, cheer); everything moves on the 12 fps steps the
// caller passes in `f`.
import { CutDefs } from "./kit";
import { BRAND, type Character as Style, CHARACTERS, type CharacterId, CREAM, INK } from "./palette.ts";

export const MOODS = ["neutral", "worried", "happy", "surprised"] as const;
export type Mood = (typeof MOODS)[number];
export const GESTURES = ["none", "wave", "phone", "shrug", "cheer"] as const;
export type Gesture = (typeof GESTURES)[number];

/** `hex` mixed toward black by `k` (0..1). */
export const shade = (hex: string, k: number) => {
  const n = parseInt(hex.slice(1), 16);
  const c = [n >> 16, (n >> 8) & 255, n & 255].map((v) => Math.round(v * (1 - k)));
  return `rgb(${c.join(", ")})`;
};

const RAD = 180 / Math.PI;

/** Arm angles (radians, 0 = hanging, + = out to the left side) for a gesture at frame `f`. */
const arms = (gesture: Gesture, f: number): [number, number] => {
  const wiggle = Math.sin(f / 2.4) * 0.35;
  switch (gesture) {
    case "wave":
      return [0.18, -2.6 + wiggle];
    case "phone":
      return [0.18, -0.6];
    case "shrug":
      return [1.25, -1.25];
    case "cheer":
      return [2.6 + wiggle * 0.4, -2.6 - wiggle * 0.4];
    default:
      return [0.18 + Math.sin(f / 9) * 0.03, -0.18 - Math.sin(f / 9) * 0.03];
  }
};

const Arm = ({ x, a, color }: { x: number; a: number; color: string }) => (
  <g transform={`translate(${x} -505) rotate(${a * RAD})`} filter="url(#cut1)">
    <rect x={-20} y={-12} width={40} height={230} rx={20} fill={color} />
  </g>
);

/** Blink for 1 step every ~2.9 s (paper.js blink), offset per character so two never blink together. */
export const blinking = (f: number, fps: number, offset = 0) => ((f + offset) / fps) % 2.9 < 0.09;

export type CharacterProps = {
  id: CharacterId;
  x: number;
  y: number;
  scale: number;
  /** Stepped frame (12 fps steps) for the idle moves, the wave, the blink. */
  f: number;
  fps: number;
  mood?: Mood;
  gesture?: Gesture;
  /** Eyes look left (-1) or right (1). */
  look?: number;
  /** Eyes closed (a happy squint). */
  closed?: boolean;
  flip?: boolean;
  /** Colour of the phone screen when the gesture is "phone". */
  phone?: string;
};

/** The character as an SVG group; place it inside an <svg> that has <CutDefs />. */
export const CharacterGroup = ({ id, x, y, scale, f, fps, mood = "neutral", gesture = "none", look = 0, closed = false, flip = false, phone = BRAND }: CharacterProps) => {
  const st: Style = CHARACTERS[id];
  const S = st.skin;
  const [aL, aR] = arms(gesture, f);
  // Shrug lifts the shoulders; cheer hops on 12 fps steps.
  const lift = gesture === "shrug" ? -10 : gesture === "cheer" ? -Math.abs(Math.sin(f / 3)) * 22 : 0;
  const sleeve = st.topStyle === "dress" ? S : st.top;
  const lk = look * 14;
  const eyesShut = closed || blinking(f, fps, id.length * 7);
  const brow = mood === "worried" ? 1 : mood === "surprised" ? -1 : 0;
  const smile = mood === "happy" ? 1 : mood === "worried" ? -0.6 : 0;
  const HC = st.hair;
  return (
    <g transform={`translate(${x} ${y}) scale(${scale * (flip ? -1 : 1)} ${scale})`}>
      {[-34, 34].map((lx) => (
        <g key={lx} transform={`translate(${lx} -292)`} filter="url(#cut1)">
          <rect x={-24} y={0} width={48} height={280} rx={22} fill={st.pants} />
          <ellipse cx={14} cy={282} rx={42} ry={22} fill="#22222c" />
        </g>
      ))}
      <g transform={`translate(0 ${lift})`}>
        {st.topStyle === "hoodie" && <circle cx={0} cy={-640} r={128} fill={shade(st.top, 0.25)} filter="url(#cut1)" />}
        {st.hairStyle === "long" && <rect x={-124} y={-752} width={248} height={300} rx={110} fill={HC} filter="url(#cut1)" />}
        <Arm x={-92} a={aL} color={sleeve} />
        {st.topStyle === "dress" ? (
          <g filter="url(#cut15)">
            <path d="M-82,-535 L82,-535 Q104,-420 138,-268 L-138,-268 Q-104,-420 -82,-535Z" fill={st.top} />
          </g>
        ) : (
          <g filter="url(#cut15)">
            <path d="M-92,-545 L92,-545 Q118,-440 104,-270 L-104,-270 Q-118,-440 -92,-545Z" fill={st.top} />
          </g>
        )}
        {st.topStyle === "dress" && (
          <>
            <path d="M-40,-535 L40,-535 L0,-490Z" fill={CREAM} />
            {[[-60, -330], [10, -300], [70, -350], [-20, -400], [45, -440]].map(([dx, dy]) => (
              <circle key={`${dx}${dy}`} cx={dx} cy={dy} r={9} fill="rgba(255,248,236,.85)" />
            ))}
          </>
        )}
        {st.topStyle === "shirt" && (
          <>
            <path d="M-44,-545 L44,-545 L0,-495Z" fill={S} />
            {"stripes" in st && st.stripes
              ? [0, 1, 2, 3, 4].map((k) => <rect key={k} x={-100} y={-520 + k * 50} width={200} height={16} fill="rgba(255,255,255,.35)" />)
              : [0, 1, 2, 3].map((k) => <circle key={k} cx={0} cy={-470 + k * 50} r={6} fill="rgba(255,255,255,.7)" />)}
          </>
        )}
        {st.topStyle === "hoodie" && (
          <>
            <rect x={-60} y={-380} width={120} height={70} rx={20} fill={shade(st.top, 0.18)} />
            <path d="M-24,-540 L-28,-470 M24,-540 L28,-470" stroke={CREAM} strokeWidth={6} />
          </>
        )}
        <Arm x={92} a={aR} color={sleeve} />
        {gesture === "phone" && (
          <g transform="translate(70 -330) rotate(-8.6)" filter="url(#cut1)">
            <rect x={-30} y={-55} width={60} height={110} rx={12} fill="#1E232B" />
            <rect x={-24} y={-48} width={48} height={96} rx={8} fill={phone} />
          </g>
        )}
        <rect x={-20} y={-580} width={40} height={60} rx={10} fill={shade(S, 0.12)} />
        {st.hairStyle === "bun" && (
          <g filter="url(#cut1)" fill={HC}>
            <circle cx={0} cy={-655} r={112} />
            <circle cx={0} cy={-782} r={54} />
          </g>
        )}
        {st.hairStyle === "curly" && (
          <g filter="url(#cut1)" fill={HC}>
            {Array.from({ length: 12 }, (_, k) => {
              const a = Math.PI * 0.9 + (k / 11) * Math.PI * 1.2;
              return <circle key={k} cx={Math.cos(a) * 98} cy={-660 + Math.sin(a) * 98} r={48} />;
            })}
          </g>
        )}
        <circle cx={0} cy={-640} r={96} fill={S} filter="url(#cut1)" />
        {(st.hairStyle === "bun" || st.hairStyle === "long") && (
          <path d="M-104,-640 Q-98,-760 10,-752 Q100,-748 104,-650 Q60,-712 -6,-700 Q-70,-690 -104,-640Z" fill={HC} filter="url(#cut05)" />
        )}
        {st.hairStyle === "short" && (
          <path d="M-100,-630 Q-110,-750 0,-752 Q110,-750 100,-630 L88,-660 Q30,-690 -40,-690 Q-80,-685 -88,-650Z" fill={HC} filter="url(#cut05)" />
        )}
        {st.hairStyle === "curly" && (
          <g fill={HC} filter="url(#cut05)">
            {Array.from({ length: 7 }, (_, k) => (
              <circle key={k} cx={-75 + k * 25} cy={-715 - Math.sin((k / 6) * Math.PI) * 28} r={38} />
            ))}
          </g>
        )}
        {"beard" in st && st.beard && (
          <path d="M-94,-640 Q-92,-530 0,-526 Q92,-530 94,-640 L76,-640 Q66,-572 0,-566 Q-66,-572 -76,-640Z" fill={HC} />
        )}
        {[-34, 34].map((ex) =>
          eyesShut ? (
            <rect key={ex} x={ex + lk - 11} y={-634} width={22} height={5} fill={INK} />
          ) : (
            <ellipse key={ex} cx={ex + lk} cy={-632} rx={9} ry={mood === "surprised" ? 15 : 13} fill={INK} />
          ),
        )}
        {[-56, 56].map((ex) => (
          <ellipse key={ex} cx={ex} cy={-596} rx={16} ry={10} fill="rgba(255,111,97,.45)" />
        ))}
        {mood === "surprised" ? (
          <ellipse cx={0} cy={-584} rx={13} ry={17} fill="#8a2d2a" stroke={INK} strokeWidth={6} />
        ) : smile > 0.7 ? (
          <path d="M-26,-590 Q0,-555 26,-590Z" fill="#8a2d2a" stroke={INK} strokeWidth={6} strokeLinejoin="round" />
        ) : (
          <path d={`M-20,-584 Q${lk},${-584 + smile * 22} 20,-584`} fill="none" stroke={INK} strokeWidth={6} strokeLinecap="round" />
        )}
        {brow !== 0 && <path d={`M-48,-662 L-20,${-668 + brow * 8} M48,-662 L20,${-668 + brow * 8}`} stroke={INK} strokeWidth={5} strokeLinecap="round" />}
        {mood === "worried" && <path d="M110,-700 Q128,-660 110,-650 Q92,-660 110,-700Z" fill="#7cc4f0" filter="url(#cut05)" />}
      </g>
    </g>
  );
};

/** One character in its own SVG box (end card cameo): `width` × `height`, feet at the bottom centre. */
export const CharacterSvg = ({ width, height, ...p }: Omit<CharacterProps, "x" | "y"> & { width: number; height: number }) => (
  <svg width={width} height={height} style={{ overflow: "visible" }}>
    <CutDefs />
    <CharacterGroup {...p} x={width / 2} y={height - 10} />
  </svg>
);
