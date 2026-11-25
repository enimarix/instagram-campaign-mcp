// The « GTA 6 » style's kit (owner 2026-11-25): the sunset palette and type, the drawn sets
// (beach, night city, Muscle Beach, the neon grid), the game HUD (wanted stars, kcal counter,
// protein bar, minimap, objective line), pickups and the cut wipe. All art drawn in code: no
// game's logo, font, names or artwork. People: ./person.tsx.
import type { CSSProperties, ReactNode } from "react";
import { Easing, interpolate, random } from "remotion";
import { fonts } from "../lib/font";

export const W = 1080;
export const H = 1920;
export const C = {
  ink: "#0B0614", night: "#160830", violet: "#3B1366", plum: "#7A1F7A", pink: "#FF3D7F", coral: "#FF6B4A",
  orange: "#FF9A3C", gold: "#FFD25E", teal: "#21D4C4", cyan: "#5CF2FF", money: "#86E85F", yellow: "#FFE14D",
};
export const SUNSET = `linear-gradient(100deg, ${C.pink} 0%, ${C.coral} 45%, ${C.gold} 100%)`;

export const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;
export const ease = (t: number, a: number, b: number, from = 0, to = 1) =>
  interpolate(t, [a, b], [from, to], { ...clamp, easing: Easing.out(Easing.cubic) });

/** Heavy outline + drop, as a filter so gradient-filled text keeps its fill. */
export const OUTLINE = "drop-shadow(3px 0 0 #0B0614) drop-shadow(-3px 0 0 #0B0614) drop-shadow(0 3px 0 #0B0614) drop-shadow(0 -3px 0 #0B0614) drop-shadow(0 10px 0 rgba(11,6,20,.85))";
// The padding lets the clipped background reach capital accents (É, È) above the line box.
export const gradText = (bg: string): CSSProperties => ({ background: bg, WebkitBackgroundClip: "text", backgroundClip: "text", color: "transparent", paddingTop: "0.2em", marginTop: "-0.2em" });
/** Units stay lowercase inside uppercase lines (g, kcal). */
export const unit = (s: string) => <span style={{ textTransform: "none" }}>{s}</span>;
/** 1 800 (a plain space: the display font draws no-break spaces with no width); its line is nowrap. */
export const num = (n: number) => String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, " ");
export const display: CSSProperties = { fontFamily: fonts.display, fontWeight: 900, letterSpacing: "-0.02em", lineHeight: 1, textTransform: "uppercase" };

// ---------- drawn scenes (any size: w × h) ----------

export type SceneProps = { w: number; h: number; t: number; id: string };

export const Halftone = ({ id, w, h, opacity = 0.28 }: { id: string; w: number; h: number; opacity?: number }) => (
  <>
    <defs>
      <pattern id={`${id}-dots`} width="9" height="9" patternUnits="userSpaceOnUse" patternTransform="rotate(30)">
        <circle cx="4.5" cy="4.5" r="1.8" fill="#0B0614" />
      </pattern>
    </defs>
    <rect width={w} height={h} fill={`url(#${id}-dots)`} opacity={opacity} />
  </>
);

/** Sunset sky, striped sun, sea with the sun's reflection. */
export const Sunset = ({ w, h, t, id, horizon, sky = ["#1A0B33", "#5B1670", "#E2366F", "#FF7A45", "#FFC15A"], sea = true }: SceneProps & { horizon: number; sky?: string[]; sea?: boolean }) => {
  const r = w * 0.24;
  const cy = horizon - r * 0.35;
  return (
    <>
      <defs>
        <linearGradient id={`${id}-sky`} x1="0" y1="0" x2="0" y2="1">
          {sky.map((c, i) => <stop key={i} offset={i / (sky.length - 1)} stopColor={c} />)}
        </linearGradient>
        <linearGradient id={`${id}-sun`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#FFF3A8" /><stop offset="0.55" stopColor={C.orange} /><stop offset="1" stopColor={C.pink} />
        </linearGradient>
        <linearGradient id={`${id}-sea`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#4A1868" /><stop offset="1" stopColor="#12062A" />
        </linearGradient>
        <mask id={`${id}-stripes`}>
          <rect width={w} height={h} fill="white" />
          {Array.from({ length: 6 }, (_, i) => {
            const y = cy + r * 0.05 + i * r * 0.17 - ((t * 0.4) % (r * 0.17));
            return <rect key={i} x="0" y={y} width={w} height={2 + i * 3.2} fill="black" />;
          })}
        </mask>
      </defs>
      <rect width={w} height={horizon} fill={`url(#${id}-sky)`} />
      <circle cx={w / 2} cy={cy} r={r * 1.5} fill={C.gold} opacity="0.18" />
      <circle cx={w / 2} cy={cy} r={r} fill={`url(#${id}-sun)`} mask={`url(#${id}-stripes)`} />
      {sea && (
        <>
          <rect y={horizon} width={w} height={h - horizon} fill={`url(#${id}-sea)`} />
          {Array.from({ length: 9 }, (_, i) => {
            const rw = r * 1.6 * (1 - i / 11);
            const x = w / 2 - rw / 2 + Math.sin(t / 9 + i) * 10;
            return <rect key={i} x={x} y={horizon + 6 + i * (h - horizon) * 0.06} width={rw} height={4 + i * 0.6} rx="3" fill={i % 2 ? C.pink : C.gold} opacity={0.7 - i * 0.06} />;
          })}
        </>
      )}
    </>
  );
};

/** A palm silhouette from its foot (x, y). */
export const Palm = ({ x, y, h, lean, t, s }: { x: number; y: number; h: number; lean: number; t: number; s: number }) => {
  const tx = x + lean;
  const ty = y - h;
  const sway = Math.sin(t / 28 + x * 0.01) * 4;
  const leaf = "M0 0 C 50 -48 135 -44 205 22 C 160 -2 125 -10 100 -6 C 70 -3 30 -7 0 0 Z";
  const side = [-62, -34, -8, 22];
  return (
    <g fill={C.ink}>
      <path d={`M${x - 13 * s} ${y} Q ${x + lean * 0.15} ${y - h * 0.55} ${tx - 5 * s} ${ty} L ${tx + 5 * s} ${ty} Q ${x + lean * 0.15 + 22 * s} ${y - h * 0.55} ${x + 13 * s} ${y} Z`} />
      <g transform={`translate(${tx} ${ty}) rotate(${sway}) scale(${s})`}>
        {side.map((a) => <path key={`r${a}`} d={leaf} transform={`rotate(${a})`} />)}
        {side.map((a) => <path key={`l${a}`} d={leaf} transform={`scale(-1 1) rotate(${a + 6})`} />)}
        <path d={leaf} transform="rotate(-88) scale(0.8)" />
        <circle r="12" />
      </g>
    </g>
  );
};

export const Skyline = ({ w, base, seed, fill, maxH, lit, t }: { w: number; base: number; seed: string; fill: string; maxH: number; lit: number; t: number }) => {
  const out: ReactNode[] = [];
  let x = -20;
  let i = 0;
  while (x < w + 20) {
    const bw = 50 + random(`${seed}w${i}`) * 110;
    const bh = maxH * (0.35 + random(`${seed}h${i}`) * 0.65);
    out.push(<rect key={`b${i}`} x={x} y={base - bh} width={bw} height={bh} fill={fill} />);
    if (lit > 0) {
      for (let wy = base - bh + 14; wy < base - 10; wy += 22) {
        for (let wx = x + 10; wx < x + bw - 12; wx += 18) {
          const r = random(`${seed}${i}-${wx}-${wy}`);
          if (r < lit) {
            const on = random(`${seed}${i}-${wx}-${wy}-${Math.floor(t / 20)}`) > 0.04;
            out.push(<rect key={`w${i}-${wx}-${wy}`} x={wx} y={wy} width="8" height="11" fill={r < lit * 0.4 ? C.cyan : r < lit * 0.7 ? C.gold : C.pink} opacity={on ? 0.85 : 0.15} />);
          }
        }
      }
    }
    x += bw + 4;
    i += 1;
  }
  return <g>{out}</g>;
};

export const Glow = ({ id, sd = 7 }: { id: string; sd?: number }) => (
  <filter id={id} x="-50%" y="-50%" width="200%" height="200%">
    <feGaussianBlur stdDeviation={sd} result="b" />
    <feMerge><feMergeNode in="b" /><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
  </filter>
);

export const NeonText = ({ x, y, size, color, children, t, id, flicker = 0 }: { x: number; y: number; size: number; color: string; children: string; t: number; id: string; flicker?: number }) => {
  const off = flicker > 0 && random(`${id}${Math.floor(t / 2)}`) < flicker;
  return (
    <text x={x} y={y} textAnchor="middle" fontFamily={fonts.display} fontWeight={900} fontSize={size} fill="none" stroke={color} strokeWidth={size * 0.06} filter={`url(#${id})`} opacity={off ? 0.25 : 1}>
      {children}
    </text>
  );
};

/** Scenes draw `children` (the people) above the set and under the halftone. */
export type SetProps = SceneProps & { children?: ReactNode };

export const BeachScene = ({ w, h, t, id, children }: SetProps) => {
  const s = w / 1000;
  const horizon = h * 0.64;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} width="100%" height="100%" preserveAspectRatio="xMidYMid slice">
      <Sunset w={w} h={h} t={t} id={id} horizon={horizon} />
      <Skyline w={w} base={horizon} seed={`${id}sky`} fill="#2A0E45" maxH={h * 0.09} lit={0} t={t} />
      {Array.from({ length: 4 }, (_, i) => {
        const bx = ((w * (0.2 + i * 0.17) + t * (1.2 + i * 0.3)) % (w * 1.1)) - w * 0.05;
        const by = h * (0.18 + (i % 2) * 0.07) + Math.sin(t / 8 + i) * 4;
        return <path key={i} d={`M${bx - 14 * s} ${by - 6 * s} Q ${bx - 6 * s} ${by - 10 * s} ${bx} ${by} Q ${bx + 6 * s} ${by - 10 * s} ${bx + 14 * s} ${by - 6 * s}`} stroke={C.ink} strokeWidth={3 * s} fill="none" />;
      })}
      <Palm x={w * 0.07} y={h * 1.02} h={h * 0.8} lean={w * 0.14} t={t} s={s * 1.1} />
      <Palm x={w * 0.95} y={h * 1.02} h={h * 0.66} lean={-w * 0.12} t={t + 40} s={s} />
      <Palm x={w * 0.78} y={horizon + h * 0.06} h={h * 0.28} lean={w * 0.03} t={t + 13} s={s * 0.42} />
      {children}
      <Halftone id={id} w={w} h={h} opacity={0.18} />
    </svg>
  );
};

/** The night city; `sign` on the big neon (a time), `side` on the small one (the temptation). */
export const CityScene = ({ w, h, t, id, children, sign = "23:00", side = "SNACK" }: SetProps & { sign?: string; side?: string }) => {
  const base = h * 0.86;
  /** Top of the big sign. */
  const sy = h > w ? h * 0.3 : h * 0.22;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} width="100%" height="100%" preserveAspectRatio="xMidYMid slice">
      <defs>
        <linearGradient id={`${id}-night`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#07021A" /><stop offset="0.55" stopColor="#2A0D52" /><stop offset="1" stopColor="#B0306E" />
        </linearGradient>
        <Glow id={`${id}-glow`} />
      </defs>
      <rect width={w} height={h} fill={`url(#${id}-night)`} />
      <Skyline w={w} base={base} seed={`${id}back`} fill="#2B1250" maxH={h * 0.55} lit={0.12} t={t} />
      <Skyline w={w} base={h} seed={`${id}front`} fill="#0D0520" maxH={h * 0.42} lit={0.22} t={t} />
      <rect x={w * 0.27} y={sy} width={w * 0.46} height={w * 0.2} rx="18" fill="#0D0520" opacity="0.85" />
      <rect x={w * 0.27} y={sy} width={w * 0.46} height={w * 0.2} rx="18" fill="none" stroke={C.cyan} strokeWidth="5" filter={`url(#${id}-glow)`} />
      <NeonText x={w * 0.5} y={sy + w * 0.155} size={w * 0.15} color={C.pink} t={t} id={`${id}-glow`} flicker={0.06}>{sign}</NeonText>
      <NeonText x={w * 0.17} y={sy + w * 0.32} size={w * 0.06} color={C.gold} t={t + 7} id={`${id}-glow`} flicker={0.12}>{side}</NeonText>
      <NeonText x={w * 0.84} y={sy + w * 0.29} size={w * 0.055} color={C.cyan} t={t} id={`${id}-glow`}>24/7</NeonText>
      <rect y={h * 0.93} width={w} height={h * 0.07} fill={C.pink} opacity="0.25" filter={`url(#${id}-glow)`} />
      {children}
      <Halftone id={id} w={w} h={h} opacity={0.16} />
    </svg>
  );
};

/** The legendary outdoor beach gym: a sand pen with a neon arch, pull-up bars, a bench press, a
 * squat rack, dumbbells in the sand, a low fence, palms and a lifeguard tower before the sunset sea. */
export const MuscleBeachScene = ({ w, h, t, id, children }: SetProps) => {
  const tall = h > w;
  const u = tall ? w / 1000 : h / 600;
  const horizon = h * (tall ? 0.5 : 0.52);
  const sand = h * (tall ? 0.6 : 0.66);
  const signY = tall ? h * 0.19 : h * 0.12;
  const post = (x: number, top: number, wd = 14 * u) => <rect x={x - wd / 2} y={top} width={wd} height={sand + 40 * u - top} rx={wd / 3} />;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} width="100%" height="100%" preserveAspectRatio="xMidYMid slice">
      <defs>
        <Glow id={`${id}-glow`} />
        <linearGradient id={`${id}-sand`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#F2A86E" /><stop offset="1" stopColor="#B8664E" />
        </linearGradient>
      </defs>
      <Sunset w={w} h={h} t={t} id={id} horizon={horizon} />
      {/* lifeguard tower on the shore */}
      <g fill={C.ink} transform={`translate(${w * 0.7} ${sand - 6 * u}) scale(${u * 0.9})`}>
        <path d="M-50 -150 H50 L60 -120 H-60 Z" />
        <rect x="-44" y="-122" width="88" height="56" />
        <path d="M-40 -66 L-56 0 M40 -66 L56 0 M-30 -66 L30 0 M30 -66 L-30 0" stroke={C.ink} strokeWidth="7" />
        <rect x="-30" y="-112" width="60" height="26" fill={C.coral} opacity="0.7" />
      </g>
      <rect y={sand} width={w} height={h - sand} fill={`url(#${id}-sand)`} />
      <path d={`M0 ${sand} Q ${w / 2} ${sand - 18 * u} ${w} ${sand}`} fill="#FFD8A8" opacity="0.5" />
      <Palm x={w * 0.04} y={sand + 60 * u} h={h * (tall ? 0.5 : 0.75)} lean={w * 0.08} t={t} s={u * 1.05} />
      <Palm x={w * 0.97} y={sand + 50 * u} h={h * (tall ? 0.45 : 0.7)} lean={-w * 0.09} t={t + 25} s={u} />
      <g fill={C.ink}>
        {/* low fence of the pen */}
        {Array.from({ length: 12 }, (_, i) => <rect key={i} x={(w / 11) * i - 4 * u} y={sand + 30 * u} width={8 * u} height={60 * u} />)}
        <rect y={sand + 36 * u} width={w} height={8 * u} />
        <rect y={sand + 64 * u} width={w} height={6 * u} />
        {/* neon arch over the gate */}
        {post(w * 0.22, signY + 40 * u, 18 * u)}
        {post(w * 0.78, signY + 40 * u, 18 * u)}
        <rect x={w * 0.2} y={signY - 10 * u} width={w * 0.6} height={120 * u} rx={14 * u} fill="#12062A" />
        {/* pull-up bars, left */}
        {post(w * 0.08, sand - 330 * u)}
        {post(w * 0.2, sand - 330 * u)}
        <rect x={w * 0.07} y={sand - 330 * u} width={w * 0.14} height={10 * u} rx={5 * u} />
        <rect x={w * 0.08} y={sand - 240 * u} width={w * 0.12} height={8 * u} rx={4 * u} />
        {/* squat rack with a loaded bar, right */}
        {post(w * 0.83, sand - 250 * u)}
        {post(w * 0.95, sand - 250 * u)}
        <rect x={w * 0.76} y={sand - 190 * u} width={w * 0.26} height={10 * u} rx={5 * u} />
        {[0.77, 0.79, 0.99, 1.01].map((x) => <rect key={x} x={w * x - 9 * u} y={sand - 230 * u} width={18 * u} height={90 * u} rx={6 * u} />)}
        {/* bench press in the middle */}
        <rect x={w * 0.4} y={sand + 2 * u} width={w * 0.2} height={16 * u} rx={6 * u} />
        {post(w * 0.42, sand - 60 * u, 10 * u)}
        {post(w * 0.58, sand - 60 * u, 10 * u)}
        <rect x={w * 0.34} y={sand - 66 * u} width={w * 0.32} height={8 * u} rx={4 * u} />
        {[0.35, 0.65].map((x) => <rect key={x} x={w * x - 8 * u} y={sand - 100 * u} width={16 * u} height={76 * u} rx={5 * u} />)}
        {/* dumbbells and plates in the sand */}
        {[0.28, 0.33, 0.68].map((x, i) => (
          <g key={x} transform={`translate(${w * x} ${sand + 110 * u + i * 8 * u})`}>
            <rect x={-26 * u} y={-4 * u} width={52 * u} height={8 * u} />
            <rect x={-32 * u} y={-14 * u} width={12 * u} height={28 * u} rx={4 * u} />
            <rect x={20 * u} y={-14 * u} width={12 * u} height={28 * u} rx={4 * u} />
          </g>
        ))}
        <ellipse cx={w * 0.74} cy={sand + 130 * u} rx={34 * u} ry={12 * u} />
      </g>
      <NeonText x={w * 0.5} y={signY + 74 * u} size={74 * u} color={C.pink} t={t} id={`${id}-glow`} flicker={0.04}>MUSCLE BEACH</NeonText>
      <NeonText x={w * 0.5} y={signY + 104 * u} size={24 * u} color={C.gold} t={t + 5} id={`${id}-glow`}>OPEN GYM · SUNSET</NeonText>
      {children}
      <Halftone id={id} w={w} h={h} opacity={0.16} />
    </svg>
  );
};

/** Sunset boardwalk with a glowing perspective grid running toward the sun (the « gameplay » ground). */
export const GridScene = ({ w, h, t, id, children }: SetProps) => {
  const horizon = h * 0.45;
  const vx = w / 2;
  const rows = 14;
  const phase = (t * 0.035) % 1;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} width="100%" height="100%" preserveAspectRatio="xMidYMid slice">
      <defs>
        <Glow id={`${id}-glow`} sd={5} />
        <linearGradient id={`${id}-floor`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#3A1060" /><stop offset="1" stopColor="#0E0424" />
        </linearGradient>
      </defs>
      <Sunset w={w} h={h} t={t} id={id} horizon={horizon} sea={false} />
      <Skyline w={w} base={horizon} seed={`${id}sky`} fill="#2A0E45" maxH={h * 0.12} lit={0.08} t={t} />
      <rect y={horizon} width={w} height={h - horizon} fill={`url(#${id}-floor)`} />
      <g stroke={C.pink} strokeWidth="3" filter={`url(#${id}-glow)`} opacity="0.8">
        {Array.from({ length: 25 }, (_, i) => (
          <line key={`v${i}`} x1={vx + (i - 12) * 6} y1={horizon} x2={vx + (i - 12) * w * 0.22} y2={h} />
        ))}
        {Array.from({ length: rows }, (_, i) => {
          const k = (i + phase) / rows;
          const y = horizon + (h - horizon) * k * k;
          return <line key={`h${i}`} x1="0" y1={y} x2={w} y2={y} opacity={0.3 + k} />;
        })}
      </g>
      <Palm x={w * 0.02} y={h * 0.95} h={h * 0.6} lean={w * 0.12} t={t} s={w / 900} />
      <Palm x={w * 0.98} y={h * 0.92} h={h * 0.55} lean={-w * 0.1} t={t + 30} s={w / 950} />
      {children}
      <Halftone id={id} w={w} h={h} opacity={0.12} />
    </svg>
  );
};

/** A person's feet at (x, y), scale s. */
export const At = ({ x, y, s, children }: { x: number; y: number; s: number; children: ReactNode }) => (
  <g transform={`translate(${x} ${y}) scale(${s})`}>{children}</g>
);

export const NIGHT_RIM: [string, string] = [C.pink, C.cyan];

// ---------- HUD ----------

export const starPath = (cx: number, cy: number, R: number) => {
  const pts = Array.from({ length: 10 }, (_, i) => {
    const r = i % 2 ? R * 0.45 : R;
    const a = -Math.PI / 2 + (i * Math.PI) / 5;
    return `${cx + r * Math.cos(a)},${cy + r * Math.sin(a)}`;
  });
  return `M${pts.join(" L")} Z`;
};

/** The craving « wanted level »: 5 slots, `lit` of them flashing; `lost` grays them out. */
export const Wanted = ({ t, lit, lost, label = "Fringale", clearLabel = "Fringale semée" }: { t: number; lit: number; lost: number; label?: string; clearLabel?: string }) => {
  const blink = Math.floor(t / 6) % 2 === 0;
  return (
    <div style={{ position: "absolute", right: 130, top: 300, textAlign: "right" }}>
      <svg width="390" height="80" viewBox="0 0 390 80">
        {Array.from({ length: 5 }, (_, i) => {
          const on = i < lit;
          return (
            <path key={i} d={starPath(40 + i * 77, 40, 34)} fill={on && lost < 1 ? (blink ? "#FFFFFF" : C.yellow) : "rgba(11,6,20,.45)"} stroke={C.ink} strokeWidth="6"
              opacity={on ? 1 - lost * 0.6 : 0.8} />
          );
        })}
      </svg>
      <div style={{ ...display, fontSize: 40, color: lost >= 1 ? "#BBBBBB" : "#FFFFFF", filter: OUTLINE, marginTop: 6 }}>{lost >= 1 ? clearLabel : label}</div>
    </div>
  );
};

/** kcal counter (the money slot) and the protein bar. */
export const Counter = ({ kcal, protein, goal, bar = "Protéines" }: { kcal: number; protein: number; goal: number; bar?: string }) => (
  <div style={{ position: "absolute", right: 130, top: 430, textAlign: "right" }}>
    <div style={{ ...display, fontSize: 92, color: C.money, filter: OUTLINE, whiteSpace: "nowrap" }}>
      {num(kcal)}<span style={{ fontSize: 46, textTransform: "none" }}> kcal</span>
    </div>
    <div style={{ ...display, fontSize: 32, color: "#FFFFFF", filter: OUTLINE, marginTop: 14 }}>{bar} {Math.round(protein)} / {goal} {unit("g")}</div>
    <div style={{ marginTop: 10, marginLeft: "auto", width: 360, height: 22, background: "rgba(11,6,20,.7)", border: `4px solid ${C.ink}` }}>
      <div style={{ width: `${Math.min(1, protein / goal) * 100}%`, height: "100%", background: `linear-gradient(90deg, ${C.teal}, ${C.money})` }} />
    </div>
  </div>
);

export const Toast = ({ t, at, text, color = C.money, y }: { t: number; at: number; text: ReactNode; color?: string; y: number }) => {
  if (t < at || t > at + 40) return null;
  const x = ease(t, at, at + 8, 80, 0);
  const o = interpolate(t, [at, at + 4, at + 32, at + 40], [0, 1, 1, 0], clamp);
  return <div style={{ position: "absolute", right: 130, top: y, ...display, fontSize: 64, color, filter: OUTLINE, transform: `translateX(${x}px)`, opacity: o }}>{text}</div>;
};

export const Minimap = ({ t, alert }: { t: number; alert: boolean }) => {
  const R = 135;
  const rot = t * 0.25;
  const pulse = 1 + 0.25 * Math.sin(t / 3);
  return (
    <div style={{ position: "absolute", left: 75, top: 960 }}>
      <svg width={2 * R + 20} height={2 * R + 60} viewBox={`-10 -10 ${2 * R + 20} ${2 * R + 60}`}>
        <defs><clipPath id="mm"><circle cx={R} cy={R} r={R} /></clipPath></defs>
        <circle cx={R} cy={R} r={R + 7} fill={C.ink} />
        <g clipPath="url(#mm)">
          <rect width={2 * R} height={2 * R} fill="#2C2A3E" />
          <g transform={`rotate(${rot} ${R} ${R})`}>
            <rect x={-R} y={R * 1.4} width={4 * R} height={R} fill="#2A5D7A" />
            {Array.from({ length: 9 }, (_, i) => (
              <g key={i} stroke="#77748C" strokeWidth={i % 3 ? 6 : 12}>
                <line x1={-R + i * 45} y1={-R} x2={-R + i * 45} y2={3 * R} />
                <line x1={-R} y1={-R + i * 52} x2={3 * R} y2={-R + i * 52} />
              </g>
            ))}
            <path d={`M${R} ${R} L${R} ${R - 50} L${R + 90} ${R - 50} L${R + 90} ${R - 140}`} stroke={alert ? C.pink : C.yellow} strokeWidth="9" fill="none" />
            <circle cx={R + 90} cy={R - 140} r="13" fill={C.yellow} stroke={C.ink} strokeWidth="4" />
            {alert && [[-60, 40], [70, 60], [-30, -80]].map(([dx, dy], i) => (
              <circle key={i} cx={R + dx} cy={R + dy} r={11 * pulse} fill={i % 2 ? "#3D7BFF" : "#FF3344"} opacity="0.9" />
            ))}
          </g>
          {alert && <circle cx={R} cy={R} r={R} fill="none" stroke={Math.floor(t / 6) % 2 ? "#FF3344" : "#3D7BFF"} strokeWidth="14" opacity="0.7" />}
        </g>
        <path d={`M${R} ${R - 18} L${R + 13} ${R + 14} L${R} ${R + 6} L${R - 13} ${R + 14} Z`} fill="#FFFFFF" stroke={C.ink} strokeWidth="3" />
        <rect x="0" y={2 * R + 20} width={R * 1.25} height="14" fill={C.money} stroke={C.ink} strokeWidth="4" />
        <rect x={R * 1.32} y={2 * R + 20} width={R * 0.68} height="14" fill={C.cyan} stroke={C.ink} strokeWidth="4" />
      </svg>
    </div>
  );
};

/** Mission objective line, bottom of the safe area; [text, true] parts are yellow. */
export const Objective = ({ t, at, parts, top = 1020 }: { t: number; at: number; parts: [string, boolean?][]; top?: number }) => (
  <div style={{ position: "absolute", left: 400, right: 140, top, fontFamily: fonts.body, fontWeight: 800, fontSize: 46, lineHeight: 1.15, color: "#FFFFFF", filter: "drop-shadow(2px 2px 0 #0B0614) drop-shadow(-2px -2px 0 #0B0614) drop-shadow(0 4px 6px rgba(0,0,0,.6))", opacity: ease(t, at, at + 8) }}>
    {parts.map(([s, y], i) => <span key={i} style={{ color: y ? C.yellow : undefined }}>{s}</span>)}
  </div>
);

export const Letterbox = ({ amount }: { amount: number }) => (
  <>
    <div style={{ position: "absolute", left: 0, right: 0, top: 0, height: 230 * amount, background: "#000" }} />
    <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: 230 * amount, background: "#000" }} />
  </>
);

/** Diagonal sunset slash that covers the cut at `at`. */
export const Wipe = ({ t, at }: { t: number; at: number }) => {
  if (Math.abs(t - at) > 9) return null;
  const x = interpolate(t, [at - 9, at + 9], [-2600, 1500], { easing: Easing.inOut(Easing.cubic) });
  return (
    <div style={{ position: "absolute", top: -200, height: H + 400, left: x, width: 1700, transform: "skewX(-18deg)", background: `linear-gradient(90deg, ${C.gold} 0 6%, ${C.pink} 6% 12%, ${C.violet} 12% 100%)` }} />
  );
};

// ---------- pickups ----------

export const Egg = () => (
  <svg width="170" height="130" viewBox="0 0 170 130">
    {[[55, 70, -12], [115, 70, 14]].map(([x, y, r]) => (
      <ellipse key={x} cx={x} cy={y} rx="38" ry="50" transform={`rotate(${r} ${x} ${y})`} fill="#FFF6E6" stroke={C.ink} strokeWidth="7" />
    ))}
  </svg>
);
export const Skyr = () => (
  <svg width="150" height="150" viewBox="0 0 150 150">
    <path d="M20 30 L130 30 L115 140 L35 140 Z" fill="#FFFFFF" stroke={C.ink} strokeWidth="7" />
    <rect x="12" y="18" width="126" height="20" rx="6" fill={C.cyan} stroke={C.ink} strokeWidth="7" />
    <rect x="30" y="70" width="90" height="34" fill="#2A5DBA" />
    <text x="75" y="97" textAnchor="middle" fontFamily={fonts.display} fontWeight={900} fontSize="28" fill="#FFFFFF">SKYR</text>
  </svg>
);

/** A floating pickup over its glowing marker; collected at `at` (flies to the HUD). */
export const Pickup = ({ t, at, x, y, children }: { t: number; at: number; x: number; y: number; children: ReactNode }) => {
  const gone = ease(t, at, at + 10);
  if (gone >= 1) return null;
  const bob = Math.sin(t / 7) * 14;
  const spin = Math.sin(t / 10) * 10;
  const fx = interpolate(gone, [0, 1], [0, 760 - x]);
  const fy = interpolate(gone, [0, 1], [0, 470 - y]);
  return (
    <div style={{ position: "absolute", left: x, top: y, transform: "translate(-50%, -50%)" }}>
      <svg width="260" height="120" viewBox="0 0 260 120" style={{ position: "absolute", left: -130, top: 70, opacity: 1 - gone }}>
        <ellipse cx="130" cy="60" rx="110" ry="34" fill={C.gold} opacity="0.35" />
        <ellipse cx="130" cy="60" rx="80" ry="24" fill="none" stroke={C.yellow} strokeWidth="6" opacity={0.6 + 0.4 * Math.sin(t / 4)} />
      </svg>
      <div style={{ transform: `translate(${fx}px, ${fy + bob}px) rotate(${spin}deg) scale(${1 - gone * 0.7})`, filter: `drop-shadow(0 0 18px ${C.gold})` }}>{children}</div>
    </div>
  );
};

// ---------- scenes ----------

const Chicken = () => (
  <svg width="170" height="130" viewBox="0 0 170 130">
    <path d="M40 30 C80 0 150 20 140 70 C132 108 80 112 60 90 L34 112 C26 120 12 108 20 100 L42 78 C24 64 20 44 40 30 Z" fill="#C9772F" stroke={C.ink} strokeWidth="7" />
    <path d="M60 42 C84 28 118 36 122 58" stroke="#F2B46A" strokeWidth="8" fill="none" strokeLinecap="round" />
    <circle cx="22" cy="114" r="9" fill="#FFF6E6" stroke={C.ink} strokeWidth="5" />
  </svg>
);
const Shaker = () => (
  <svg width="120" height="170" viewBox="0 0 120 170">
    <rect x="34" y="6" width="52" height="22" rx="6" fill={C.pink} stroke={C.ink} strokeWidth="7" />
    <path d="M22 28 H98 L90 160 H30 Z" fill="#F4F1EA" stroke={C.ink} strokeWidth="7" />
    <rect x="30" y="80" width="60" height="70" fill="#8A5A3C" />
    <path d="M30 70 H90" stroke={C.ink} strokeWidth="5" />
  </svg>
);
const Bowl = () => (
  <svg width="180" height="120" viewBox="0 0 180 120">
    <path d="M30 40 C40 10 140 10 150 40 Z" fill="#7BC86C" stroke={C.ink} strokeWidth="6" />
    <circle cx="70" cy="30" r="12" fill="#F2B46A" stroke={C.ink} strokeWidth="5" />
    <circle cx="108" cy="28" r="10" fill={C.pink} stroke={C.ink} strokeWidth="5" />
    <path d="M14 44 H166 C160 96 124 112 90 112 C56 112 20 96 14 44 Z" fill="#F4F1EA" stroke={C.ink} strokeWidth="7" />
    <path d="M30 60 H150" stroke={C.teal} strokeWidth="8" />
  </svg>
);

/** The foods a mission can pick up (a bowl for anything else). */
export const ITEMS = { egg: Egg, skyr: Skyr, chicken: Chicken, shaker: Shaker, bowl: Bowl } as const;
