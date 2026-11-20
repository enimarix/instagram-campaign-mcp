// Editorial (step 144): black editorial art direction. A type-only hook (kicker chip, white
// grotesk + pink italic serif), 3-5 counted chapters (« 01 / 04 », a scrubber whose playhead
// runs with the video) that cut between the pixel blossom tree (it grows, takes a gust with
// anticipation, sheds petals, is framed by viewfinder brackets or a ring), a before / after
// split and cute anatomy characters on deep blue cards (pixel caption, a mood change), the
// payoff over the tree in full bloom, then the editorial end card. The tree stays in place
// across chapters while the type changes around it.
import { type CSSProperties, useMemo } from "react";
import { AbsoluteFill, Html5Audio, Sequence, useCurrentFrame, useVideoConfig } from "remotion";
import { MusicBed } from "../../components/MusicBed";
import { SafeZoneGuide } from "../../components/SafeZoneGuide";
import { Sfx } from "../../components/Sfx";
import { Character } from "../../editorial/Character";
import { Brackets, Counter, DeepGround, DotGrid, Drift, ease, GROTESK, Kicker, LEFT, PixelCaption, PixelDefs, Rise, Scrubber, SERIF, StatCard, struckWords, TagChip, W, H } from "../../editorial/kit";
import { BLACK, CHARACTERS, PINK } from "../../editorial/palette.ts";
import { FlatTree, Tree } from "../../editorial/Tree";
import { CROWN, gustOf, GUST_RANGE, TREE } from "../../editorial/blossom.ts";
import { EndCard } from "../../endcards/EndCard";
import { frenchSpaces } from "../../lib/french";
import { type SfxId, spokenLines } from "../../lib/duck";
import { loopFade } from "../../lib/timeline";
import { type Camera, cameraOf, payoffCamera } from "./layout";
import { bloomOf, cameoOf, type Chapter, type EditorialProps, timelineOf } from "./schema";

type SceneProps = { p: EditorialProps; index: number; f: number; len: number; frame: number };

/** The hook's key word rises at HOOK_KEY_AT, then the strike. */
export const HOOK_KEY_AT = 8;
export const HOOK_STRIKE_AT = 18;
/** Words of a Rise land 16 frames after their start; the key's words start 3 frames apart. */
const RISE = 16;

/** The Reel cover: once every word of the key has landed and the strike is drawn (at least 1.2 s). */
export const coverFrame = (p: Pick<EditorialProps, "hook">, fps: number) =>
  Math.max(Math.round(1.2 * fps), HOOK_KEY_AT + 3 * (p.hook.key.split(" ").length - 1) + RISE + 1, HOOK_STRIKE_AT + p.hook.lead.split(" ").length + 11);
/** Frames the anatomy card takes to slide up (or down, out). */
const CARD_SLIDE = 12;
/** Where the tree's foot stands. */
const GROUND = 1150;

/** Rough lines a text wraps to at `size` px in `width` (Inter Tight 900 ≈ 0.5 em a character). */
const linesOf = (text: string, size: number, width: number, em = 0.5) => Math.max(1, Math.ceil((Array.from(text).length * size * em) / width));
const titleSize = (t: string) => (Array.from(t).length > 18 ? 80 : 96);

/** Bottom of a chapter's header (eyebrow, title, key), for placing the stage under it. */
const headerBottom = (c: Chapter) => {
  if (c.scene === "anatomy") return 0;
  const size = titleSize(c.title);
  return 345 + linesOf(c.title, size, 900) * size * 1.02 + (c.key ? 14 + linesOf(c.key, 58, 900, 0.42) * 66 : 0);
};

/** The tree on the chapter stage: as large as fits between the header and the ground. */
const stageOf = (top: number, ground: number, x = 540) => {
  const s = Math.min(0.9, (ground - top - 30) / TREE.height);
  return { x, y: ground, s };
};

const ChapterHeader = ({ p, c, n, f }: { p: EditorialProps; c: Chapter & { title: string; key?: string }; n: number; f: number }) => {
  const size = titleSize(c.title);
  return (
    <>
      {p.eyebrow && <div style={{ ...SERIF, position: "absolute", left: LEFT, top: 282, fontSize: 44 }}>{frenchSpaces(p.eyebrow)}</div>}
      <Counter n={n} total={p.chapters.length} f={f} />
      <div style={{ position: "absolute", left: LEFT, top: 345, width: 900, lineHeight: 1.02 }}>
        <Rise text={c.title} f={f} start={1} style={{ ...GROTESK, fontSize: size }} />
        {c.key && (
          <div style={{ marginTop: 14, lineHeight: 1.12 }}>
            <Rise text={c.key} f={f} start={8} style={{ ...SERIF, fontSize: 58 }} />
          </div>
        )}
      </div>
    </>
  );
};

/** The crown's box on screen for a tree standing at `stage`. */
const crownBox = (stage: { x: number; y: number; s: number }) => ({
  x: stage.x + CROWN.left * stage.s,
  y: stage.y + CROWN.top * stage.s,
  w: (CROWN.right - CROWN.left) * stage.s,
  h: (CROWN.bottom - CROWN.top) * stage.s,
});

/** SVG transform of a camera over the tree at `stage`: the crown point (u, v) brought to `at` (or kept), zoomed and rolled. */
const cameraTransform = (cam: Camera, stage: { x: number; y: number; s: number }) => {
  const box = crownBox(stage);
  const fx = box.x + box.w * cam.u;
  const fy = box.y + box.h * cam.v;
  const [sx, sy] = cam.at ?? [fx, fy];
  return `translate(${sx} ${sy}) scale(${cam.z}) rotate(${cam.roll}) translate(${-fx} ${-fy})`;
};

/** Black behind the header when the picture runs up under it (close-ups). */
const HeaderShade = () => <div style={{ position: "absolute", left: 0, top: 0, width: W, height: 760, background: "linear-gradient(#000 0%, #000 52%, rgba(0,0,0,0) 100%)" }} />;

const TreeChapter = ({ p, index, f, len, frame }: SceneProps) => {
  const c = p.chapters[index - 1] as Extract<Chapter, { scene: "tree" }>;
  const [from, to] = bloomOf(p.chapters, index - 1);
  const first = !p.chapters.slice(0, index - 1).some((x) => x.scene === "tree" || x.scene === "split");
  const bloom = c.action === "bloom" ? from + (to - from) * ease(f, len * 0.15, len * 0.6) : to;
  const grow = first && c.action === "bloom" ? ease(f, 0, len * 0.4) : 1;
  const top = headerBottom(c) + 10;
  const stage = stageOf(top, c.stat ? 900 : GROUND, c.tags.length ? 420 : 540);
  const gust = c.action === "wind" ? gustOf(f, len) : c.action === "petals" ? 0.3 + 0.15 * Math.sin(f / 9) : 0;
  const petals = c.action === "petals" ? 90 : c.action === "wind" ? 40 : 14;
  const cam = cameraOf(c.action, f / len);
  // The gust shakes the frame a little at its peak.
  const shake = c.action === "wind" ? Math.max(0, gust - 0.6) * Math.sin(f * 1.7) * 10 : 0;
  const box = crownBox(stage);
  const framed = c.action === "frame" ? ease(f, len * 0.1, len * 0.3) : 0;
  const ring = c.action === "loop" ? ease(f, len * 0.1, len * 0.45) : 0;
  const r = Math.max(box.w, box.h) / 2 + 30;
  const close = c.action === "petals";
  return (
    <>
      {framed > 0 && <DotGrid opacity={framed} />}
      <svg width={W} height={H} style={{ position: "absolute", inset: 0 }}>
        <g transform={`translate(${shake} 0) ${cameraTransform(cam, stage)}`}>
          <Tree {...stage} frame={frame} bloom={bloom} grow={grow} gust={gust} petals={petals} wind={c.action === "wind" ? { f, len } : undefined} />
          {framed > 0 && <Brackets x={box.x - 20} y={box.y - 20} w={box.w + 40} h={box.h + 40} p={framed} />}
          {ring > 0 && (
            <circle cx={box.x + box.w / 2} cy={box.y + box.h / 2} r={r} fill="none" stroke={PINK} strokeWidth={6} strokeDasharray={2 * Math.PI * r} strokeDashoffset={2 * Math.PI * r * (1 - ring)} transform={`rotate(-90 ${box.x + box.w / 2} ${box.y + box.h / 2})`} style={{ filter: `drop-shadow(0 0 12px ${PINK})` }} />
          )}
        </g>
      </svg>
      {close && <Drift frame={frame} count={22} />}
      {close && <HeaderShade />}
      {c.tags.map((t, i) => {
        const at = Math.round(len * (0.3 + 0.14 * i));
        const e = ease(f, at, 14);
        return f >= at ? <TagChip key={i} text={t.text} mark={t.mark} style={{ position: "absolute", left: 640, top: Math.max(top + 40, box.y + 120) + i * 104, opacity: e, transform: `translateX(${(1 - e) * 60}px)` }} /> : null;
      })}
      {c.stat && <StatCard {...c.stat} f={f} start={Math.round(len * 0.3)} style={{ position: "absolute", left: LEFT, top: 925 }} />}
      <ChapterHeader p={p} c={c} n={index} f={f} />
    </>
  );
};

const SplitChapter = ({ p, index, f, len, frame }: SceneProps) => {
  const c = p.chapters[index - 1] as Extract<Chapter, { scene: "split" }>;
  const top = headerBottom(c) + 30;
  const h = (1170 - top - 30) / 2;
  const panel = (k: number) => ease(f, Math.round(len * (0.05 + 0.2 * k)), 16);
  const box = { x: 200, w: 790, h };
  const side = (text: string, y: number, e: number) => (
    <div style={{ ...SERIF, position: "absolute", left: 60, top: y + h, width: h, fontSize: 60, transformOrigin: "0 0", transform: `rotate(-90deg) translateX(${(1 - e) * -40}px)`, opacity: e, whiteSpace: "nowrap", textAlign: "center" }}>
      {frenchSpaces(text)}.
    </div>
  );
  const y2 = top + h + 30;
  const label: CSSProperties = { position: "absolute", left: box.x + 22, fontFamily: GROTESK.fontFamily, fontSize: 22, fontWeight: 700, letterSpacing: "0.22em", textTransform: "uppercase" };
  // Camera: the panels slide in from opposite sides, then the shot pushes in on « avec ».
  const push = ease(f, len * 0.45, len * 0.55);
  const slideX = (k: number) => (1 - panel(k)) * (k ? 120 : -120);
  return (
    <>
      <div style={{ position: "absolute", inset: 0, transformOrigin: `600px ${y2 + h / 2}px`, transform: `scale(${1 + 0.07 * push})` }}>
        <svg width={W} height={H} style={{ position: "absolute", inset: 0 }}>
          <defs>
            <linearGradient id="flatSky" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stopColor="#E9E4FA" />
              <stop offset="1" stopColor="#FBE7F0" />
            </linearGradient>
          </defs>
          <g opacity={panel(0) * (1 - 0.45 * push)} transform={`translate(${slideX(0)} 0)`}>
            <rect x={box.x} y={top} width={box.w} height={h} rx={26} fill="url(#flatSky)" />
            <rect x={box.x} y={top + h - 46} width={box.w} height={46} fill="#BFE3B4" />
            <svg x={box.x} y={top} width={box.w} height={h}>
              <FlatTree x={box.w / 2} y={h - 30} s={Math.min(0.9, (h - 60) / 480)} frame={frame} />
            </svg>
          </g>
          <g opacity={panel(1)} transform={`translate(${slideX(1)} 0)`}>
            <rect x={box.x} y={y2} width={box.w} height={h} rx={26} fill={BLACK} stroke="#2A2830" strokeWidth={3} />
            <svg x={box.x} y={y2} width={box.w} height={h}>
              <Tree x={box.w / 2} y={h - 24} s={(h - 50) / TREE.height} frame={frame} bloom={0.25 + 0.75 * ease(f, len * 0.25, len * 0.45)} petals={30} />
            </svg>
          </g>
        </svg>
        <div style={{ ...label, top: top + 18, color: "#6B5E8C", opacity: panel(0) }}>• {c.before}</div>
        <div style={{ ...label, top: y2 + 18, color: PINK, opacity: panel(1) }}>• {c.after}</div>
        {side(c.before, top, panel(0))}
        {side(c.after, y2, panel(1))}
      </div>
      <ChapterHeader p={p} c={c} n={index} f={f} />
    </>
  );
};

/** The deep blue card: the character (its mood turning halfway when `then`), the caption on top, the stat under. */
const AnatomyCard = ({ p, index, f, len }: SceneProps) => {
  const c = p.chapters[index - 1] as Extract<Chapter, { scene: "anatomy" }>;
  const turn = Math.round(len * 0.5);
  const mood = c.then && f >= turn ? c.then : c.mood;
  const arrive = ease(f, 6, 14);
  const aura = CHARACTERS[c.character].aura;
  // Camera: a slow push on the character while the ground drifts by (parallax).
  const push = 1 + 0.1 * ease(f, 10, len - 10);
  return (
    <div style={{ position: "absolute", left: 40, top: 180, width: 1000, height: 1560, borderRadius: 44, overflow: "hidden", border: "4px solid #3B3FA6", boxShadow: "0 0 0 2px #000, 0 30px 80px rgba(43,47,134,0.45)" }}>
      <DeepGround f={f} drift={-f * 0.9}>
        <PixelDefs />
        <defs>
          <radialGradient id="aura" cx="50%" cy="50%" r="50%">
            <stop offset="0" stopColor="#FFE2A8" />
            <stop offset="0.5" stopColor={aura} />
            <stop offset="1" stopColor={aura} stopOpacity={0.85} />
          </radialGradient>
          <linearGradient id="statShade" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#0C0E33" stopOpacity={0} />
            <stop offset="0.3" stopColor="#0C0E33" stopOpacity={0.85} />
            <stop offset="1" stopColor="#0C0E33" stopOpacity={0.85} />
          </linearGradient>
        </defs>
        <g transform={`translate(500 560) scale(${push}) translate(-500 -560)`}>
          <g transform={`translate(500 560) scale(${(0.6 + 0.4 * arrive) * (1 + 0.015 * Math.sin(f / 11))})`} filter="url(#px)" opacity={arrive}>
            <ellipse rx={300} ry={320} fill="url(#aura)" stroke={PINK} strokeWidth={14} />
          </g>
          {arrive > 0 && <Character id={c.character} mood={mood} f={f} changed={c.then && f >= turn ? f - turn : 99} x={500} y={570} s={0.95 * (0.5 + 0.5 * arrive)} />}
        </g>
        {c.stat && <rect y={760} width={1000} height={800} fill="url(#statShade)" />}
      </DeepGround>
      <div style={{ position: "absolute", left: 70, top: 180, width: 860, opacity: ease(f, 2, 10) }}>
        <PixelCaption text={c.caption} highlight={c.highlight} width={860} />
      </div>
      {c.stat && <StatCard {...c.stat} f={f} start={Math.round(len * 0.35)} style={{ position: "absolute", left: 50, top: 860 }} />}
    </div>
  );
};

const AnatomyChapter = (sp: SceneProps) => (
  <>
    <AnatomyCard {...sp} />
    <Counter n={sp.index} total={sp.p.chapters.length} f={sp.f} />
  </>
);

/** A type-only beat: the title slams in big, word by word, the key under it, the block drifting and petals crossing. */
const TypeChapter = ({ p, index, f, len, frame }: SceneProps) => {
  const c = p.chapters[index - 1] as Extract<Chapter, { scene: "type" }>;
  const size = Array.from(c.title).length > 16 ? 120 : 150;
  const push = ease(f, 0, len);
  return (
    <>
      <Drift frame={frame} count={20} />
      <Counter n={index} total={p.chapters.length} f={f} />
      <div style={{ position: "absolute", left: LEFT, top: 560, width: 900, transformOrigin: "0 50%", transform: `scale(${1.12 - 0.12 * push}) translateY(${-30 * push}px)` }}>
        <div style={{ lineHeight: 0.98 }}>
          <Rise text={c.title} f={f} start={0} stagger={3} style={{ ...GROTESK, fontSize: size }} />
        </div>
        {c.key && (
          <div style={{ marginTop: 20, lineHeight: 1.1 }}>
            <Rise text={c.key} f={f} start={10} stagger={3} style={{ ...SERIF, fontSize: 84 }} />
          </div>
        )}
      </div>
    </>
  );
};

/** The typographic duo: the lead rises from `leadAt` (-1 = there from frame 0), the key from `keyAt`, then the strike. */
const Duo = ({ d, f, leadAt, keyAt, strikeAt, size, keySize }: { d: EditorialProps["hook"]; f: number; leadAt: number; keyAt: number; strikeAt: number; size: number; keySize: number }) => (
  <>
    <div style={{ lineHeight: 1.0 }}>
      <Rise text={d.lead} f={f} start={leadAt} style={{ ...GROTESK, fontSize: size }} struck={struckWords(d.lead, d.strike)} strikeAt={strikeAt} />
    </div>
    <div style={{ lineHeight: 1.05, marginTop: 10 }}>
      <Rise text={d.key} f={f} start={keyAt} style={{ ...SERIF, fontSize: keySize }} stagger={3} />
    </div>
  </>
);

/** The hook: readable from frame 0, moving from frame 0 (a push on the type, petals at depth crossing it). */
const Hook = ({ p, f, len, frame }: SceneProps) => {
  const size = Array.from(p.hook.lead).length > 26 ? 96 : 116;
  const push = Math.min(1, f / len);
  return (
    <>
      <Drift frame={frame + 60} count={24} />
      <div style={{ position: "absolute", left: LEFT, top: 290 }}>
        <Kicker text={p.kicker} f={f} />
      </div>
      <div style={{ position: "absolute", left: LEFT, top: 520, width: 900, transformOrigin: "0 30%", transform: `scale(${1 + 0.08 * push}) translateY(${-24 * push}px)` }}>
        <Duo d={p.hook} f={f} leadAt={-1} keyAt={HOOK_KEY_AT} strikeAt={HOOK_STRIKE_AT} size={size} keySize={150} />
      </div>
    </>
  );
};

const Payoff = ({ p, f, len, frame }: SceneProps) => {
  const size = Array.from(p.payoff.lead).length > 26 ? 84 : 100;
  const stage = stageOf(345 + linesOf(p.payoff.lead, size, 900) * size + 150 + 20, GROUND);
  return (
    <>
      <svg width={W} height={H} style={{ position: "absolute", inset: 0 }}>
        <g transform={cameraTransform(payoffCamera(f / len), stage)}>
          <Tree {...stage} frame={frame} bloom={1} gust={0.2 * Math.sin(f / 14)} petals={60} />
        </g>
      </svg>
      <HeaderShade />
      <div style={{ position: "absolute", left: LEFT, top: 300, width: 900 }}>
        <Duo d={p.payoff} f={f} leadAt={0} keyAt={10} strikeAt={22} size={size} keySize={130} />
      </div>
    </>
  );
};

const SceneView = (sp: SceneProps) => {
  const n = sp.p.chapters.length;
  if (sp.index === 0) return <Hook {...sp} />;
  if (sp.index === n + 1) return <Payoff {...sp} />;
  const c = sp.p.chapters[sp.index - 1];
  if (c.scene === "anatomy") return <AnatomyChapter {...sp} />;
  if (c.scene === "split") return <SplitChapter {...sp} />;
  if (c.scene === "type") return <TypeChapter {...sp} />;
  return <TreeChapter {...sp} />;
};

const isAnatomy = (p: EditorialProps, index: number) => index >= 1 && index <= p.chapters.length && p.chapters[index - 1].scene === "anatomy";

/** SFX cues (frame, sound, dB from the voice's level) for the whole film. */
const cuesOf = (p: EditorialProps, starts: number[], lens: number[], endStart: number) => {
  const cues: [number, SfxId, number, number?][] = [];
  p.chapters.forEach((c, i) => {
    const s = starts[i + 1];
    const len = lens[i + 1];
    cues.push([s - 3, "sfx-swish", -7]);
    if (c.scene === "tree") c.tags.forEach((_, k) => cues.push([s + Math.round(len * (0.3 + 0.14 * k)), "sfx-pop", -2]));
    if (c.scene === "anatomy" && c.then) cues.push([s + Math.round(len * 0.5), "sfx-pop", 0]);
    if ((c.scene === "tree" || c.scene === "anatomy") && c.stat) cues.push([s + Math.round(len * (c.scene === "anatomy" ? 0.35 : 0.3)), "sfx-pop", -2]);
  });
  cues.push([starts[p.chapters.length + 1] + 10, "sfx-chime", 0]);
  cues.push([endStart - 3, "sfx-swish", -6]);
  return cues;
};

export const Editorial = (props: EditorialProps) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const { timeline, endStart } = useMemo(() => timelineOf(props, fps), [props, fps]);
  const scenes = timeline.scenes.slice(0, props.chapters.length + 2);
  const index = Math.max(0, ...scenes.map((s, i) => (frame >= s.startFrame ? i : 0)));
  const lenOf = (i: number) => (i + 1 < scenes.length ? scenes[i + 1].startFrame : endStart) - scenes[i].startFrame;
  const sp = (i: number, at: number): SceneProps => ({ p: props, index: i, f: at - scenes[i].startFrame, len: lenOf(i), frame: at });
  const since = frame - scenes[index].startFrame;
  // The anatomy card slides up over the scene before it, and down off the scene after it.
  const cardIn = isAnatomy(props, index) && index > 0 && !isAnatomy(props, index - 1) && since < CARD_SLIDE;
  const cardOut = index > 0 && isAnatomy(props, index - 1) && !isAnatomy(props, index) && since < CARD_SLIDE;
  const slide = ease(since, 0, CARD_SLIDE);
  const chapterAt = index >= 1 && index <= props.chapters.length ? props.chapters[index - 1] : null;
  // Not over the anatomy card, nor over the petals close-up (the crown fills the frame there).
  const showScrub = index >= 1 && !isAnatomy(props, index) && !(chapterAt?.scene === "tree" && chapterAt.action === "petals");
  const range: [number, number] | undefined =
    chapterAt?.scene === "tree" && chapterAt.action === "wind" ? [(scenes[index].startFrame + GUST_RANGE[0] * lenOf(index)) / endStart, (scenes[index].startFrame + GUST_RANGE[1] * lenOf(index)) / endStart] : undefined;
  const cues = cuesOf(props, scenes.map((s) => s.startFrame), scenes.map((_, i) => lenOf(i)), endStart);
  const loop = loopFade(frame, timeline);
  const lines = spokenLines(props.voice);
  return (
    <AbsoluteFill style={{ background: BLACK }}>
      {frame < endStart ? (
        <>
          {cardIn ? (
            <>
              <SceneView {...sp(index - 1, scenes[index].startFrame - 1)} />
              <AbsoluteFill style={{ transform: `translateY(${(1 - slide) * 1800}px)` }}>
                <SceneView {...sp(index, frame)} />
              </AbsoluteFill>
            </>
          ) : (
            <SceneView {...sp(index, frame)} />
          )}
          {showScrub && <Scrubber p={frame / endStart} total_s={endStart / fps} range={range} opacity={ease(frame - scenes[1].startFrame, 0, 10)} />}
          {cardOut && (
            <AbsoluteFill style={{ transform: `translateY(${slide * 1800}px)` }}>
              <SceneView {...sp(index - 1, scenes[index].startFrame - 1)} />
            </AbsoluteFill>
          )}
        </>
      ) : (
        <Sequence from={endStart} layout="none">
          <EndCard style="editorial" tagline={props.outro} accent={props.accent} cameo={cameoOf(props)} address={props.address} pixelate={1} />
        </Sequence>
      )}
      {loop > 0 && (
        <AbsoluteFill style={{ opacity: loop, background: BLACK }}>
          <SceneView {...sp(0, 0)} />
        </AbsoluteFill>
      )}
      {cues.map(([at, id, db, speech], i) => (
        <Sfx key={i} id={id} at={at} db={db} speech={speech} lines={lines} />
      ))}
      <MusicBed id={props.music} lines={lines} />
      <SafeZoneGuide show={!!props.safeZone} />
      {props.voice?.audioSrc && <Html5Audio src={props.voice.audioSrc} />}
    </AbsoluteFill>
  );
};
