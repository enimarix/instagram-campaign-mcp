// The voxel style's end card (step 130), animated motion design: from the kitchen's wide
// shot the camera cranes up to a podium (a round of the kitchen floor, ringed in the topic's
// accent) where the mB tile assembles from falling cubes (staggered, a little bounce, soft
// shadow); the wordmark reveals letter by letter, the tagline rises, the « 7 jours gratuits »
// pill pops, macrobody.fr fades up; the cameo hops in and waves. The kitchen stays below as
// the backdrop. Plays from its own frame 0 (VoxelQuest puts it in a <Sequence>); settles by
// about 2.2 s.
import { AbsoluteFill, Html5Audio, interpolate, Sequence, useCurrentFrame, useVideoConfig } from "remotion";
import { assetById } from "../assets";
import { brand, safeArea } from "../brand";
import { fonts } from "../lib/font";
import { frenchSpaces } from "../lib/french";
import { backOut, bob, easeInOut, easeOut, hop, type Move, poseAt, type Pose, popIn, span } from "../voxel/anim.ts";
import { cellNoise, VoxelGrid } from "../voxel/mesh.ts";
import { golem, KITCHEN_SPOT, KITCHEN_WIDE, kitchen, mbTile, PROPS } from "../voxel/models.ts";
import { FORMS } from "../voxel/palette.ts";
import { CameraRig, VoxelCanvas, VoxelCubes, VoxelMesh } from "../voxel/Stage.tsx";
import { ACCENTS, type Accent, type CardProps, cameoOf, cardVolume, DEFAULT_TAGLINE } from "./schema.ts";

/** The kitchen sits this far below the podium: the crane up leaves it as the backdrop. */
const KITCHEN_Y = -110;
const KITCHEN = kitchen().voxels();
const TILE = mbTile().voxels();
const GOLEMS = Object.fromEntries(FORMS.map((f, i) => [f.id, golem(i + 1).voxels()]));
const FOODS = Object.fromEntries(Object.entries(PROPS).map(([id, make]) => [id, make().voxels()]));

/** Podium: kitchen floor tiles in a disc on a plinth, an accent ring round the top. */
const podium = (accent: Accent) => {
  const ring = accent === "brand" ? "emerald" : accent;
  return new VoxelGrid()
    .cylinder(0, 0, -3, -3, 23.5, "plinth")
    .cylinder(0, 0, -2, -1, 23, (x, _y, z) => (Math.hypot(x, z) > 21.2 ? ring : (Math.floor(x / 4) + Math.floor(z / 4)) % 2 ? "floorA" : "floorB"))
    .repaint((x, y, z, c) => (y === -1 && c !== ring && cellNoise(x, z, 3) < 0.04 ? "plinth" : null))
    .voxels();
};
const PODIUMS = Object.fromEntries(Object.keys(ACCENTS).map((a) => [a, podium(a as Accent)])) as Record<Accent, ReturnType<typeof podium>>;

/** Faces the iso camera (azimuth 45°) and leans back a little: reads face-on, still 3D. */
const TILE_TURN: [number, number, number, "YXZ"] = [-0.18, Math.PI / 4, 0, "YXZ"];
/** Cameo spot on the podium: to the tile's right on screen, a step toward the camera. */
const CAMEO_AT: [number, number, number] = [16, 0, -12];

const START_POSE: Pose = { ...KITCHEN_WIDE, target: [KITCHEN_WIDE.target[0], KITCHEN_WIDE.target[1] + KITCHEN_Y, KITCHEN_WIDE.target[2]] };
const END_POSE: Pose = { ...KITCHEN_WIDE, target: [0, -29, 0], lens: 13.5 };
const MOVE: Move = { from: START_POSE, to: END_POSE, start: 0, duration: 34 };

/** Frames (from the card's start) at which each piece comes in. */
const AT = { leave: 4, podium: 6, cubes: 12, letters: 32, cameo: 30, word: 34, tagline: 48, pill: 54, url: 62 };
const DROP = 13; // frames a cube takes to fall and bounce
const FALL = 18; // voxels it falls

/** One cube's fall: quadratic drop to rest at 70 %, then a small bounce. */
const drop = (frame: number, start: number) => {
  if (frame < start) return { dy: FALL, scale: 0 };
  const t = span(frame, start, DROP);
  const dy = t < 0.7 ? FALL * (1 - (t / 0.7) ** 2) : 0.8 * Math.sin((Math.PI * (t - 0.7)) / 0.3);
  return { dy, scale: 1 };
};

// Stagger: the slab builds up row by row from the bottom (sweeping left to right), then the
// white letters land on it.
const START = TILE.map(([x, y, z]) => (z > 0 ? AT.letters + (x + 10) * 0.3 + (25 - y) * 0.1 : AT.cubes + y * 0.7 + (x + 13) * 0.16));

/** The light background the voxel style floats on (brand light, a breath of mint at the bottom). */
export const BACKGROUND = `linear-gradient(180deg, ${brand.colors.light.bg} 0%, #EEF4F2 60%, #DDEFE7 100%)`;

const ink = brand.colors.light.ink;
const muted = brand.colors.light.muted;
const display = { fontFamily: `"${fonts.display}", sans-serif`, fontWeight: fonts.displayWeight, letterSpacing: "-0.04em" };

const fade = (frame: number, start: number, length = 10) => ({
  opacity: interpolate(frame, [start, start + length], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }),
  transform: `translateY(${(1 - easeOut(span(frame, start, length))) * 36}px)`,
});

export const VoxelEndCard = ({ tagline, accent, cameo: asked, address, pixelate }: CardProps) => {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();
  const area = safeArea();
  const color = ACCENTS[accent];
  const cameo = cameoOf("voxel", asked);
  const isGolem = cameo in GOLEMS;
  const cameoVoxels = isGolem ? GOLEMS[cameo] : FOODS[cameo];
  const arrive = hop(frame, AT.cameo, 18, 5);
  const wave = frame > AT.cameo + 18 ? Math.sin((frame - AT.cameo - 18) / 4) * 0.14 : 0;
  const pill = frame < AT.pill ? 0 : backOut(span(frame, AT.pill, 12), 0.35);
  const line = frenchSpaces(tagline ?? DEFAULT_TAGLINE[address]);
  return (
    <AbsoluteFill>
      <VoxelCanvas width={width} height={height} pixelate={pixelate} background={BACKGROUND} shadowExtent={44}>
        <CameraRig kind="iso" pose={poseAt(frame, MOVE)} />
        <group position={[0, KITCHEN_Y, 0]}>
          <VoxelMesh voxels={KITCHEN} build={{ center: false }} />
          {/* The story's golem where the story left it (the wide shot the card starts on); it
              vanishes as the camera rises and the cameo hops onto the podium: one golem at a time. */}
          {isGolem && frame < AT.leave + 8 && (
            <group position={KITCHEN_SPOT} scale={1 - easeInOut(span(frame, AT.leave, 8))}>
              <VoxelMesh voxels={GOLEMS[cameo]} rotation={[0, Math.PI / 4, 0]} />
            </group>
          )}
        </group>
        <group scale={popIn(frame, AT.podium, 14, 0.12)}>
          <VoxelMesh voxels={PODIUMS[accent]} build={{ center: false }} />
        </group>
        {cameoVoxels && <group
          position={[CAMEO_AT[0], arrive.y + bob(frame, 50, 0.2), CAMEO_AT[2]]}
          rotation={[0, Math.PI / 4, wave]}
          scale={arrive.scale.map((v) => v * (frame < AT.cameo ? 0 : isGolem ? 0.58 : 0.85)) as [number, number, number]}
        >
          <VoxelMesh voxels={cameoVoxels} fit={isGolem ? undefined : 11} />
        </group>}
      </VoxelCanvas>
      {/* The logo on its own layer, never pixelated: a crisp rounded square and "mB". An
          invisible floor catches its shadow on the podium below. */}
      <VoxelCanvas width={width} height={height} pixelate={1} background="transparent" shadowExtent={44}>
        <CameraRig kind="iso" pose={poseAt(frame, MOVE)} />
        <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.02, 0]} receiveShadow>
          <circleGeometry args={[19, 64]} />
          <shadowMaterial opacity={0.28 * popIn(frame, AT.podium, 14, 0)} />
        </mesh>
        <group rotation={TILE_TURN}>
          <VoxelCubes voxels={TILE} place={(i) => drop(frame, START[i])} />
        </group>
      </VoxelCanvas>
      <Sequence from={AT.pill} durationInFrames={30} layout="none">
        <Html5Audio src={assetById("sfx-pop").src} volume={cardVolume("sfx-pop")} />
      </Sequence>
      {/* Brand base: wordmark, tagline, pill, url, stacked in the lower half of the safe area. */}
      <div
        style={{
          position: "absolute",
          left: area.left,
          width: area.width,
          top: 826,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          textAlign: "center",
          color: ink,
        }}
      >
        <div style={{ ...display, fontSize: 132, lineHeight: 1, whiteSpace: "nowrap" }}>
          {[..."macroBody"].map((ch, i) => (
            <span key={i} style={{ display: "inline-block", ...fade(frame, AT.word + i * 2, 8), color: i >= 5 ? brand.colors.brand : ink }}>
              {ch}
            </span>
          ))}
        </div>
        <div style={{ ...fade(frame, AT.tagline), marginTop: 22, fontFamily: `"${fonts.body}", sans-serif`, fontWeight: 600, fontSize: 46, lineHeight: 1.2, color: muted, textWrap: "balance", maxWidth: area.width - 40 }}>
          {line}
        </div>
        <div
          style={{
            ...display,
            marginTop: 34,
            transform: `scale(${pill})`,
            background: brand.colors.brand,
            color: "#FFFFFF",
            fontSize: 58,
            letterSpacing: "-0.02em",
            padding: "16px 40px 18px",
            borderRadius: 999,
            boxShadow: "0 10px 24px rgba(16, 24, 40, 0.18)",
          }}
        >
          {frenchSpaces(brand.cta.trial)}
        </div>
        <div style={{ ...fade(frame, AT.url), marginTop: 30, fontFamily: `"${fonts.body}", sans-serif`, fontWeight: 700, fontSize: 44 }}>
          <span style={{ borderBottom: `5px solid ${color}`, paddingBottom: 4 }}>{brand.cta.url}</span>
        </div>
      </div>
    </AbsoluteFill>
  );
};
