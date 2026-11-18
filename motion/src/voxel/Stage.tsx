// The voxel stage: canvas (with the optional pixelate pass), lighting rig, camera rig and
// the mesh component. Everything is driven by useCurrentFrame through props: no useFrame,
// no clock, so a frame renders the same every time.
import { ThreeCanvas } from "@remotion/three";
import { type ThreeElements, useThree } from "@react-three/fiber";
import { type ReactNode, useEffect, useLayoutEffect, useMemo } from "react";
import { AbsoluteFill } from "remotion";
import * as THREE from "three";
import { cameraPosition, type Pose } from "./anim.ts";
import { buildMesh, type BuildOptions, type Voxel } from "./mesh.ts";
import { COLORS } from "./palette.ts";

/** Pixelate factor used when a scene does not say: see the PR for the on/off comparison. */
export const DEFAULT_PIXELATE = 2;

/** Width the orthographic lens is defined against (lens = pixels per voxel at this width). */
const REFERENCE_WIDTH = 1080;

type CanvasProps = {
  width: number;
  height: number;
  /**
   * 1 = off. N renders at 1/N size without antialiasing and upscales with nearest-neighbour
   * filtering: crisp pixel steps on every edge, the "8-bit" read.
   */
  pixelate?: number;
  /** CSS background behind the scene (the canvas is transparent). */
  background?: string;
  /** Half-size of the area the key light's shadow covers, in voxels. */
  shadowExtent?: number;
  children: ReactNode;
};

export const VoxelCanvas = ({ width, height, pixelate = DEFAULT_PIXELATE, background, shadowExtent = 48, children }: CanvasProps) => {
  const p = Math.max(1, Math.round(pixelate));
  const w = Math.round(width / p);
  const h = Math.round(height / p);
  return (
    <AbsoluteFill style={{ background: background ?? "linear-gradient(180deg, #FFF3E2 0%, #FBEFE6 45%, #DDEFE8 100%)" }}>
      <div style={{ width: w, height: h, transform: `scale(${p})`, transformOrigin: "0 0" }}>
        <ThreeCanvas
          width={w}
          height={h}
          dpr={1}
          shadows="soft"
          style={{ imageRendering: p > 1 ? "pixelated" : "auto" }}
          gl={{ antialias: p === 1, alpha: true, toneMapping: THREE.NeutralToneMapping, toneMappingExposure: 1.05 }}
        >
          <Lights extent={shadowExtent} />
          {children}
        </ThreeCanvas>
      </div>
    </AbsoluteFill>
  );
};

/**
 * Warm key light with soft shadows, cool fill, white rim from behind, sky/ground hemisphere.
 * Shadow map 2048²: about one shadow texel per output pixel across a 1080 px wide scene.
 */
export const Lights = ({ extent = 48 }: { extent?: number }) => (
  <>
    <hemisphereLight args={["#EAF4FF", "#B08A62", 0.75]} />
    <ambientLight intensity={0.12} />
    <directionalLight
      position={[30, 55, 38]}
      intensity={3.3}
      color="#FFEFD8"
      castShadow
      shadow-mapSize={[2048, 2048]}
      shadow-bias={-0.0004}
      shadow-normalBias={0.05}
      shadow-camera-left={-extent}
      shadow-camera-right={extent}
      shadow-camera-top={extent}
      shadow-camera-bottom={-extent}
      shadow-camera-near={1}
      shadow-camera-far={220}
    />
    <directionalLight position={[-40, 22, 18]} intensity={0.55} color="#CFE0FF" />
    <directionalLight position={[-12, 30, -45]} intensity={1.3} color="#FFFFFF" />
  </>
);

/** Orthographic isometric ("iso") or perspective ("persp") camera placed at `pose`. */
export const CameraRig = ({ kind, pose }: { kind: "iso" | "persp"; pose: Pose }) => {
  const get = useThree((s) => s.get);
  // Layout effect: runs before @remotion/three renders the frame (a passive effect).
  useLayoutEffect(() => {
    const { camera: current, set, size } = get();
    let camera = current;
    if (!camera.userData.voxelRig || camera instanceof THREE.OrthographicCamera !== (kind === "iso")) {
      camera = kind === "iso" ? new THREE.OrthographicCamera() : new THREE.PerspectiveCamera();
      // R3F leaves a manual camera's projection alone on resize: this component owns it.
      Object.assign(camera, { manual: true, near: 0.5, far: 1000 });
      camera.userData.voxelRig = true;
      set({ camera });
    }
    camera.position.set(...cameraPosition(pose));
    camera.lookAt(...pose.target);
    if (camera instanceof THREE.OrthographicCamera) {
      Object.assign(camera, { left: -size.width / 2, right: size.width / 2, top: size.height / 2, bottom: -size.height / 2 });
      camera.zoom = (pose.lens * size.width) / REFERENCE_WIDTH;
      camera.updateProjectionMatrix();
    } else if (camera instanceof THREE.PerspectiveCamera) {
      camera.fov = pose.lens;
      camera.aspect = size.width / size.height;
      camera.updateProjectionMatrix();
    }
  });
  return null;
};

type MeshProps = Omit<ThreeElements["group"], "children"> & {
  /** Build it once (module level or useMemo): a new array rebuilds the mesh. */
  voxels: Voxel[];
  /** Scale so the model's largest side is `fit` world units (default: 1 voxel = 1 unit). */
  fit?: number;
  build?: BuildOptions;
};

/** One model = one merged mesh (built once per model, then only transformed). */
export const VoxelMesh = ({ voxels, fit, build, ...group }: MeshProps) => {
  const { noise, ao, center } = build ?? {};
  const { geometry, scale } = useMemo(() => {
    const m = buildMesh(voxels, COLORS, { noise, ao, center });
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(m.positions, 3));
    g.setAttribute("normal", new THREE.BufferAttribute(m.normals, 3));
    g.setAttribute("color", new THREE.BufferAttribute(m.colors, 3));
    g.setIndex(new THREE.BufferAttribute(m.indices, 1));
    g.computeBoundingSphere();
    return { geometry: g, scale: fit ? fit / Math.max(...m.size, 1) : 1 };
  }, [voxels, fit, noise, ao, center]);
  useEffect(() => () => geometry.dispose(), [geometry]);
  return (
    <group {...group}>
      <mesh geometry={geometry} scale={scale} castShadow receiveShadow>
        <meshStandardMaterial vertexColors roughness={0.82} metalness={0} />
      </mesh>
    </group>
  );
};
