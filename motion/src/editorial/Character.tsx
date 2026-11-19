// The anatomy kit (step 144): body parts as soft, glossy cartoon characters with simple faces
// (stomach, muscle, heart, bone, fat cell; five moods), drawn in SVG and pixelated by the
// `px` filter (kit.tsx PixelDefs) so they match the pixel captions (`pixel` off for a small cameo). About
// 400 px across, centred on (0, 0).
import { CHARACTERS, type CharacterId, type Mood } from "./palette.ts";

const INK = "#1A1030";

/** Each body part's silhouette and where its face sits. */
/** Each part's silhouette, where its face sits and its highlight's centre (`light`, default -70, -80). */
const BODY: Record<CharacterId, { d: string; face: [number, number]; extra?: string; rot?: number; size?: number; light?: [number, number] }> = {
  stomach: {
    // A J-shaped bean: the oesophagus in at the top left, the pylorus out at the bottom right.
    d: "M-110 -130C-60 -120 -10 -60 70 -80C170 -105 215 0 170 90C130 170 20 205 -80 180C-190 150 -215 40 -175 -40C-155 -85 -140 -110 -110 -130Z",
    face: [-5, 40],
    extra: "M-128 -118C-140 -170 -138 -220 -120 -268L-78 -258C-92 -220 -92 -180 -82 -134ZM150 120C175 150 200 168 236 170L232 212C185 212 150 190 120 152Z",
  },
  muscle: { d: "M-200 0C-130 -150 130 -150 200 0C130 150 -130 150 -200 0Z", face: [0, 0], extra: "M-250 -22h70v44h-70zM180 -22h70v44h-70z", rot: -14, size: 1.25, light: [-90, -50] },
  heart: {
    d: "M0 170C-70 110 -200 30 -200 -70C-200 -160 -100 -200 -40 -150C-15 -130 0 -105 0 -105C0 -105 15 -130 40 -150C100 -200 200 -160 200 -70C200 30 70 110 0 170Z",
    face: [0, -10],
    extra: "M-50 -150v-90h44v80zM20 -150c0 -60 20 -90 70 -100l10 40c-30 6 -40 26 -40 60z",
  },
  bone: {
    d: `M-160 -50h320v100h-320z${[[-178, -44], [-178, 44], [178, -44], [178, 44]].map(([x, y]) => `M${x - 54} ${y}a54 54 0 1 0 108 0a54 54 0 1 0 -108 0z`).join("")}`,
    face: [0, 0],
    rot: -12,
    light: [-185, -62],
  },
  fat: { d: "", face: [0, 0] },
};

/** The fat cell's wobbly membrane at `frame`. */
const blob = (frame: number) => {
  const pts = Array.from({ length: 48 }, (_, i) => {
    const a = (i / 48) * 2 * Math.PI;
    const r = 175 + 9 * Math.sin(6 * a + frame / 9) + 5 * Math.sin(3 * a - frame / 13);
    return `${(Math.cos(a) * r).toFixed(1)} ${(Math.sin(a) * r * 0.92).toFixed(1)}`;
  });
  return `M${pts.join("L")}Z`;
};

/** Eyes and mouth for a mood; `blink` closes the eyes; `look` moves the pupils (-1..1). */
const Face = ({ mood, blink, look }: { mood: Mood; blink: boolean; look: number }) => {
  const big = mood === "surprised" ? 1.2 : 1;
  const eye = (x: number) => {
    if (mood === "sore") return <path key={x} d={`M${x - 18} -24l30 14l-30 14`} transform={x > 0 ? `translate(${2 * x} 0) scale(-1 1)` : undefined} fill="none" stroke={INK} strokeWidth={9} strokeLinecap="round" strokeLinejoin="round" />;
    if (blink || mood === "happy") {
      return mood === "happy" && !blink ? (
        <path key={x} d={`M${x - 22} -4q22 -30 44 0`} fill="none" stroke={INK} strokeWidth={9} strokeLinecap="round" />
      ) : (
        <path key={x} d={`M${x - 22} -8h44`} stroke={INK} strokeWidth={9} strokeLinecap="round" />
      );
    }
    return (
      <g key={x} transform={`translate(${x} -10) scale(${big})`}>
        <ellipse rx={27} ry={31} fill="#FFFFFF" stroke={INK} strokeWidth={6} />
        <circle cx={look * 8} cy={4} r={mood === "surprised" ? 9 : 14} fill={INK} />
        <circle cx={look * 8 + 5} cy={-3} r={6} fill="#FFFFFF" />
        <circle cx={look * 8 - 5} cy={10} r={3} fill="#FFFFFF" />
        {mood === "tired" && <path d="M-29 -2V-34H29V-2Z" fill="currentColor" stroke={INK} strokeWidth={6} />}
      </g>
    );
  };
  const mouth = {
    neutral: <path d="M-18 44q18 8 36 0" fill="none" stroke={INK} strokeWidth={7} strokeLinecap="round" />,
    happy: (
      <g>
        <path d="M-38 32q38 50 76 0z" fill={INK} />
        <path d="M-16 56q16 -14 32 0q-16 12 -32 0z" fill="#FF6F8E" />
      </g>
    ),
    surprised: <ellipse cy={52} rx={16} ry={22} fill={INK} />,
    tired: <path d="M-22 50q11 -8 22 0t22 0" fill="none" stroke={INK} strokeWidth={7} strokeLinecap="round" />,
    sore: <path d="M-36 52q9 -12 18 0t18 0t18 0t18 0" fill="none" stroke={INK} strokeWidth={7} strokeLinecap="round" />,
  }[mood];
  // Brows carry most of the feeling: raised (surprised), worried (sore), heavy (tired).
  const brows = {
    neutral: "M-74 -58q20 -8 40 0M34 -58q20 -8 40 0",
    happy: "M-74 -54q20 -14 40 0M34 -54q20 -14 40 0",
    surprised: "M-74 -76q20 -18 40 0M34 -76q20 -18 40 0",
    tired: "M-74 -46l40 6M34 -40l40 -6",
    sore: "M-74 -44l40 -16M34 -60l40 16",
  }[mood];
  return (
    <g>
      <path d={brows} fill="none" stroke={INK} strokeWidth={8} strokeLinecap="round" />
      {eye(-52)}
      {eye(52)}
      {mouth}
      {mood !== "tired" && (
        <g fill="#FF5C8A" opacity={mood === "happy" || mood === "surprised" ? 0.6 : 0.3}>
          <ellipse cx={-88} cy={34} rx={22} ry={13} />
          <ellipse cx={88} cy={34} rx={22} ry={13} />
        </g>
      )}
      {(mood === "sore" || mood === "tired") && <path d="M96 -70q14 26 0 34q-14 -8 0 -34z" fill="#9BD8FF" stroke={INK} strokeWidth={4} />}
    </g>
  );
};

/**
 * A body part at frame `f` (from its scene's start) in `mood`; `changed` = frames since its
 * mood last changed: it squashes (anticipation), stretches, then settles. Breathes, blinks
 * every ~3 s, hops with a landing squash when happy, shakes when sore, sags when tired.
 * Shading: the glossy gradient, a dithered shadow on the lower right, a cool rim light from
 * the blue ground on that edge, a soft highlight and specular pixels on the upper left.
 */
export const Character = ({ id, mood, f, changed = 99, x, y, s, pixel = true }: { id: CharacterId; mood: Mood; f: number; changed?: number; x: number; y: number; s: number; pixel?: boolean }) => {
  const c = CHARACTERS[id];
  const body = BODY[id];
  const breathe = Math.sin(f / 14) * 0.03;
  // Mood change: squash 4 frames, stretch 4, settle 6.
  const react = changed < 4 ? -0.14 * (changed / 4) : changed < 8 ? -0.14 + 0.3 * ((changed - 4) / 4) : changed < 14 ? 0.16 * (1 - (changed - 8) / 6) : 0;
  const hop = mood === "happy" ? Math.abs(Math.sin(f / 7)) : 0;
  const land = mood === "happy" && hop < 0.25 ? 0.1 * (1 - hop / 0.25) : 0;
  const bounce = -hop * 26 + (mood === "tired" ? 14 : 0);
  const shake = mood === "sore" ? Math.sin(f * 2.1) * 7 : 0;
  const blink = mood !== "sore" && f % 92 > 87;
  const look = mood === "tired" ? 0 : Math.sin(f / 37) > 0.6 ? 1 : Math.sin(f / 37) < -0.7 ? -1 : 0;
  const k = s * (body.size ?? 1);
  const sy = 1 + breathe + react - land;
  const sx = 1 - breathe - react * 0.7 + land;
  const gid = `ed-${id}`;
  const [lx, ly] = body.light ?? [-70, -80];
  const d = id === "fat" ? blob(f) : body.d;
  return (
    <g transform={`translate(${x + shake} ${y + bounce}) scale(${k * sx} ${k * sy}) rotate(${(body.rot ?? 0) + (mood === "tired" ? 5 : 0)})`} filter={pixel ? "url(#px)" : undefined}>
      <defs>
        <radialGradient id={gid} cx="35%" cy="28%" r="80%">
          <stop offset="0" stopColor={c.light} />
          <stop offset="0.45" stopColor={c.base} />
          <stop offset="1" stopColor={c.shade} />
        </radialGradient>
        <clipPath id={`${gid}-clip`}>
          <path d={d} />
        </clipPath>
        {/* 8 px cells = the pixel filter's blocks, so the checker survives it. */}
        <pattern id={`${gid}-dither`} width={16} height={16} patternUnits="userSpaceOnUse">
          <rect width={8} height={8} fill={c.shade} />
          <rect x={8} y={8} width={8} height={8} fill={c.shade} />
        </pattern>
        <linearGradient id={`${gid}-fall`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0.45" stopColor="#FFFFFF" stopOpacity={0} />
          <stop offset="0.75" stopColor="#FFFFFF" stopOpacity={1} />
        </linearGradient>
        <mask id={`${gid}-shadow`}>
          <rect x={-300} y={-300} width={600} height={600} fill={`url(#${gid}-fall)`} />
        </mask>
        <mask id={`${gid}-rim`}>
          <path d={d} fill="#FFFFFF" />
          <path d={d} fill="#000000" transform="translate(-16 -14)" />
        </mask>
      </defs>
      {body.extra && <path d={body.extra} fill={id === "muscle" ? "#F6E7CF" : c.shade} stroke={INK} strokeWidth={8} strokeLinejoin="round" />}
      {/* Outline first, fill over it: overlapping parts (the bone's knobs) keep one silhouette. */}
      <path d={d} fill={INK} stroke={INK} strokeWidth={16} strokeLinejoin="round" />
      <path d={d} fill={`url(#${gid})`} />
      <g clipPath={`url(#${gid}-clip)`}>
        <rect x={-300} y={-300} width={600} height={600} fill={`url(#${gid}-dither)`} mask={`url(#${gid}-shadow)`} />
        <rect x={-300} y={-300} width={600} height={600} fill="#8FD8FF" opacity={0.7} mask={`url(#${gid}-rim)`} />
        <ellipse cx={lx} cy={ly} rx={46} ry={22} fill="#FFFFFF" opacity={0.45} transform={`rotate(-25 ${lx} ${ly})`} />
        <g fill="#FFFFFF">
          <rect x={lx - 26} y={ly - 20} width={16} height={16} />
          <rect x={lx - 2} y={ly - 28} width={8} height={8} />
        </g>
      </g>
      {id === "muscle" && <path d="M-120 -40q120 -50 240 0M-140 10q140 -40 280 0M-120 55q120 -30 240 0" fill="none" stroke={c.shade} strokeWidth={6} opacity={0.6} />}
      {id === "fat" && <circle cx={70} cy={60} r={40} fill={c.light} stroke={c.shade} strokeWidth={6} />}
      <g transform={`translate(${body.face[0]} ${body.face[1]}) rotate(${-(body.rot ?? 0)})`} color={c.base}>
        <Face mood={mood} blink={blink} look={look} />
      </g>
    </g>
  );
};
