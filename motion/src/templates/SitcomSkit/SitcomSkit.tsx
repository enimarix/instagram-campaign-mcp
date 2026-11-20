// SitcomSkit (step 164): « Sitcom 3D absurde ». The troupe's Blender shots (a cut every 1-2 s,
// reaction close-ups, top-down, x10 and slow-mo, the punchline frozen: src/studio/sitcom.py) play
// under the hook slammed in from frame 0, bold karaoke captions of the narrator, the characters'
// own lines in speech bubbles (their own voices), the key fact as a big number, scene slates and
// cartoon foley, over a bouncy bed ducked under every voice. Ends on the sitcom end card.
import { useMemo } from "react";
import { AbsoluteFill, Html5Audio, Sequence, useCurrentFrame, useVideoConfig } from "remotion";
import { MusicBed } from "../../components/MusicBed";
import { SafeZoneGuide } from "../../components/SafeZoneGuide";
import { Sfx } from "../../components/Sfx";
import { EndCard } from "../../endcards/EndCard";
import { cast } from "./cast";
import { BigNumber, Bubble, Hook, Karaoke, numberText, Plate, Slate } from "./kit";
import { type Beat, HOOK_MIN_S, layoutOf, SFX_FILE, type SitcomProps } from "./schema";
import { easeOut, span } from "../../voxel/anim.ts";

const SLATE_S = 1.2;

/** A character's line, in its own voice (src/studio/sitcom.py), from the bubble's start. */
const SayVoice = ({ voice, from, frames }: { voice: string; from: number; frames: number }) => (
  <Sequence from={from} durationInFrames={frames} layout="none">
    <Html5Audio src={voice} />
  </Sequence>
);

export const SitcomSkit = (props: SitcomProps) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const layout = useMemo(() => layoutOf(props), [props]);
  const { parts, spoken, voiceParts, cardStart } = layout;
  const t = frame / fps;
  const at = (s: number) => Math.round(s * fps);
  const end = at(cardStart);
  const part = parts.find((x) => t < x.end_s) ?? parts[parts.length - 1];
  const scene = props.scenes[part.scene];
  const beat: Beat = scene.beats[part.beat];
  // the narrator's beat line on screen: the last one started, until the next one starts
  const beatsCount = props.scenes.reduce((k, x) => k + x.beats.length, 0);
  const narrated = spoken.filter((x) => x.line !== undefined && x.line > 0 && x.line <= beatsCount);
  const li = narrated.filter((x) => x.start_s <= t).length - 1;
  const line = li >= 0 && t < (narrated[li + 1]?.start_s ?? cardStart) ? narrated[li] : undefined;
  const say = spoken.find((x) => x.say && t >= x.start_s - 0.15 && t < x.end_s + 0.35);
  const beatParts = parts.filter((x) => x.scene === part.scene && x.beat === part.beat && x.part !== "hook");
  const beatStart = beatParts.length ? beatParts[0].start_s : 0;
  const beatEnd = beatParts.length ? beatParts[beatParts.length - 1].end_s : 0;
  const freeze = parts.find((x) => x.part === "freeze");
  const sceneStarts = props.scenes.map((_, i) => parts.find((x) => x.scene === i)?.start_s ?? 0);
  const voice = props.voice?.audioSrc;
  const speech = voice ? spoken : undefined;
  const hookOut = at(Math.max(HOOK_MIN_S, parts.find((x) => x.part !== "hook")?.start_s ?? HOOK_MIN_S));
  const n = beat.number;
  const zoom = freeze && t >= freeze.start_s ? 1 + 0.06 * easeOut(span(frame, at(freeze.start_s), 8)) : 1;
  const flash = freeze ? 1 - span(frame, at(freeze.start_s), 6) : 0;
  return (
    <AbsoluteFill style={{ background: "#1B1530" }}>
      {frame < end ? (
        <>
          <Plate src={props.plate} zoom={zoom} />
          {frame < hookOut && <Hook text={props.hook} f={frame} out={hookOut} />}
          {line && !(part.part === "say" && say) && part.part !== "freeze" && <Karaoke line={line.text} keyWord={line.line === undefined ? undefined : keyOf(props, line.line)} start={line.start_s} end={line.end_s} t={t} fps={fps} />}
          {n && part.part !== "hook" && t >= beatStart && (
            <BigNumber
              key={`n${part.scene}-${part.beat}`}
              text={numberText(n.from === undefined ? n.value : n.from + (n.value - n.from) * easeOut(span(t, beatStart + 0.2, Math.max(0.5, (beatEnd - beatStart) * 0.6))), n.decimals)}
              unit={n.unit}
              accent={props.accent}
              f={frame - at(beatStart)}
            />
          )}
          {say?.say && (
            <Bubble
              key={`b${say.say.scene}-${say.say.beat}`}
              name={nameOf(props, say.say.scene, say.say.beat)}
              text={say.text}
              f={frame - at(say.start_s - 0.15)}
              side={say.say.beat % 2 ? 1 : -1}
            />
          )}
          {props.scenes.map((s, i) =>
            s.label && t >= sceneStarts[i] && t < sceneStarts[i] + SLATE_S ? <Slate key={`s${i}`} text={s.label} f={frame - at(sceneStarts[i])} frames={at(SLATE_S)} /> : null,
          )}
          {flash > 0 && t >= (freeze?.start_s ?? Infinity) && <AbsoluteFill style={{ background: "#FFFFFF", opacity: 0.85 * flash }} />}
        </>
      ) : (
        <Sequence from={end} layout="none">
          <EndCard style="sitcom" tagline={props.outro} accent={props.accent} address={props.address} pixelate={1} />
        </Sequence>
      )}
      {/* foley: a whoosh into each new scene, the beats' own sounds, a pop on each bubble, a hit on the freeze */}
      {sceneStarts.slice(1).map((s, i) => (
        <Sfx key={`w${i}`} id="sfx-swish" at={at(s)} lines={speech} />
      ))}
      {props.scenes.flatMap((s, i) =>
        s.beats.map((b, j) => {
          const p = parts.find((x) => x.scene === i && x.beat === j && x.part === "line");
          return b.sfx && p ? <Sfx key={`f${i}-${j}`} id={SFX_FILE[b.sfx]} at={at(p.start_s)} lines={speech} /> : null;
        }),
      )}
      {spoken.filter((x) => x.say).map((x, i) => (
        <Sfx key={`p${i}`} id="sfx-pop" at={at(x.start_s - 0.15)} db={-4} lines={speech} />
      ))}
      {freeze && <Sfx id="sfx-hit" at={at(freeze.start_s)} lines={speech} />}
      <MusicBed id={props.music} lines={speech} />
      <SafeZoneGuide show={!!props.safeZone} />
      {voice &&
        voiceParts.map((v, i) => {
          const next = voiceParts[i + 1];
          return (
            <Sequence key={`v${i}`} from={at(v.at_s)} durationInFrames={next ? Math.max(1, at(next.audio_s - v.audio_s)) : undefined} layout="none">
              <Html5Audio src={voice} trimBefore={at(v.audio_s)} />
            </Sequence>
          );
        })}
      {spoken.map((x, i) => {
        if (!x.say) return null;
        const src = props.scenes[x.say.scene].beats[x.say.beat].say?.audioSrc;
        return src ? <SayVoice key={`c${i}`} voice={src} from={at(x.start_s)} frames={Math.max(1, at(x.end_s - x.start_s) + 6)} /> : null;
      })}
    </AbsoluteFill>
  );
};

/** The key word of narrator script line `i` (line 0 is the hook: none). */
const keyOf = (p: SitcomProps, i: number) => p.scenes.flatMap((s) => s.beats)[i - 1]?.key;

/** A bubble's name tag: the speaker's role in the skit, else the troupe's name for them. */
const nameOf = (p: SitcomProps, scene: number, beat: number) => {
  const who = p.scenes[scene].beats[beat].say?.who ?? "";
  return p.scenes[scene].cast.find((m) => m.who === who)?.role ?? cast[who] ?? who;
};
