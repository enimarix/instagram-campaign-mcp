// The cinema style's end card (step 143): the story's pixel set, darkened, rain still falling;
// a beam swings in from the bottom left and lands on the mB tile (the tile catches the light
// and glows), then the brand stack plays as on the clean card: wordmark rising letter by
// letter, the tagline, the « 7 jours gratuits » pill, macrobody.fr. Cameo = the set.
// Settles by SETTLE_S.cinema, then holds.
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { Stage } from "../cinema/Stage";
import { SETS, type SceneId } from "../cinema/scenes.ts";
import { easeOut, span } from "../voxel/anim.ts";
import { CardStack } from "./CleanEndCard";
import { type CardProps, cameoOf } from "./schema.ts";

/** Where the beam comes from (screen cells, off the bottom left) and the tile's centre it lands on. */
const ORIGIN = [-8, 330] as const;
const TILE = [90, 76] as const;
const AIM = Math.atan2(TILE[1] - ORIGIN[1], TILE[0] - ORIGIN[0]);

export const CinemaEndCard = ({ tagline, accent, address, cameo }: Omit<CardProps, "pixelate">) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const scene = cameoOf("cinema", cameo) as SceneId | "none";
  const set: SceneId = scene === "none" ? "window" : scene;
  const swing = easeOut(span(frame, 0, Math.round(0.8 * fps)));
  const landed = easeOut(span(frame, Math.round(0.6 * fps), Math.round(0.5 * fps)));
  const { view, to } = SETS[set].card;
  return (
    <AbsoluteFill style={{ background: "#07081A", overflow: "hidden" }}>
      <Stage
        scene={set}
        view={view}
        t={20 + frame / fps}
        cam={{ zoom: to[0], fx: to[1], fy: to[2], dx: 0, dy: 0 }}
        beam={0.45}
        sweep={0}
        flash={false}
        dim={0.9}
        open={1}
        extra={{ x: ORIGIN[0], y: ORIGIN[1], angle: AIM - 0.6 * (1 - swing), spread: 0.1, length: 300, power: Math.min(1, swing * 1.4) }}
      />
      {/* The tile catches the light. */}
      <div style={{ position: "absolute", left: 540 - 300, top: 455 - 300, width: 600, height: 600, borderRadius: "50%", background: "radial-gradient(circle, rgba(255, 181, 71, 0.55) 0%, rgba(255, 181, 71, 0.18) 40%, rgba(255, 181, 71, 0) 70%)", opacity: landed }} />
      <CardStack tagline={tagline} accent={accent} address={address} dark />
    </AbsoluteFill>
  );
};
