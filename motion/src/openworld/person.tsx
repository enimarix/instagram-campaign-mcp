// The « Open World » style's people, in the genre's loading-screen art style (owner 2026-11-25:
// « make the characters look like GTA characters »): realistic proportions, a heavy ink outline,
// sunset rim light on both edges, violet-tinted cel shading (light from the upper left), detailed
// faces. Our own two characters (him, her), not the game's: no copied likeness.
// Drawn in SVG user units, feet at (0, 0), about 980 units tall; place with
// <g transform="translate(x y) scale(s)">. A tiny 2D skeleton poses them (Pose).
// ponytail: front view only; a side view or new outfits = new Look fields.
import type { ReactNode } from "react";

/** Angles in degrees. Limbs: 0 = straight down, positive = outward (away from the body's middle);
 * bends (le, re, lk, rk) are added to their upper limb. l = the screen-left limb. */
export type Pose = { lean: number; tilt: number; ls: number; le: number; rs: number; re: number; lh: number; lk: number; rh: number; rk: number };
export type Face = "neutral" | "smile" | "shock";

export type Look = { build: "him" | "her"; skin: string; hair: string; top: string; shirt?: string; bottoms: string; shoes: string };

export const HIM: Look = { build: "him", skin: "#B87458", hair: "#140A0E", top: "#F2EEE6", shirt: "#1C7F86", bottoms: "#27304A", shoes: "#F4F4F4" };
export const HER: Look = { build: "her", skin: "#D9946E", hair: "#22100C", top: "#17121C", bottoms: "#7FA6D6", shoes: "#FFFFFF" };

export const STAND: Pose = { lean: 0, tilt: 0, ls: 8, le: 5, rs: 8, re: 5, lh: 5, lk: -2, rh: 5, rk: -2 };
export const CHEER: Pose = { lean: 0, tilt: -5, ls: 150, le: 18, rs: 150, re: 18, lh: 8, lk: -2, rh: 8, rk: -2 };

const INK = "#0B0614";
const SHADOW = "#2A0A3A";

type P = [number, number];
const rad = (a: number) => (a * Math.PI) / 180;
const add = (a: P, b: P): P => [a[0] + b[0], a[1] + b[1]];
const mul = (a: P, k: number): P => [a[0] * k, a[1] * k];
const rot = ([x, y]: P, a: number): P => [x * Math.cos(rad(a)) - y * Math.sin(rad(a)), x * Math.sin(rad(a)) + y * Math.cos(rad(a))];
const lerp = (a: P, b: P, u: number): P => [a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u];
const deg = (a: P, b: P) => (Math.atan2(b[1] - a[1], b[0] - a[0]) * 180) / Math.PI;
/** Unit vector of a limb: side -1 (screen left) or 1, angle as Pose. */
const dir = (side: number, a: number): P => [side * Math.sin(rad(a)), Math.cos(rad(a))];

/** `hex` mixed toward the violet shadow by f (0..1): the cel shade. */
const shade = (hex: string, f = 0.42) => {
  const c = (h: string, i: number) => parseInt(h.slice(1 + i * 2, 3 + i * 2), 16);
  const m = [0, 1, 2].map((i) => Math.round(c(hex, i) * (1 - f) + c(SHADOW, i) * f));
  return `#${m.map((v) => v.toString(16).padStart(2, "0")).join("")}`;
};

/** A tapered capsule from a (width wa) to b (width wb). */
const taper = (a: P, b: P, wa: number, wb: number) => {
  const l = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1;
  const n: P = [-(b[1] - a[1]) / l, (b[0] - a[0]) / l];
  const f = (p: P, r: number) => `${p[0] + n[0] * r} ${p[1] + n[1] * r}`;
  return `M${f(a, wa / 2)} L${f(b, wb / 2)} A${wb / 2} ${wb / 2} 0 0 0 ${f(b, -wb / 2)} L${f(a, -wa / 2)} A${wa / 2} ${wa / 2} 0 0 0 ${f(a, wa / 2)} Z`;
};

const BUILD = {
  him: { pelvis: 500, torso: 315, sw: 118, ww: 76, hw: 74, neck: 88, rx: 50, ry: 63, arm: [52, 42, 30], leg: [80, 56, 40], l: [158, 148, 252, 248] },
  her: { pelvis: 485, torso: 292, sw: 90, ww: 56, hw: 70, neck: 84, rx: 45, ry: 58, arm: [38, 31, 23], leg: [68, 46, 30], l: [148, 138, 246, 240] },
};

type Skeleton = ReturnType<typeof skeleton>;
const skeleton = (look: Look, p: Pose) => {
  const b = BUILD[look.build];
  const pelvis: P = [0, -b.pelvis];
  const at = (x: number, y: number) => add(pelvis, rot([x, y], p.lean));
  /** A point on the torso's edge: side -1..1 across, u 0 (shoulders) .. 1 (hips) down. */
  const torso = (side: number, u: number): P => {
    const s = at(side * b.sw, -b.torso + 30);
    const w = at(side * b.ww, -b.torso * 0.45);
    const h = at(side * b.hw, 0);
    return u < 0.55 ? lerp(s, w, u / 0.55) : lerp(w, h, (u - 0.55) / 0.45);
  };
  const neck = at(0, -b.torso);
  const head = add(neck, rot([0, -b.neck], p.lean + p.tilt));
  const limb = (side: number, root: P, a: number, bend: number, l1: number, l2: number) => {
    const mid = add(root, mul(dir(side, a), l1));
    return [root, mid, add(mid, mul(dir(side, a + bend), l2))] as const;
  };
  const arm = (side: number) => limb(side, at(side * (b.sw - 22), -b.torso + 40), side < 0 ? p.ls : p.rs, side < 0 ? p.le : p.re, b.l[0], b.l[1]);
  const leg = (side: number) => limb(side, at(side * b.hw * 0.55, -14), side < 0 ? p.lh : p.rh, side < 0 ? p.lk : p.rk, b.l[2], b.l[3]);
  return { b, torso, neck, head, angle: p.lean + p.tilt, arms: [arm(-1), arm(1)], legs: [leg(-1), leg(1)] };
};

/** Torso region between sides s0..s1 (-1..1) and heights u0..u1. */
const band = (k: Skeleton, s0: number, s1: number, u0: number, u1: number, round = false) => {
  const n = 6;
  const col = (s: number) => Array.from({ length: n + 1 }, (_, i) => k.torso(s, u0 + ((u1 - u0) * i) / n));
  const l = col(s0);
  const r = col(s1).reverse();
  const top = round && u0 === 0 ? `Q ${k.neck[0] + (s0 + s1) * 20} ${k.neck[1] - 10} ` : "L";
  return `M${l.map((q) => q.join(" ")).join(" L")} L${r.map((q) => q.join(" ")).join(" L")} ${top}${l[0].join(" ")} Z`;
};

/** A cel-shaded capsule: the shade, then the lit part toward the upper left. */
const Limb = ({ a, b, wa, wb, col, flat }: { a: P; b: P; wa: number; wb: number; col: string; flat?: string }) => {
  if (flat) return <path d={taper(a, b, wa, wb)} fill={flat} />;
  const o: P = [-wa * 0.13, -wa * 0.04];
  return (
    <>
      <path d={taper(a, b, wa, wb)} fill={shade(col)} />
      <path d={taper(add(a, o), add(b, o), wa * 0.72, wb * 0.72)} fill={col} />
    </>
  );
};

/** A cel-shaded torso band: shade across, lit from the left up to `litTo`. */
const Band = ({ k, s0 = -1, s1 = 1, u0, u1, col, flat, litTo = 0.4, round }: { k: Skeleton; s0?: number; s1?: number; u0: number; u1: number; col: string; flat?: string; litTo?: number; round?: boolean }) => (
  <>
    <path d={band(k, s0, s1, u0, u1, round)} fill={flat ?? shade(col)} />
    {!flat && litTo > s0 && <path d={band(k, s0, Math.min(s1, litTo), u0, u1, round)} fill={col} />}
  </>
);

/** Head outline (local: centre 0 0): cranium and a jaw, squarer for him. */
const headPath = (rx: number, ry: number, square: boolean) => {
  const c = square ? 0.3 : 0.12;
  return `M${-rx} -8 C${-rx} ${-ry * 1.08} ${rx} ${-ry * 1.08} ${rx} -8 C${rx} ${ry * 0.38} ${rx * 0.62} ${ry * 0.86} ${rx * c} ${ry} L${-rx * c} ${ry} C${-rx * 0.62} ${ry * 0.86} ${-rx} ${ry * 0.38} ${-rx} -8 Z`;
};

const Eye = ({ x, her, face }: { x: number; her: boolean; face: Face }) => {
  const m = Math.sign(x);
  const open = face === "shock" ? 1.5 : face === "smile" ? 0.7 : 1;
  const top = -4 - 9 * open;
  return (
    <g transform={`translate(${x} 0)`}>
      <path d={`M${-12} -4 Q 0 ${top} 12 -4 Q 0 ${2 + 2 * open} -12 -4 Z`} fill="#F3E6DC" />
      <circle cx="0" cy={-4.5} r={face === "shock" ? 4 : 5} fill="#2A140C" />
      <circle cx="-1.5" cy="-6.5" r="1.4" fill="#FFFFFF" />
      <path d={`M${-13} -4 Q 0 ${top - 1} 13 -4`} stroke={INK} strokeWidth={her ? 4 : 3.2} fill="none" strokeLinecap="round" />
      {her && <path d={`M${m * 12} -5 L${m * 19} -10`} stroke={INK} strokeWidth="3.4" strokeLinecap="round" />}
    </g>
  );
};

const FaceArt = ({ look, face }: { look: Look; face: Face }) => {
  const her = look.build === "her";
  const { rx, ry } = BUILD[look.build];
  const lip = her ? "#B23A4E" : shade(look.skin, 0.3);
  const raise = face === "shock" ? -6 : 0;
  return (
    <g>
      {/* the shaded right half of the face (light from the upper left) */}
      <path d={headPath(rx, ry, !her)} fill={shade(look.skin, 0.38)} />
      <path d={headPath(rx, ry, !her)} transform={`translate(${-rx * 0.17} -2) scale(0.8 0.97)`} fill={look.skin} />
      {!her && <path d={`M${-rx} 10 C${-rx + 4} ${ry * 0.6} ${-rx * 0.3} ${ry} 0 ${ry} C${rx * 0.3} ${ry} ${rx - 4} ${ry * 0.6} ${rx} 10 C${rx * 0.6} ${ry * 0.5} ${rx * 0.3} ${ry * 0.55} 0 ${ry * 0.55} C${-rx * 0.3} ${ry * 0.55} ${-rx * 0.6} ${ry * 0.5} ${-rx} 10 Z`} fill={look.hair} opacity="0.3" />}
      <Eye x={-19} her={her} face={face} />
      <Eye x={19} her={her} face={face} />
      {her
        ? <path d={`M-30 ${-19 + raise} Q-19 ${-27 + raise} -8 ${-20 + raise} M8 ${-20 + raise} Q19 ${-27 + raise} 30 ${-19 + raise}`} stroke={look.hair} strokeWidth="3.4" fill="none" strokeLinecap="round" />
        : <path d={`M-33 ${-17 + raise} Q-20 ${-26 + raise} -7 ${-19 + raise} L-7 ${-14 + raise} Q-20 ${-20 + raise} -33 ${-13 + raise} Z M33 ${-17 + raise} Q20 ${-26 + raise} 7 ${-19 + raise} L7 ${-14 + raise} Q20 ${-20 + raise} 33 ${-13 + raise} Z`} fill={look.hair} />}
      <path d="M-2 -4 L-5 17 Q0 21 7 18" stroke={shade(look.skin, 0.45)} strokeWidth="3.4" fill="none" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M-9 18 Q-6 20 -3 19" stroke={shade(look.skin, 0.6)} strokeWidth="2.5" fill="none" />
      {face === "shock" ? (
        <ellipse cx="0" cy="33" rx="10" ry="13" fill="#3A0F1E" stroke={lip} strokeWidth="4" />
      ) : face === "smile" ? (
        <path d="M-18 29 Q0 46 18 29 Q0 34 -18 29 Z" fill="#FFF6EE" stroke={lip} strokeWidth="4" strokeLinejoin="round" />
      ) : her ? (
        <g fill={lip}>
          <path d="M-15 30 Q-7 25 0 28 Q7 25 15 30 Q0 33 -15 30 Z" />
          <path d="M-15 30 Q0 41 15 30 Q0 34 -15 30 Z" opacity="0.85" />
        </g>
      ) : (
        <path d="M-14 31 Q0 34 14 31" stroke={lip} strokeWidth="4" fill="none" strokeLinecap="round" />
      )}
      {!her && <path d="M-14 24 Q0 20 14 24 Q0 26 -14 24 Z" fill={look.hair} opacity="0.45" />}
    </g>
  );
};

/** Bold tropical print for his open shirt (the same pattern everywhere, so a shared id is safe). */
const PRINT = "ow-print";
const PrintDefs = ({ base }: { base: string }) => (
  <defs>
    <pattern id={PRINT} width="70" height="70" patternUnits="userSpaceOnUse" patternTransform="rotate(18)">
      <rect width="70" height="70" fill={base} />
      <path d="M10 40 C20 20 40 18 50 30 C40 28 28 32 10 40 Z" fill="#0E4F55" />
      <circle cx="48" cy="54" r="7" fill="#FF3D7F" />
      <circle cx="48" cy="54" r="2.5" fill="#FFD25E" />
      <path d="M20 8 C26 2 34 4 36 12 C30 10 25 10 20 8 Z" fill="#FFB84D" />
    </pattern>
  </defs>
);

/** The figure, all in `flat` (outline and rim passes) or dressed and shaded. */
const Body = ({ look, k, face, flat, t }: { look: Look; k: Skeleton; face: Face; flat?: string; t: number }) => {
  const her = look.build === "her";
  const b = k.b;
  const [A0, A1, A2] = b.arm;
  const [L0, L1, L2] = b.leg;
  const c = (col: string) => flat ?? col;
  const headT = `translate(${k.head[0]} ${k.head[1]}) rotate(${k.angle})`;
  const sway = Math.sin(t / 14) * 3;
  const out: ReactNode[] = [];

  if (her) {
    out.push(<path key="hairback" transform={headT} fill={c(look.hair)}
      d={`M-60 -14 C-70 -86 70 -86 60 -14 C${72 + sway} 40 ${66 + sway} 90 ${84 + sway} 140 C${74 + sway} 170 ${86 + sway} 210 ${64 + sway} 236 C${30 + sway} 220 ${-30 + sway} 220 ${-64 + sway} 236 C${-86 + sway} 210 ${-74 + sway} 170 ${-84 + sway} 140 C${-66 + sway} 90 ${-72 + sway} 40 -60 -14 Z`} />);
  }
  // legs: skin or long trousers, then shorts over the thigh, sneakers
  for (const [hip, knee, ankle] of k.legs) {
    const legCol = her ? look.skin : look.bottoms;
    out.push(<Limb key={`th${hip[0]}`} a={hip} b={knee} wa={L0} wb={L1} col={legCol} flat={flat} />);
    out.push(<Limb key={`sh${hip[0]}`} a={knee} b={ankle} wa={L1} wb={L2} col={legCol} flat={flat} />);
    if (her) out.push(<Limb key={`pa${hip[0]}`} a={hip} b={lerp(hip, knee, 0.3)} wa={L0 + 4} wb={L0} col={look.bottoms} flat={flat} />);
    const toe = Math.sign(ankle[0] || 1) * 12;
    out.push(<g key={`fo${hip[0]}`}>
      <ellipse cx={ankle[0] + toe} cy={ankle[1] + 10} rx={her ? 34 : 42} ry="20" fill={c(look.shoes)} />
      {!flat && <path d={`M${ankle[0] + toe - (her ? 32 : 40)} ${ankle[1] + 16} H${ankle[0] + toe + (her ? 32 : 40)}`} stroke={shade(look.shoes, 0.35)} strokeWidth="6" />}
    </g>);
  }
  // torso: skin, then clothes
  out.push(<Band key="torso" k={k} u0={0} u1={1} col={look.skin} flat={flat} round />);
  if (her) {
    out.push(<Band key="crop" k={k} u0={0.02} u1={0.4} s0={-0.92} s1={0.92} col={look.top} flat={flat} litTo={0.2} />);
    out.push(<Band key="shorts" k={k} u0={0.72} u1={1} col={look.bottoms} flat={flat} litTo={0.35} />);
    if (!flat) out.push(<circle key="navel" cx={k.torso(0, 0.66)[0]} cy={k.torso(0, 0.66)[1]} r="2.5" fill={shade(look.skin, 0.5)} />);
  } else {
    out.push(<Band key="tank" k={k} u0={0.05} u1={0.92} s0={-0.62} s1={0.62} col={look.top} flat={flat} litTo={0.1} />);
    out.push(<Band key="jeans" k={k} u0={0.86} u1={1} col={look.bottoms} flat={flat} />);
    if (!flat) out.push(<path key="belt" d={band(k, -1, 1, 0.86, 0.9)} fill="#2A1A12" />);
    if (look.shirt) {
      out.push(<path key="shirtL" d={band(k, -1.04, -0.5, 0, 0.95, true)} fill={flat ?? `url(#${PRINT})`} />);
      out.push(<path key="shirtR" d={band(k, 0.5, 1.04, 0, 0.95, true)} fill={flat ?? `url(#${PRINT})`} />);
      if (!flat) out.push(<path key="shirtRs" d={band(k, 0.5, 1.04, 0, 0.95, true)} fill={SHADOW} opacity="0.35" />);
    }
  }
  // arms (his short sleeves, tattoo, watch), hands
  k.arms.forEach(([sh, el, wr], i) => {
    out.push(<Limb key={`ua${i}`} a={sh} b={el} wa={A0} wb={A1} col={look.skin} flat={flat} />);
    out.push(<Limb key={`fa${i}`} a={el} b={wr} wa={A1} wb={A2} col={look.skin} flat={flat} />);
    if (!her && look.shirt) {
      out.push(<path key={`sl${i}`} d={taper(sh, lerp(sh, el, 0.5), A0 + 16, A0 + 12)} fill={flat ?? `url(#${PRINT})`} />);
      if (!flat && i === 1) out.push(<path key={`sls${i}`} d={taper(sh, lerp(sh, el, 0.5), A0 + 16, A0 + 12)} fill={SHADOW} opacity="0.35" />);
    }
    if (!flat && !her && i === 0) {
      // tattoo sleeve: leaves climbing the forearm
      out.push(<g key="tattoo" fill={INK} opacity="0.4">
        {[0.15, 0.32, 0.5, 0.68].map((u, j) => {
          const p = lerp(el, wr, u);
          return <path key={u} d="M0 0 C6 -12 18 -12 20 -2 C12 -6 6 -4 0 0 Z" transform={`translate(${p[0]} ${p[1]}) rotate(${deg(el, wr) + (j % 2 ? 40 : -140)})`} />;
        })}
      </g>);
    }
    if (!flat && !her && i === 1) out.push(<path key="watch" d={taper(lerp(el, wr, 0.86), lerp(el, wr, 0.97), A2 + 8, A2 + 8)} fill="#FFD25E" />);
    const hand = add(wr, mul(dir(1, 0), 0));
    out.push(<ellipse key={`ha${i}`} cx={hand[0]} cy={hand[1]} rx={A2 * 0.62} ry={A2 * 0.9} transform={`rotate(${deg(el, wr) - 90} ${hand[0]} ${hand[1]})`} fill={c(i === 1 ? shade(look.skin, 0.2) : look.skin)} />);
  });
  // neck, chain, collarbones
  out.push(<Limb key="neck" a={k.neck} b={lerp(k.neck, k.head, 0.62)} wa={her ? 40 : 52} wb={her ? 34 : 46} col={look.skin} flat={flat} />);
  if (!flat) {
    out.push(<path key="collar" d={`M${k.neck[0] - 46} ${k.neck[1] + 26} Q${k.neck[0] - 20} ${k.neck[1] + 20} ${k.neck[0] - 6} ${k.neck[1] + 30} M${k.neck[0] + 6} ${k.neck[1] + 30} Q${k.neck[0] + 20} ${k.neck[1] + 20} ${k.neck[0] + 46} ${k.neck[1] + 26}`} stroke={shade(look.skin, 0.4)} strokeWidth="3" fill="none" />);
    if (!her) out.push(<path key="chain" d={`M${k.neck[0] - 30} ${k.neck[1] + 6} Q ${k.neck[0]} ${k.neck[1] + 64} ${k.neck[0] + 30} ${k.neck[1] + 6}`} stroke="#FFD25E" strokeWidth="6" fill="none" />);
  }
  // head: ears, face, hair, her sunglasses and hoops
  out.push(
    <g key="head" transform={headT}>
      {!her && [-1, 1].map((m) => <ellipse key={m} cx={m * (b.rx + 2)} cy="2" rx="9" ry="15" fill={c(m < 0 ? look.skin : shade(look.skin, 0.3))} />)}
      <path d={headPath(b.rx, b.ry, !her)} fill={c(look.skin)} />
      {!flat && <FaceArt look={look} face={face} />}
      {her ? (
        <>
          <path fill={c(look.hair)} d="M-50 10 C-58 -60 -20 -84 2 -82 C30 -84 62 -58 50 12 C46 -24 30 -46 4 -52 C-4 -40 -24 -30 -40 -26 C-46 -12 -48 0 -50 10 Z" />
          {!flat && <path d="M-26 -62 Q4 -76 30 -60" stroke="#5A2E22" strokeWidth="5" fill="none" opacity="0.7" />}
          {!flat && (
            <g>
              <path d="M-40 -64 H-6 V-54 C-6 -46 -16 -44 -24 -44 C-34 -44 -42 -50 -40 -64 Z M6 -64 H40 C42 -50 34 -44 24 -44 C16 -44 6 -46 6 -54 Z" fill={INK} />
              <path d="M-34 -58 H-22 M12 -58 H24" stroke="#FF3D7F" strokeWidth="3" strokeLinecap="round" />
              {[-1, 1].map((m) => <circle key={m} cx={m * (b.rx + 2)} cy="34" r="12" fill="none" stroke="#FFD25E" strokeWidth="4" />)}
            </g>
          )}
        </>
      ) : (
        <>
          <path fill={c(look.hair)} d={`M${-b.rx - 1} -6 C${-b.rx - 4} -58 -26 -80 2 -80 C30 -80 ${b.rx + 4} -58 ${b.rx + 1} -6 C${b.rx - 6} -30 ${b.rx - 14} -42 ${b.rx - 22} -46 C10 -50 -16 -50 ${-b.rx + 22} -46 C${-b.rx + 14} -42 ${-b.rx + 6} -30 ${-b.rx - 1} -6 Z`} />
          {!flat && <path d="M-30 -62 Q0 -74 28 -64" stroke="#3A2A2E" strokeWidth="5" fill="none" opacity="0.8" />}
        </>
      )}
    </g>,
  );
  return <g>{out}</g>;
};

/** A dumbbell in the hand at the end of an arm (forearm from `el` to `wr`). */
const Dumbbell = ({ el, wr }: { el: P; wr: P }) => (
  <g transform={`translate(${wr[0]} ${wr[1]}) rotate(${deg(el, wr) + 90})`} fill="#1A1A24" stroke={INK} strokeWidth="5">
    <rect x="-58" y="-7" width="116" height="14" rx="5" />
    <rect x="-68" y="-26" width="22" height="52" rx="6" />
    <rect x="46" y="-26" width="22" height="52" rx="6" />
  </g>
);

/**
 * A lit person: the ink outline, two rim passes (left / right colours, shifted out), then the
 * dressed, cel-shaded figure. `dumbbell`: in the screen-left hand.
 */
export const Person = ({ look, pose, face = "neutral", rim = ["#FF3D7F", "#FFB84D"], t, dumbbell = false }: {
  look: Look; pose: Pose; face?: Face; rim?: [string, string]; t: number; dumbbell?: boolean;
}) => {
  const breathe = Math.sin(t / 18) * 1.2;
  const k = skeleton(look, { ...pose, lean: pose.lean + breathe * 0.4 });
  return (
    <g>
      {look.shirt && <PrintDefs base={look.shirt} />}
      <g stroke={INK} strokeWidth="14" strokeLinejoin="round"><Body look={look} k={k} face={face} flat={INK} t={t} /></g>
      <g transform="translate(-6 -2)"><Body look={look} k={k} face={face} flat={rim[0]} t={t} /></g>
      <g transform="translate(6 -2)"><Body look={look} k={k} face={face} flat={rim[1]} t={t} /></g>
      <Body look={look} k={k} face={face} t={t} />
      {dumbbell && <Dumbbell el={k.arms[0][1]} wr={k.arms[0][2]} />}
    </g>
  );
};
