// Showcase of the voxel engine (step 129): the six golem forms, the Titan, the props turning.
// Registered in Root.tsx only (not a template the studio can pick).
import { useCurrentFrame } from "remotion";
import { z } from "zod";
import { bob, dolly, hop, ISO, type Move, orbit, popIn, type Pose, poseAt, pushIn, turntable } from "../voxel/anim.ts";
import { golem, island, platform, PROPS } from "../voxel/models.ts";
import { CameraRig, DEFAULT_PIXELATE, VoxelCanvas, VoxelMesh } from "../voxel/Stage.tsx";

export const voxelPreviewSchema = z.strictObject({
  /** 1 = off; see VoxelCanvas. */
  pixelate: z.number().int().min(1).max(4),
});

export const VOXEL_PREVIEW_DEFAULTS: z.infer<typeof voxelPreviewSchema> = { pixelate: DEFAULT_PIXELATE };

/** Scene starts at 30 fps: the six forms (iso), the Titan up close, the props (perspective). */
export const SCENES = { golems: 0, titan: 180, props: 300, end: 480 };

const GOLEMS = [1, 2, 3, 4, 5, 6].map((level) => golem(level).voxels());
const PROP_MODELS = Object.values(PROPS).map((make) => make().voxels());
const GOLEM_BASE = platform(30).voxels();
const ISLAND = island(7).voxels();
const HERO_ISLAND = island(15, 7).voxels();

// Golems by level: forms 1–3 in front, 4–6 behind (Titan, the widest, in the middle).
const GOLEM_SPOTS: [number, number][] = [[-16, 13], [0, 13], [16, 13], [-16, -13], [16, -13], [0, -13]];
const golemStart: Pose = { ...ISO, azimuth: 30, distance: 120, target: [0, 7, 0], lens: 16 };
const golemMove: Move = { from: golemStart, to: pushIn(orbit(golemStart, 30), 1.1, [0, 8, 0]), start: SCENES.golems, duration: SCENES.titan };

const GolemLineup = ({ frame }: { frame: number }) => (
  <>
    <CameraRig kind="iso" pose={poseAt(frame, golemMove)} />
    {/* Rows face azimuth 45°, where the camera passes mid-move. */}
    <group rotation={[0, Math.PI / 4, 0]}>
      <VoxelMesh voxels={GOLEM_BASE} position={[0, -4, 0]} />
      {GOLEMS.map((voxels, i) => {
        const [x, z] = GOLEM_SPOTS[i];
        const s = popIn(frame, 8 + i * 7, 14);
        const h = hop(frame, 80 + i * 10, 22, 5);
        return (
          <group key={i} position={[x, h.y + 0.2 + bob(frame, 70, 0.2, i * 11), z]} scale={h.scale.map((v) => v * s) as [number, number, number]}>
            <VoxelMesh voxels={voxels} />
          </group>
        );
      })}
    </group>
  </>
);

// Titan alone: perspective push-in while it turns to show the wings, then hops.
const titanStart: Pose = { azimuth: 10, elevation: 16, distance: 140, target: [0, 10, 0], lens: 32 };
const titanMove: Move = { from: titanStart, to: pushIn(orbit(titanStart, -20), 1.3, [0, 11, 0], false), start: SCENES.titan, duration: SCENES.props - SCENES.titan };

const TitanHero = ({ frame }: { frame: number }) => {
  const t = frame - SCENES.titan;
  const h = hop(t, 84, 24, 6);
  return (
    <>
      <CameraRig kind="persp" pose={poseAt(frame, titanMove)} />
      <VoxelMesh voxels={HERO_ISLAND} position={[0, -8, 0]} />
      <group position={[0, h.y, 0]} scale={h.scale} rotation={[0, turntable(t, 200, -0.9), 0]}>
        <VoxelMesh voxels={GOLEMS[5]} />
      </group>
    </>
  );
};

// Props: a zig-zag stack of floating islands (fills the tall frame), long perspective lens.
const PROP_SPOTS: [number, number][] = [0, 1, 2, 3, 4, 5, 6, 7].map((i) => [i % 2 ? 9.5 : -9.5, i * 9.5]);
const propStart: Pose = { azimuth: -14, elevation: 24, distance: 250, target: [0, 37, 0], lens: 20 };
const propMove: Move = { from: propStart, to: dolly(orbit(propStart, 28), 0.9), start: SCENES.props, duration: SCENES.end - SCENES.props };

const PropIslands = ({ frame }: { frame: number }) => {
  const t = frame - SCENES.props;
  return (
    <>
      <CameraRig kind="persp" pose={poseAt(frame, propMove)} />
      {PROP_MODELS.map((voxels, i) => {
        const [x, y] = PROP_SPOTS[i];
        return (
          <group key={i} position={[x, y + bob(t, 90, 0.5, i * 13), 0]}>
            <VoxelMesh voxels={ISLAND} position={[0, -6, 0]} />
            {/* Faces the camera mid-scene, swinging about 70° either side. */}
            <group scale={popIn(t, 4 + i * 5, 14)} rotation={[0, turntable(t - 90, 480, 0.25 - i * 0.04), 0]}>
              <VoxelMesh voxels={voxels} fit={11} />
            </group>
          </group>
        );
      })}
    </>
  );
};

export const VoxelPreview = ({ pixelate }: z.infer<typeof voxelPreviewSchema>) => {
  const frame = useCurrentFrame();
  const scene = frame < SCENES.titan ? "golems" : frame < SCENES.props ? "titan" : "props";
  return (
    <VoxelCanvas width={1080} height={1920} pixelate={pixelate} shadowExtent={scene === "props" ? 52 : 46}>
      {scene === "golems" ? <GolemLineup frame={frame} /> : scene === "titan" ? <TitanHero frame={frame} /> : <PropIslands frame={frame} />}
    </VoxelCanvas>
  );
};
