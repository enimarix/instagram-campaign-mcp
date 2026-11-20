// VoxelQuest (step 130): the first "3D 8-bit" story, in the owner's structure. Hook (big
// line on the light background while the kitchen set pops in), 1-2 problem beats (foods pop
// onto the worktop with their numbers), 1-2 app beats (the voxel phone fills its calorie
// ring, camera push-in), the payoff (the golem levels up: hop, flash, pop) and the animated
// voxel end card. One iso camera moves between the beats; text stays in the top of the safe
// area, the scene below it, so they never overlap.
import { type ReactNode, useMemo } from "react";
import { AbsoluteFill, Html5Audio, Sequence, useCurrentFrame, useVideoConfig } from "remotion";
import { brand, safeArea } from "../../brand";
import { MusicBed } from "../../components/MusicBed";
import { SafeZoneGuide } from "../../components/SafeZoneGuide";
import { Sfx } from "../../components/Sfx";
import { EndCard } from "../../endcards/EndCard";
import { BACKGROUND } from "../../endcards/VoxelEndCard";
import { ACCENTS, type FormId, TEXT_ACCENT } from "../../endcards/schema";
import { spokenLines } from "../../lib/duck";
import { fonts } from "../../lib/font";
import { frenchSpaces } from "../../lib/french";
import { loopFade, type Scene, sceneAt } from "../../lib/timeline";
import { backOut, bob, easeInOut, easeOut, hop, type Pose, popIn, projectIso, span } from "../../voxel/anim.ts";
import type { Voxel } from "../../voxel/mesh.ts";
import { golem, KITCHEN_SPOT, KITCHEN_WIDE, kitchen, kitchenScale, phone, PHONE_NUMBER, plate, PROPS } from "../../voxel/models.ts";
import { FORMS } from "../../voxel/palette.ts";
import { CameraRig, VoxelCanvas, VoxelMesh } from "../../voxel/Stage.tsx";
import {
  beatClock,
  beatOf,
  before,
  cameraAt,
  countUp,
  flashFrame,
  FOOD_FIT,
  FOOD_HEIGHT,
  FOOD_Z,
  HOOK_PROP_AT,
  IN_BEAT,
  MOVE,
  PHONE_AT,
  PHONE_CENTER,
  PHONE_SCALE,
  phonePoint,
  PILL_Y,
  reached,
  SCALE_LIFT,
  SLOTS,
  type Vec,
  WORKTOP_Y,
} from "./layout";
import { timelineOf, type VoxelQuestProps } from "./schema";

// Models, built once per bundle.
const KITCHEN = kitchen().voxels();
const GOLEMS = Object.fromEntries(FORMS.map((f, i) => [f.id, golem(i + 1).voxels()])) as Record<FormId, Voxel[]>;
const FOODS = Object.fromEntries(Object.entries(PROPS).map(([id, make]) => [id, make().voxels()]));
const SCALE = kitchenScale("72.4").voxels();
const PLATE = plate().voxels();
/** The phone's ring in 8 steps (an 8-bit fill), 0 = empty. */
const PHONE_STEPS = 8;
const PHONES = Array.from({ length: PHONE_STEPS + 1 }, (_, i) => phone(i / PHONE_STEPS).voxels());

const RAD = Math.PI / 180;
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

/** The line with its numbers ("308 kcal", "1,6 g", "21 h") in the accent colour, counted up to `progress`. */
const Highlighted = ({ text, color, progress = 1 }: { text: string; color: string; progress?: number }) => {
  const parts = frenchSpaces(text).split(/(\d[\d\u00a0\u202f ,.]*(?:\s?(?:kcal|kg|g|h|%)\b)?)/);
  return (
    <>
      {parts.map((part, i) => (i % 2 ? <span key={i} style={{ color }}>{countUp(part, progress).replace(/ (?=\S)/g, "\u00a0")}</span> : part))}
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
  const box = { left: area.left, width: area.width, top: area.top + 10, height: 330 };
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
        <Highlighted text={scene.text} color={color} progress={hook ? 1 : easeOut(span(frame, scene.startFrame + 4, 20))} />
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

/** Which of the phone's 9 ring steps shows `t` frames into an app beat. */
const phoneStep = (t: number, k: number, length: number) =>
  Math.min(PHONE_STEPS, Math.max(0, Math.floor(((t - IN_BEAT.fill * k) / (length * 0.55)) * PHONE_STEPS)));

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
  const form: FormId = frame >= flash ? reached(props) : before(props, beat);
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
          position={[KITCHEN_SPOT[0], (onScale ? SCALE_LIFT : 0) + jump.y + bob(frame, 64, 0.15), KITCHEN_SPOT[2]]}
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
            scale={popIn(clock.t, IN_BEAT.phone, 12, 0.2) * PHONE_SCALE}
          >
            <VoxelMesh voxels={PHONES[phoneStep(clock.t, clock.k, clock.length)]} position={[0, -PHONE_CENTER, 0]} build={{ center: false }} />
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
      at[1] -= (i % 2) * 92;
      out.push(
        <div key={`f${i}`} style={{ opacity: fade }}>
          <Label at={at} text={f.label} color={ACCENTS[f.macro]} frame={clock.t} start={(IN_BEAT.food + i * IN_BEAT.foodGap) * clock.k + 4} />
        </div>,
      );
    });
  }
  if (scene && beat?.kind === "app") {
    const clock = beatClock(frame, scene, fps);
    const fill = phoneStep(clock.t, clock.k, clock.length) / PHONE_STEPS;
    const [x, y] = projectIso(pose, phonePoint(pose, [PHONE_NUMBER[0] + 0.5, PHONE_NUMBER[1] + 0.5, PHONE_NUMBER[2] + 1], bob(frame, 70, 0.3)), width, height);
    const appear = popIn(clock.t, IN_BEAT.phone + 4, 12, 0.2);
    const text = frenchSpaces(countUp(beat.value ?? "100 %", fill));
    // As big as the screen's width allows (14 cubes, Inter Tight 900 about 0.52 em a character).
    const size = Math.round(Math.min(pose.lens * PHONE_SCALE * 5, (14 * PHONE_SCALE * pose.lens * 0.9) / (Array.from(text).length * 0.52)));
    out.push(
      <div
        key="value"
        style={{
          position: "absolute",
          left: x,
          top: y,
          transform: `translate(-50%, -50%) scale(${appear})`,
          ...display,
          fontSize: size,
          lineHeight: 1,
          whiteSpace: "nowrap",
          textAlign: "center",
          color: ink,
          opacity: 1 - span(frame, scene.endFrame - 5, 5),
        }}
      >
        {text}
      </div>,
    );
  }
  if (scene && beat?.kind === "payoff" && frame >= flash) {
    const form = FORMS.findIndex((f) => f.id === reached(props));
    const at = projectIso(pose, [KITCHEN_SPOT[0], PILL_Y, KITCHEN_SPOT[2]], width, height);
    out.push(
      <div key="level" style={{ opacity: 1 - span(frame, scene.endFrame - 5, 5) }}>
        <Label at={at} text={`Niveau ${form + 1} · ${FORMS[form].name}`} color={ACCENTS.brand} frame={frame} start={flash + 4} size={54} />
      </div>,
    );
  }
  return <>{out}</>;
};

export const VoxelQuest = (props: VoxelQuestProps) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const { timeline, endStart } = useMemo(() => timelineOf(props, fps), [props, fps]);
  const scenes = timeline.scenes;
  const flash = flashFrame(scenes[props.beats.length], fps);
  const story: Story = { props, scenes, endStart, flash };
  const accent = TEXT_ACCENT[props.accent];
  const pose = cameraAt(Math.min(frame, endStart - 1), props, scenes, endStart, fps);
  const scene = sceneAt(scenes, frame);
  const flashOpacity = frame >= flash ? 0.85 * (1 - span(frame, flash, 9)) : 0;
  // Sound cues: food pops, the phone's ring completing, the level-up chime.
  const cues: { at: number; id: "sfx-pop" | "sfx-chime"; db?: number }[] = [];
  props.beats.forEach((b, i) => {
    const s = scenes[i + 1];
    const { k, length } = beatClock(s.startFrame, s, fps);
    b.foods?.forEach((_, j) => cues.push({ at: s.startFrame + (IN_BEAT.food + j * IN_BEAT.foodGap) * k, id: "sfx-pop", db: -2 }));
    if (b.kind === "app") cues.push({ at: s.startFrame + IN_BEAT.phone, id: "sfx-pop", db: -2 }, { at: s.startFrame + IN_BEAT.fill * k + length * 0.55, id: "sfx-pop", db: -2 });
  });
  cues.push({ at: flash, id: "sfx-chime" });
  const loop = loopFade(frame, timeline);
  const lines = spokenLines(props.voice);
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
            cameo={props.cameo ?? reached(props)}
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
        <Sfx key={i} at={c.at} id={c.id} db={c.db} lines={lines} />
      ))}
      <MusicBed id={props.music} lines={lines} />
      <SafeZoneGuide show={!!props.safeZone} />
      {props.voice?.audioSrc && <Html5Audio src={props.voice.audioSrc} />}
    </AbsoluteFill>
  );
};
