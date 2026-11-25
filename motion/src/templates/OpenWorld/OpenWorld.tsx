// « GTA 6 » (owner 2026-11-25): an open-world crime-game mission at sunset, in drawn
// loading-screen art. Scenes: schema.ts. Sets, HUD and pickups: src/openworld/kit.tsx; the two
// people: src/openworld/person.tsx; end card: src/endcards/Gta6EndCard.tsx.
import { type ReactNode, useMemo } from "react";
import { AbsoluteFill, Html5Audio, interpolate, Sequence, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { SafeZoneGuide } from "../../components/SafeZoneGuide";
import { Sfx } from "../../components/Sfx";
import { EndCard } from "../../endcards/EndCard";
import { spokenLines } from "../../lib/duck";
import { fonts } from "../../lib/font";
import { shotIndex } from "../../lib/timeline";
import {
  At, BeachScene, C, CityScene, clamp, Counter, display, ease, gradText, GridScene, H, ITEMS, Letterbox, Minimap, MuscleBeachScene,
  NIGHT_RIM, Objective, OUTLINE, Pickup, SUNSET, Toast, unit, W, Wanted, Wipe,
} from "../../openworld/kit";
import { CHEER, HER, HIM, Person, type Pose, STAND } from "../../openworld/person";
import { type OpenWorldProps, pickupFrames, timelineOf } from "./schema";

type S = { p: OpenWorldProps; t: number; len: number };

/** Her dumbbell curl: the screen-left forearm comes up to the shoulder and down. */
const curl = (t: number): Pose => ({ ...STAND, ls: 8, le: interpolate(Math.sin(t / 9), [-1, 1], [-8, -150]), rs: 14, re: 6 });
const HAND_ON_HIP: Pose = { ...STAND, tilt: -5, rs: 38, re: -100, lh: 6, rh: 2, ls: 14, le: 4 };
/** Him reaching out for the pickups. */
const reach = (t: number): Pose => ({ ...STAND, ls: 35 + Math.sin(t / 8) * 6, le: 30, rs: 120 + Math.cos(t / 8) * 8, re: 15 });

/** The objective line split round its highlight. */
const parts = (line: string, highlight?: string): [string, boolean?][] => {
  const i = highlight ? line.indexOf(highlight) : -1;
  return i < 0 || !highlight ? [[line]] : [[line.slice(0, i)], [highlight, true], [line.slice(i + highlight.length)]];
};

/** A new framing every 3 s at most (lib/timeline.ts MAX_SHOT_S): wide, closer, half-way. */
const Camera = ({ t, len, children }: { t: number; len: number; children: ReactNode }) => {
  const { fps } = useVideoConfig();
  const shot = shotIndex(t, len, fps);
  const [s, x, y] = [[1.03, 0, 0], [1.16, -40, 60], [1.09, 40, -30]][shot % 3];
  return <div style={{ position: "absolute", inset: 0, transform: `translate(${x}px, ${y}px) scale(${s + t * 0.0006})` }}>{children}</div>;
};

const Panel = ({ x, y, w, h, rot, drift, t, children }: { x: number; y: number; w: number; h: number; rot: number; drift: number; t: number; children: ReactNode }) => (
  <div style={{ position: "absolute", left: x, top: y, width: w, height: h, transform: `rotate(${rot}deg) translateX(${drift * t}px)`, border: "12px solid #FFFFFF", boxShadow: "0 24px 40px rgba(0,0,0,.55)", overflow: "hidden", background: C.ink }}>
    <div style={{ width: "100%", height: "100%", transform: `scale(${1.05 + t * 0.0012})` }}>{children}</div>
  </div>
);

const Hook = ({ p, t }: S) => {
  const punch = 1 + 0.06 * (1 - ease(t, 0, 10));
  return (
    <AbsoluteFill style={{ background: `linear-gradient(180deg, ${C.night}, ${C.violet})` }}>
      <Panel x={30} y={90} w={1020} h={610} rot={-3} drift={-0.25} t={t}><BeachScene w={1020} h={610} t={t} id="hb" /></Panel>
      <Panel x={50} y={700} w={980} h={560} rot={2.4} drift={0.3} t={t}>
        <CityScene w={980} h={560} t={t} id="hc" sign={p.sign} side={p.side}><At x={830} y={1010} s={0.8}><Person look={HIM} pose={{ ...STAND, tilt: -7 }} face="shock" rim={NIGHT_RIM} t={t} /></At></CityScene>
      </Panel>
      <Panel x={20} y={1270} w={1040} h={600} rot={-2} drift={-0.2} t={t}>
        <MuscleBeachScene w={1040} h={600} t={t} id="hg"><At x={170} y={830} s={0.75}><Person look={HER} pose={curl(t)} t={t} dumbbell /></At></MuscleBeachScene>
      </Panel>
      <div style={{ position: "absolute", left: 70, right: 140, top: 290, transform: `scale(${punch}) rotate(-3deg)`, transformOrigin: "left center" }}>
        <div style={{ ...display, fontSize: 100, color: "#FFFFFF", filter: OUTLINE, textWrap: "balance" }}>{p.hook.lead}</div>
        <div style={{ ...display, fontSize: 84, marginTop: 14, ...gradText(SUNSET), filter: OUTLINE, textWrap: "balance" }}>{p.hook.key}</div>
      </div>
    </AbsoluteFill>
  );
};

const Mission = ({ p, t, len }: S) => {
  const bars = ease(t, 0, 14);
  const title = ease(t, 10, 34);
  return (
    <AbsoluteFill>
      <Camera t={t} len={len}>
        <MuscleBeachScene w={W} h={H} t={t + 105} id="mb">
          <At x={360} y={2030} s={1.1}><Person look={HIM} pose={{ ...STAND, tilt: 3 }} t={t} /></At>
          <At x={720} y={2030} s={1.1}><Person look={HER} pose={HAND_ON_HIP} t={t + 30} dumbbell /></At>
        </MuscleBeachScene>
      </Camera>
      <AbsoluteFill style={{ background: "radial-gradient(ellipse at 50% 38%, rgba(11,6,20,0) 30%, rgba(11,6,20,.55) 100%)" }} />
      <Letterbox amount={bars} />
      <div style={{ position: "absolute", left: 70, right: 140, top: 500, textAlign: "center", opacity: title }}>
        <div style={{ ...display, fontSize: 40, letterSpacing: `${0.5 - title * 0.2}em`, color: "#FFFFFF", filter: OUTLINE }}>Mission</div>
        <div style={{ ...display, fontSize: 116, marginTop: 20, letterSpacing: `${0.12 * (1 - title) - 0.02}em`, ...gradText(SUNSET), filter: `${OUTLINE} blur(${(1 - title) * 8}px)`, textWrap: "balance" }}>{p.mission.title}</div>
        <div style={{ fontFamily: fonts.body, fontWeight: 700, fontSize: 40, color: "#FFFFFF", marginTop: 34, filter: OUTLINE, opacity: ease(t, 30, 45) }}>{p.mission.objective}</div>
      </div>
    </AbsoluteFill>
  );
};

/** Frame (from the chase's start) where star `i` lights up. */
const starAt = (i: number) => 15 + i * 10;

const Chase = ({ p, t, len }: S) => {
  const lit = Array.from({ length: p.chase.stars }, (_, i) => i).filter((i) => t >= starAt(i)).length;
  const flash = lit > 0 ? (Math.floor(t / 5) % 2 ? "rgba(255,40,60,.55)" : "rgba(60,110,255,.55)") : "transparent";
  return (
    <AbsoluteFill>
      <Camera t={t} len={len}>
        <CityScene w={W} h={H} t={t} id="wc" sign={p.sign} side={p.side}>
          <At x={740} y={2080} s={1.15}><Person look={HIM} pose={{ ...STAND, tilt: -8 }} face={t < 12 ? "neutral" : "shock"} rim={NIGHT_RIM} t={t} /></At>
        </CityScene>
      </Camera>
      <AbsoluteFill style={{ boxShadow: `inset 0 0 160px 50px ${flash}` }} />
      <Wanted t={t} lit={lit} lost={0} label={p.chase.label} />
      <Minimap t={t} alert={lit > 0} />
      <Objective t={t} at={8} top={820} parts={parts(p.chase.line, p.chase.highlight)} />
    </AbsoluteFill>
  );
};

/** Where the pickups float on the grid (1-3). */
const SPOTS: [number, number][] = [[240, 700], [840, 780], [690, 600]];

const lootState = (p: OpenWorldProps, at: number[], t: number) => {
  let grams = 0;
  let kcal = p.loot.kcal;
  p.loot.items.forEach((it, k) => {
    const u = interpolate(t, [at[k], at[k] + 12], [0, 1], clamp);
    grams += it.grams * u;
    kcal -= it.kcal * u;
  });
  return { grams, kcal };
};

const Loot = ({ p, t, len, clear }: S & { clear?: { t: number; len: number } }) => {
  const at = pickupFrames(p.loot.items.length, len);
  const tt = clear ? len + clear.t : t;
  const { grams, kcal } = lootState(p, at, tt);
  return (
    <AbsoluteFill>
      <Camera t={clear ? clear.t : t} len={clear ? clear.len : len}>
        <GridScene w={W} h={H} t={tt} id="lg">
          <At x={440} y={1220} s={0.8}><Person look={HIM} pose={clear ? { ...STAND, tilt: -3, rs: 150, re: 20 } : reach(t)} face={clear ? "smile" : "neutral"} t={tt} /></At>
        </GridScene>
      </Camera>
      <Wanted t={tt} lit={p.chase.stars} lost={clear ? ease(clear.t, 4, 14) : 0} label={p.chase.label} clearLabel={p.clear.label} />
      <Counter kcal={kcal} protein={grams} goal={p.loot.goal} bar={p.loot.bar} />
      {!clear && p.loot.items.map((it, k) => {
        const Icon = ITEMS[it.item];
        return (
          <div key={k}>
            <Toast t={t} at={at[k] + 8} text={<>+{it.grams} {unit("g")}</>} y={640} />
            <Pickup t={t} at={at[k]} x={SPOTS[k][0]} y={SPOTS[k][1]}><Icon /></Pickup>
          </div>
        );
      })}
      <Minimap t={tt} alert={!clear} />
      {clear
        ? <Objective t={clear.t} at={2} parts={parts(p.clear.line, p.clear.highlight)} />
        : <Objective t={t} at={4} parts={parts(p.loot.line, p.loot.highlight)} />}
    </AbsoluteFill>
  );
};

const Passed = ({ p, t, len }: S) => {
  const { fps } = useVideoConfig();
  const slam = spring({ frame: t - 4, fps, config: { damping: 12, stiffness: 140 } });
  const line = (at: number) => ({ opacity: ease(t, at, at + 8), transform: `translateY(${ease(t, at, at + 8, 30, 0)}px)` });
  return (
    <AbsoluteFill>
      <div style={{ position: "absolute", inset: 0, filter: `saturate(${1 - ease(t, 0, 10) * 0.6}) brightness(${1 - ease(t, 0, 10) * 0.45})` }}>
        <Camera t={t} len={len}>
          <MuscleBeachScene w={W} h={H} t={180 + t * 0.2} id="pg">
            <At x={370} y={1900} s={1.05}><Person look={HIM} pose={CHEER} face="smile" t={t} /></At>
            <At x={720} y={1900} s={1.05}><Person look={HER} pose={{ ...CHEER, ls: 140, rs: 160 }} face="smile" t={t + 20} /></At>
          </MuscleBeachScene>
        </Camera>
      </div>
      <div style={{ position: "absolute", left: 0, right: 0, top: 520, height: 520, background: "linear-gradient(180deg, rgba(11,6,20,0), rgba(11,6,20,.75) 20%, rgba(11,6,20,.75) 80%, rgba(11,6,20,0))" }} />
      <div style={{ position: "absolute", left: 70, right: 140, top: 580, textAlign: "center" }}>
        <div style={{ ...display, fontSize: 132, ...gradText(`linear-gradient(180deg, #FFF3A8, ${C.gold} 45%, ${C.orange})`), filter: OUTLINE, transform: `scale(${interpolate(slam, [0, 1], [1.6, 1])})`, opacity: Math.min(1, slam * 2), textWrap: "balance" }}>{p.passed.title}</div>
        <div style={{ ...display, fontSize: 58, color: C.money, filter: OUTLINE, marginTop: 34, ...line(22) }}>{p.passed.reward}</div>
        {p.passed.detail && <div style={{ ...display, fontSize: 46, color: "#FFFFFF", filter: OUTLINE, marginTop: 18, ...line(32) }}>{p.passed.detail}</div>}
      </div>
    </AbsoluteFill>
  );
};

export const OpenWorld = (p: OpenWorldProps) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const { timeline, endStart } = useMemo(() => timelineOf(p, fps), [p, fps]);
  const starts = timeline.scenes.slice(0, 6).map((s) => s.startFrame);
  const ends = [...starts.slice(1), endStart];
  const lens = starts.map((s, i) => ends[i] - s);
  const lines = spokenLines(p.voice);
  const voice = p.voice?.audioSrc;
  const views = [Hook, Mission, Chase, Loot, null, Passed] as const;
  const at = (i: number) => frame - starts[i];
  const pick = pickupFrames(p.loot.items.length, lens[3]);
  return (
    <AbsoluteFill style={{ background: C.ink, overflow: "hidden" }}>
      {views.map((View, i) => (
        <Sequence key={i} from={starts[i]} durationInFrames={lens[i]} layout="none">
          {View ? <View p={p} t={at(i)} len={lens[i]} /> : <Loot p={p} t={lens[3]} len={lens[3]} clear={{ t: at(4), len: lens[4] }} />}
        </Sequence>
      ))}
      <Sequence from={endStart} layout="none">
        <EndCard style="gta6" tagline={p.outro} accent={p.accent} cameo="duo" address={p.address} pixelate={1} />
      </Sequence>
      {[...starts.slice(1), endStart].map((s) => <Wipe key={s} t={frame} at={s} />)}
      {[...starts.slice(1), endStart].map((s) => <Sfx key={`w${s}`} id="sfx-swish" at={s - 8} lines={lines} />)}
      {Array.from({ length: p.chase.stars }, (_, i) => <Sfx key={`s${i}`} id="sfx-select" at={starts[2] + starAt(i)} lines={lines} />)}
      {pick.map((f, k) => <Sfx key={`c${k}`} id="sfx-coin" at={starts[3] + f} lines={lines} />)}
      <Sfx id="sfx-confirm" at={starts[4] + 4} lines={lines} />
      <Sfx id="sfx-chime" at={starts[5] + 4} lines={lines} />
      <SafeZoneGuide show={!!p.safeZone} />
      {voice && <Html5Audio src={voice} />}
    </AbsoluteFill>
  );
};
