// VoxelQuest (step 130): the first "3D 8-bit" story, in the owner's structure. Hook (big
// line on the light background while the kitchen set pops in), 1-2 problem beats (foods pop
// onto the worktop with their numbers), 1-2 app beats (the voxel phone fills its calorie
// ring, camera push-in), the payoff (the golem levels up: hop, flash, pop) and the animated
// voxel end card. One iso camera moves between the beats; text stays in the top of the safe
// area, the scene below it, so they never overlap.
import { type ReactNode, useMemo } from "react";
import { AbsoluteFill, Html5Audio, Sequence, useCurrentFrame, useVideoConfig } from "remotion";
import { assetById } from "../../assets";
import { brand, safeArea } from "../../brand";
import { MusicBed } from "../../components/MusicBed";
import { SafeZoneGuide } from "../../components/SafeZoneGuide";
import { EndCard } from "../../endcards/EndCard";
import { BACKGROUND } from "../../endcards/VoxelEndCard";
import { ACCENTS, type FormId } from "../../endcards/schema";
import { fonts } from "../../lib/font";
import { frenchSpaces } from "../../lib/french";
import { loopFade, type Scene, sceneAt } from "../../lib/timeline";
import { backOut, bob, easeInOut, easeOut, hop, lerpPose, type Pose, popIn, projectIso, span } from "../../voxel/anim.ts";
import type { Voxel } from "../../voxel/mesh.ts";
import { golem, KITCHEN_SPOT, KITCHEN_WIDE, kitchen, kitchenScale, phone, plate, PROPS } from "../../voxel/models.ts";
import { FORMS } from "../../voxel/palette.ts";
import { CameraRig, VoxelCanvas, VoxelMesh } from "../../voxel/Stage.tsx";
import { timelineOf, type VoxelQuestProps } from "./schema";

type Vec = [number, number, number];
type Beat = VoxelQuestProps["beats"][number];

// Models, built once per bundle.
const KITCHEN = kitchen().voxels();
const GOLEMS = Object.fromEntries(FORMS.map((f, i) => [f.id, golem(i + 1).voxels()])) as Record<FormId, Voxel[]>;
const FOODS = Object.fromEntries(Object.entries(PROPS).map(([id, make]) => [id, make().voxels()]));
/** Height of each food as a share of its largest side (where its label is pinned). */
const FOOD_HEIGHT = Object.fromEntries(
  Object.entries(FOODS).map(([id, v]) => {
    const size = [0, 1, 2].map((a) => Math.max(...v.map((c) => c[a] as number)) - Math.min(...v.map((c) => c[a] as number)) + 1);
    return [id, size[1] / Math.max(...size)];
  }),
);
const SCALE = kitchenScale("72.4").voxels();
const PLATE = plate().voxels();
/** The phone's ring in 8 steps (an 8-bit fill), 0 = empty. */
const PHONE_STEPS = 8;
const PHONES = Array.from({ length: PHONE_STEPS + 1 }, (_, i) => phone(i / PHONE_STEPS).voxels());


const RAD = Math.PI / 180;
const WORKTOP_Y = 11;
/** Food slots on the worktop for 1, 2 or 3 foods (x; z is the worktop's middle). */
const SLOTS: Record<number, number[]> = { 1: [9], 2: [4, 14.5], 3: [1.5, 9.5, 17.5] };
const FOOD_Z = -16;
/** Largest side of a food on the worktop, by how many share it. */
const FOOD_FIT: Record<number, number> = { 1: 14, 2: 12, 3: 10 };
/** Right of the golem on screen, a step toward the camera. */
const PHONE_AT: Vec = [KITCHEN_SPOT[0] + 11.3, 12, KITCHEN_SPOT[2] - 5.7];
/** The plate (hookProp plate): on the worktop, just right of the golem. */
const HOOK_PROP_AT: Vec = [0, WORKTOP_Y, -15];

// Camera shots, iso; targets put each shot's subject below the caption band.
const SHOTS = {
  hook: KITCHEN_WIDE,
  // Swings round to face the worktop: the foods stand in a row, their numbers side by side.
  problem: { ...KITCHEN_WIDE, azimuth: 20, elevation: 30, lens: 26, target: [5, 20, -10] },
  // A problem beat without foods: close on the golem and the hook's prop (still the same reading).
  close: { ...KITCHEN_WIDE, azimuth: 58, lens: 30, target: [KITCHEN_SPOT[0] + 2, 15, KITCHEN_SPOT[2] - 4] },
  app: { ...KITCHEN_WIDE, lens: 28, target: [PHONE_AT[0] - 1.5, PHONE_AT[1] + 3, PHONE_AT[2] - 1.5] },
  payoff: { ...KITCHEN_WIDE, lens: 22, target: [KITCHEN_SPOT[0] - 1.6, 13, KITCHEN_SPOT[2] - 1.6] },
} satisfies Record<string, Pose>;
/** Frames of the eased camera move into each beat. */
const MOVE = 16;
/** Frames before the end card when the payoff eases back to the wide shot (the card starts there). */
const SETTLE = 22;
/** Lens gain of the slow push over a beat. */
const DRIFT = 0.07;

/** When things happen inside a beat, in frames from its start (scaled down for short beats). */
const IN_BEAT = { food: 8, foodGap: 9, phone: 4, fill: 16, hop: 10, hopLength: 26 };

const TEXT_ACCENT = { ...ACCENTS, fat: "#B7862A", carbs: "#2E9E66" } as const;
const ink = brand.colors.light.ink;
const display = { fontFamily: `"${fonts.display}", sans-serif`, fontWeight: fonts.displayWeight, letterSpacing: "-0.035em" } as const;

/** The largest size from `sizes` whose greedy word wrap fits the box (Inter Tight 900 ≈ 0.5 em a character). */
const fitSize = (text: string, width: number, height: number, sizes: number[], lineHeight = 1.06) => {
  const words = text.split(/\s+/);
  for (const size of sizes) {
    const cols = Math.floor(width / (size * 0.5));
    let lines = 1;
    let used = 0;
    for (const w of words) {
      const n = Array.from(w).length;
      if (used && used + 1 + n > cols) {
        lines++;
        used = n;
      } else used += used ? 1 + n : n;
    }
    if (lines * size * lineHeight <= height && words.every((w) => Array.from(w).length <= cols)) return size;
  }
  return sizes[sizes.length - 1];
};

/** The line with its numbers ("308 kcal", "1,6 g", "21 h") in the accent colour. */
const Highlighted = ({ text, color }: { text: string; color: string }) => {
  const parts = frenchSpaces(text).split(/(\d[\d   ,.]*(?:\s?(?:kcal|kg|g|h|%))?)/);
  return (
    <>
      {parts.map((part, i) => (i % 2 ? <span key={i} style={{ color }}>{part.replace(/ (?=\S)/g, " ")}</span> : part))}
    </>
  );
};

/** Fade and rise in from `start`, fade out over the last frames before `end`. */
const inOut = (frame: number, start: number, end: number, length = 8) => {
  const a = easeOut(span(frame, start, length));
  const b = 1 - span(frame, end - 6, 6);
  return { opacity: Math.min(a, b), transform: `translateY(${(1 - a) * 30}px)` };
};

/** Hook text and beat captions: one at a time in the top of the safe area. */
const Caption = ({ scene, color, frame }: { scene: Scene; color: string; frame: number }) => {
  const area = safeArea();
  const hook = scene.index === 0;
  const box = { left: area.left, width: area.width, top: area.top + 10, height: hook ? 330 : 330 };
  const size = fitSize(scene.text, box.width - (hook ? 20 : 96), box.height - (hook ? 0 : 60), hook ? [128, 116, 104, 96, 88, 80, 72] : [84, 76, 68, 62, 56]);
  // The hook is whole from frame 0 (the cover); later lines fade in.
  const style = hook ? { opacity: 1 - span(frame, scene.endFrame - 6, 6) } : inOut(frame, scene.startFrame, scene.endFrame);
  return (
    <div style={{ position: "absolute", ...box, display: "flex", justifyContent: "center", alignItems: hook ? "center" : "flex-start", ...style }}>
      <div
        style={{
          ...display,
          fontSize: size,
          lineHeight: 1.06,
          color: ink,
          textAlign: "center",
          textWrap: "balance",
          ...(hook
            ? {}
            : { background: "#FFFFFF", borderRadius: 34, padding: "26px 40px 30px", boxShadow: "0 14px 36px rgba(17, 24, 39, 0.12)" }),
        }}
      >
        <Highlighted text={scene.text} color={color} />
      </div>
    </div>
  );
};

/** A number pinned above a model: a pill in the macro's colour with a small pointer. */
const Label = ({ at, text, color, frame, start, size = 42 }: { at: [number, number]; text: string; color: string; frame: number; start: number; size?: number }) => {
  const s = frame < start ? 0 : backOut(span(frame, start, 10), 0.3);
  const dark = color === ACCENTS.fat;
  return (
    <div style={{ position: "absolute", left: at[0], top: at[1], transform: `translate(-50%, -100%) scale(${s})`, transformOrigin: "50% 100%" }}>
      <div
        style={{
          ...display,
          fontSize: size,
          letterSpacing: "-0.02em",
          whiteSpace: "nowrap",
          color: dark ? ink : "#FFFFFF",
          background: color,
          borderRadius: 999,
          padding: "10px 26px 12px",
          boxShadow: "0 8px 20px rgba(17, 24, 39, 0.18)",
        }}
      >
        {frenchSpaces(text)}
      </div>
      <div style={{ width: 0, height: 0, margin: "0 auto", borderLeft: "12px solid transparent", borderRight: "12px solid transparent", borderTop: `14px solid ${color}` }} />
    </div>
  );
};

type Story = {
  props: VoxelQuestProps;
  scenes: Scene[];
  endStart: number;
  /** Frame of the level-up flash. */
  flash: number;
};

/** Which camera shot a beat uses. */
const shotOf = (b?: Beat): keyof typeof SHOTS => (!b ? "payoff" : b.kind === "problem" && !b.foods ? "close" : b.kind);

const beatOf = (p: VoxelQuestProps, scene?: Scene): Beat | undefined =>
  scene && scene.index >= 1 && scene.index <= p.beats.length ? p.beats[scene.index - 1] : undefined;

/** Frames into the beat, with its in-beat times scaled when the beat is short (a fast voice). */
const beatClock = (frame: number, scene: Scene, fps: number) => {
  const length = scene.endFrame - scene.startFrame;
  const k = Math.min(1, length / (3.4 * fps));
  return { t: frame - scene.startFrame, k, length };
};

const cameraAt = (frame: number, story: Story): Pose => {
  const { props, scenes, endStart } = story;
  const shot = (s: Scene) => (s.index === 0 ? SHOTS.hook : SHOTS[shotOf(beatOf(props, s))]);
  const i = scenes.findIndex((s) => frame >= s.startFrame && frame < s.endFrame);
  const scene = scenes[i === -1 ? scenes.length - 1 : i];
  if (frame >= endStart - SETTLE) {
    const from = shot(scenes[Math.min(props.beats.length, scenes.length - 1)]);
    return lerpPose(from, KITCHEN_WIDE, easeInOut(span(frame, endStart - SETTLE, SETTLE)));
  }
  if (scene.index === 0) return lerpPose({ ...KITCHEN_WIDE, lens: KITCHEN_WIDE.lens * 0.9 }, SHOTS.hook, easeOut(span(frame, 0, scene.endFrame)));
  const prev = shot(scenes[scene.index - 1]);
  // After the move in, a slow push keeps the picture alive through the beat.
  const to = shot(scene);
  const drift = { ...to, lens: to.lens * (1 + DRIFT * span(frame, scene.startFrame + MOVE, scene.endFrame - scene.startFrame - MOVE)) };
  return lerpPose(prev, drift, easeInOut(span(frame, scene.startFrame, MOVE)));
};

/** Everything in the 3D set for this frame. */
const Set3D = ({ frame, story, pose }: { frame: number; story: Story; pose: Pose }) => {
  const { fps } = useVideoConfig();
  const { props, scenes, flash } = story;
  const scene = sceneAt(scenes, frame) ?? scenes[scenes.length - 1];
  const beat = beatOf(props, scene);
  const kind = scene.index === 0 ? "hook" : (beat?.kind ?? "payoff");
  const clock = beatClock(frame, scene, fps);
  // Room and golem pop in under the hook text in the first half second.
  const room = popIn(frame, 0, 12, 0.08);
  const form: FormId = frame >= flash ? (kind === "payoff" ? (beat?.form ?? props.toForm) : props.toForm) : (beat?.form ?? props.fromForm);
  // The hook's prop shows in the hook and again in a problem beat without foods (nothing changed).
  const showProp = kind === "hook" || (kind === "problem" && !beat?.foods);
  const onScale = props.hookProp === "scale" && showProp;
  // Golem: faces the camera, turns toward the worktop in problem beats, toward the phone in app beats.
  const turn = kind === "problem" && beat?.foods ? 0.7 : kind === "app" ? 0.6 : props.hookProp === "plate" && showProp ? 0.5 : 0;
  const yaw = pose.azimuth * RAD + turn * easeInOut(span(frame, scene.startFrame, MOVE));
  const shake = kind === "problem" && clock.t > 40 * clock.k ? Math.sin((clock.t - 40 * clock.k) / 2.2) * 0.1 * (1 - span(clock.t, 40 * clock.k, 24)) : 0;
  const jump = kind === "payoff" ? hop(clock.t, IN_BEAT.hop * clock.k, IN_BEAT.hopLength, 7) : hop(frame, 4, 14, 3);
  const pop = frame >= flash ? backOut(span(frame, flash, 12), 0.6) : 1;
  const enter = popIn(frame, 3, 12, 0.2);
  const golemScale = jump.scale.map((v) => v * enter * pop) as Vec;
  return (
    <>
      <CameraRig kind="iso" pose={pose} />
      <group scale={room}>
        <VoxelMesh voxels={KITCHEN} build={{ center: false }} />
        {onScale && (
          <VoxelMesh voxels={SCALE} position={[KITCHEN_SPOT[0], 0, KITCHEN_SPOT[2]]} rotation={[0, KITCHEN_WIDE.azimuth * RAD, 0]} />
        )}
        {props.hookProp === "plate" && showProp && <VoxelMesh voxels={PLATE} position={HOOK_PROP_AT} />}
        <group
          position={[KITCHEN_SPOT[0], (onScale ? 3 : 0) + jump.y + bob(frame, 64, 0.15), KITCHEN_SPOT[2]]}
          rotation={[onScale ? 0.12 : 0, yaw + shake, 0]}
          scale={golemScale}
        >
          {/* Sit the model's centre back on the scale (feet behind the display). */}
          <VoxelMesh voxels={GOLEMS[form]} position={onScale ? [0, 0, -3] : [0, 0, 0]} />
        </group>
        {kind === "problem" && beat?.foods?.map((f, i) => {
          const x = SLOTS[beat.foods!.length][i];
          const s = popIn(clock.t, (IN_BEAT.food + i * IN_BEAT.foodGap) * clock.k, 12, 0.25) * (1 - span(frame, scene.endFrame - 5, 5));
          return (
            <group key={i} position={[x, WORKTOP_Y, FOOD_Z]} scale={s} rotation={[0, pose.azimuth * RAD - 0.25 + bob(frame, 90, 0.08, i * 20), 0]}>
              <VoxelMesh voxels={FOODS[f.prop]} fit={FOOD_FIT[beat.foods!.length]} />
            </group>
          );
        })}
        {kind === "app" && (
          <group
            position={[PHONE_AT[0], PHONE_AT[1] + bob(frame, 70, 0.3), PHONE_AT[2]]}
            rotation={[-pose.elevation * RAD * 0.6, pose.azimuth * RAD, 0, "YXZ"]}
            scale={popIn(clock.t, IN_BEAT.phone, 12, 0.2) * 0.9}
          >
            <VoxelMesh
              voxels={PHONES[Math.min(PHONE_STEPS, Math.max(0, Math.floor(((clock.t - IN_BEAT.fill * clock.k) / (clock.length * 0.55)) * PHONE_STEPS)))]}
              position={[0, -12, 0]}
            />
          </group>
        )}
      </group>
    </>
  );
};

/** 2D overlays pinned to the set: food numbers, the level pill. */
const Pins = ({ frame, story, pose }: { frame: number; story: Story; pose: Pose }) => {
  const { fps, width, height } = useVideoConfig();
  const { props, scenes, flash } = story;
  const scene = sceneAt(scenes, frame);
  const beat = beatOf(props, scene);
  const out: ReactNode[] = [];
  if (scene && beat?.kind === "problem" && beat.foods) {
    const clock = beatClock(frame, scene, fps);
    const fade = 1 - span(frame, scene.endFrame - 5, 5);
    beat.foods.forEach((f, i) => {
      const x = SLOTS[beat.foods!.length][i];
      // Odd labels sit higher: neighbours never overlap, however tight the row.
      const top = WORKTOP_Y + FOOD_HEIGHT[f.prop] * FOOD_FIT[beat.foods!.length] + 2;
      const at = projectIso(pose, [x, top, FOOD_Z], width, height);
      at[1] -= (i % 2) * 74;
      out.push(
        <div key={`f${i}`} style={{ opacity: fade }}>
          <Label at={at} text={f.label} color={ACCENTS[f.macro]} frame={clock.t} start={(IN_BEAT.food + i * IN_BEAT.foodGap) * clock.k + 4} />
        </div>,
      );
    });
  }
  if (scene && beat?.kind === "payoff" && frame >= flash) {
    const form = FORMS.findIndex((f) => f.id === (beat.form ?? props.toForm));
    const at = projectIso(pose, [KITCHEN_SPOT[0], 25, KITCHEN_SPOT[2]], width, height);
    out.push(
      <div key="level" style={{ opacity: 1 - span(frame, scene.endFrame - 5, 5) }}>
        <Label at={at} text={`Niveau ${form + 1} · ${FORMS[form].name}`} color={ACCENTS.brand} frame={frame} start={flash + 4} size={54} />
      </div>,
    );
  }
  return <>{out}</>;
};

const Sfx = ({ at, id, volume = 0.6 }: { at: number; id: "sfx-pop" | "sfx-chime"; volume?: number }) => (
  <Sequence from={Math.round(at)} durationInFrames={45} layout="none">
    <Html5Audio src={assetById(id).src} volume={volume} />
  </Sequence>
);

export const VoxelQuest = (props: VoxelQuestProps) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const { timeline, endStart } = useMemo(() => timelineOf(props, fps), [props, fps]);
  const scenes = timeline.scenes;
  const payoff = scenes[props.beats.length];
  const flash = payoff.startFrame + Math.round((IN_BEAT.hop + IN_BEAT.hopLength * 0.5) * beatClock(payoff.startFrame, payoff, fps).k);
  const story: Story = { props, scenes, endStart, flash };
  const accent = TEXT_ACCENT[props.accent];
  const pose = cameraAt(Math.min(frame, endStart - 1), story);
  const scene = sceneAt(scenes, frame);
  const flashOpacity = frame >= flash ? 0.85 * (1 - span(frame, flash, 9)) : 0;
  // Sound cues: food pops, the phone's ring completing, the level-up chime.
  const cues: { at: number; id: "sfx-pop" | "sfx-chime" }[] = [];
  props.beats.forEach((b, i) => {
    const s = scenes[i + 1];
    const { k, length } = beatClock(s.startFrame, s, fps);
    b.foods?.forEach((_, j) => cues.push({ at: s.startFrame + (IN_BEAT.food + j * IN_BEAT.foodGap) * k, id: "sfx-pop" }));
    if (b.kind === "app") cues.push({ at: s.startFrame + IN_BEAT.phone, id: "sfx-pop" }, { at: s.startFrame + IN_BEAT.fill * k + length * 0.55, id: "sfx-pop" });
  });
  cues.push({ at: flash, id: "sfx-chime" });
  const loop = loopFade(frame, timeline);
  return (
    <AbsoluteFill style={{ background: BACKGROUND }}>
      {frame < endStart ? (
        <>
          <VoxelCanvas width={width} height={height} pixelate={props.pixelate} background={BACKGROUND} shadowExtent={40}>
            <Set3D frame={frame} story={story} pose={pose} />
          </VoxelCanvas>
          <Pins frame={frame} story={story} pose={pose} />
          {scene && scene.index <= props.beats.length && <Caption scene={scene} color={accent} frame={frame} />}
          <AbsoluteFill style={{ background: "#FFFFFF", opacity: flashOpacity }} />
        </>
      ) : (
        <Sequence from={endStart} layout="none">
          <EndCard
            style="voxel"
            tagline={props.outro}
            accent={props.accent}
            cameo={props.cameo ?? props.toForm}
            address={props.address}
            pixelate={props.pixelate}
          />
        </Sequence>
      )}
      {loop > 0 && (
        // Loop on: frame 0's picture (background + hook) comes back over the last frames.
        <AbsoluteFill style={{ background: BACKGROUND, opacity: loop }}>
          <Caption scene={scenes[0]} color={accent} frame={0} />
        </AbsoluteFill>
      )}
      {cues.map((c, i) => (
        <Sfx key={i} at={c.at} id={c.id} />
      ))}
      <Sfx at={endStart + 54} id="sfx-pop" volume={0.45} />
      <MusicBed id={props.music} />
      <SafeZoneGuide show={!!props.safeZone} />
      {props.voice?.audioSrc && <Html5Audio src={props.voice.audioSrc} />}
    </AbsoluteFill>
  );
};
