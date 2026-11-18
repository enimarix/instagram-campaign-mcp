// Voxel models as code, and the builder that turns one into ONE merged mesh.
// Pure (no runtime imports): `node --test` runs it without a GPU (test/voxel.test.ts).

/** One cube: integer cell [x, y, z] (y is up) and a palette colour name. */
export type Voxel = [x: number, y: number, z: number, color: string];

/** A colour, or a rule giving one per cell (null leaves the cell as it is). */
export type Paint = string | ((x: number, y: number, z: number) => string | null);

const key = (x: number, y: number, z: number) => `${x},${y},${z}`;

/** A sparse voxel model. Later writes win, so details are painted over a base shape. */
export class VoxelGrid {
  readonly cells = new Map<string, Voxel>();

  set(x: number, y: number, z: number, paint: Paint): this {
    const c = typeof paint === "string" ? paint : paint(x, y, z);
    if (c !== null) this.cells.set(key(x, y, z), [x, y, z, c]);
    return this;
  }

  remove(x: number, y: number, z: number): this {
    this.cells.delete(key(x, y, z));
    return this;
  }

  get(x: number, y: number, z: number): string | undefined {
    return this.cells.get(key(x, y, z))?.[3];
  }

  /** Inclusive box. */
  box(x0: number, y0: number, z0: number, x1: number, y1: number, z1: number, paint: Paint): this {
    for (let x = Math.min(x0, x1); x <= Math.max(x0, x1); x++)
      for (let y = Math.min(y0, y1); y <= Math.max(y0, y1); y++)
        for (let z = Math.min(z0, z1); z <= Math.max(z0, z1); z++) this.set(x, y, z, paint);
    return this;
  }

  /** Every cell whose centre lies inside the ellipsoid (centre may sit on a half cell). */
  ellipsoid(cx: number, cy: number, cz: number, rx: number, ry: number, rz: number, paint: Paint, keep?: (x: number, y: number, z: number) => boolean): this {
    for (let x = Math.floor(cx - rx); x <= Math.ceil(cx + rx); x++)
      for (let y = Math.floor(cy - ry); y <= Math.ceil(cy + ry); y++)
        for (let z = Math.floor(cz - rz); z <= Math.ceil(cz + rz); z++) {
          const d = ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 + ((z - cz) / rz) ** 2;
          if (d <= 1 && (!keep || keep(x, y, z))) this.set(x, y, z, paint);
        }
    return this;
  }

  /** Upright cylinder (along y) from y0 to y1 inclusive. */
  cylinder(cx: number, cz: number, y0: number, y1: number, r: number, paint: Paint): this {
    for (let y = y0; y <= y1; y++)
      for (let x = Math.floor(cx - r); x <= Math.ceil(cx + r); x++)
        for (let z = Math.floor(cz - r); z <= Math.ceil(cz + r); z++)
          if ((x - cx) ** 2 + (z - cz) ** 2 <= r * r) this.set(x, y, z, paint);
    return this;
  }

  /** Every cell within the radius (r0 at a, r1 at b) of the segment a-b: limbs, bones, stems. */
  capsule(a: [number, number, number], b: [number, number, number], r0: number, r1: number, paint: Paint): this {
    const d = [b[0] - a[0], b[1] - a[1], b[2] - a[2]];
    const len2 = d[0] ** 2 + d[1] ** 2 + d[2] ** 2 || 1;
    const r = Math.max(r0, r1);
    for (let x = Math.floor(Math.min(a[0], b[0]) - r); x <= Math.ceil(Math.max(a[0], b[0]) + r); x++)
      for (let y = Math.floor(Math.min(a[1], b[1]) - r); y <= Math.ceil(Math.max(a[1], b[1]) + r); y++)
        for (let z = Math.floor(Math.min(a[2], b[2]) - r); z <= Math.ceil(Math.max(a[2], b[2]) + r); z++) {
          const t = Math.min(1, Math.max(0, ((x - a[0]) * d[0] + (y - a[1]) * d[1] + (z - a[2]) * d[2]) / len2));
          const dist2 = (x - a[0] - d[0] * t) ** 2 + (y - a[1] - d[1] * t) ** 2 + (z - a[2] - d[2] * t) ** 2;
          if (dist2 <= (r0 + (r1 - r0) * t) ** 2) this.set(x, y, z, paint);
        }
    return this;
  }

  /** Recolour the cells that exist; `paint` returning null keeps a cell's colour. */
  repaint(paint: (x: number, y: number, z: number, color: string) => string | null): this {
    for (const v of this.cells.values()) {
      const c = paint(v[0], v[1], v[2], v[3]);
      if (c !== null) v[3] = c;
    }
    return this;
  }

  /**
   * Layers of strings, bottom layer first; in a layer, rows run back (-z) to front (+z) and
   * characters left (-x) to right (+x). "." and " " are empty, other characters go through `key`.
   */
  layers(layers: string[][], keyMap: Record<string, string>, at: [number, number, number] = [0, 0, 0]): this {
    layers.forEach((rows, y) =>
      rows.forEach((row, z) =>
        [...row].forEach((ch, x) => {
          if (ch === "." || ch === " ") return;
          const c = keyMap[ch];
          if (c === undefined) throw new Error(`voxel layers: no colour for "${ch}"`);
          this.set(at[0] + x, at[1] + y, at[2] + z, c);
        }),
      ),
    );
    return this;
  }

  /** Copy of every cell, translated. */
  add(other: VoxelGrid, dx = 0, dy = 0, dz = 0): this {
    for (const [x, y, z, c] of other.cells.values()) this.set(x + dx, y + dy, z + dz, c);
    return this;
  }

  voxels(): Voxel[] {
    return [...this.cells.values()];
  }
}

// Faces: outward normal, corners counter-clockwise seen from outside, and a fixed shade so
// a cube reads as a cube even where the lights hit two faces alike.
const FACES = [
  { n: [1, 0, 0], c: [[1, 0, 0], [1, 1, 0], [1, 1, 1], [1, 0, 1]], shade: 0.9 },
  { n: [-1, 0, 0], c: [[0, 0, 1], [0, 1, 1], [0, 1, 0], [0, 0, 0]], shade: 0.9 },
  { n: [0, 1, 0], c: [[0, 1, 0], [0, 1, 1], [1, 1, 1], [1, 1, 0]], shade: 1 },
  { n: [0, -1, 0], c: [[0, 0, 0], [1, 0, 0], [1, 0, 1], [0, 0, 1]], shade: 0.72 },
  { n: [0, 0, 1], c: [[0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]], shade: 0.95 },
  { n: [0, 0, -1], c: [[1, 0, 0], [0, 0, 0], [0, 1, 0], [1, 1, 0]], shade: 0.95 },
] as const;

/** Vertex brightness by how many of its 3 neighbours (2 sides, 1 corner) are solid. */
const AO = [1, 0.84, 0.7, 0.56];

const srgbToLinear = (c: number) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);

/** Deterministic 0..1 from a cell (no Math.random: renders must repeat exactly). */
export const cellNoise = (x: number, y: number, z: number): number => {
  let t = Math.imul(x, 0x9e3779b1) ^ Math.imul(y, 0x85ebca6b) ^ Math.imul(z, 0xc2b2ae35);
  t = Math.imul(t ^ (t >>> 16), 0x7feb352d);
  t = Math.imul(t ^ (t >>> 15), 0x846ca68b);
  return ((t ^ (t >>> 16)) >>> 0) / 4294967296;
};

export type MeshData = {
  /** xyz per vertex, in voxel units; x/z centred on the model, y = 0 at its bottom. */
  positions: Float32Array;
  normals: Float32Array;
  /** Linear RGB per vertex (palette colour x face shade x ambient occlusion x noise). */
  colors: Float32Array;
  indices: Uint32Array;
  /** Visible faces (hidden faces between two cubes are culled). */
  faces: number;
  /** Bounding box size in voxels [x, y, z]. */
  size: [number, number, number];
};

export type BuildOptions = {
  /** Per-cube brightness variation, 0..0.2 (default 0.035): hand-made texture, deterministic. */
  noise?: number;
  /** Ambient occlusion in the corners (default true). */
  ao?: boolean;
  /** Centre x/z and stand on y = 0 (default true); false keeps cell coordinates. */
  center?: boolean;
};

/**
 * One mesh for a whole model: 4 vertices + 2 triangles per visible face. Throws on a
 * colour the palette does not have, so a typo never renders as black.
 */
export const buildMesh = (voxels: Voxel[], palette: Readonly<Record<string, string>>, options: BuildOptions = {}): MeshData => {
  const { noise = 0.035, ao = true, center = true } = options;
  const solid = new Set<string>();
  for (const [x, y, z] of voxels) solid.add(key(x, y, z));
  const filled = (x: number, y: number, z: number) => (solid.has(key(x, y, z)) ? 1 : 0);

  let min = [Infinity, Infinity, Infinity];
  let max = [-Infinity, -Infinity, -Infinity];
  for (const v of voxels) {
    min = min.map((m, i) => Math.min(m, v[i] as number));
    max = max.map((m, i) => Math.max(m, (v[i] as number) + 1));
  }
  const offset = !voxels.length || !center ? [0, 0, 0] : [-(min[0] + max[0]) / 2, -min[1], -(min[2] + max[2]) / 2];

  const rgb = new Map<string, number[]>();
  const linear = (name: string) => {
    let c = rgb.get(name);
    if (!c) {
      const hex = palette[name];
      if (!hex || !/^#[0-9a-fA-F]{6}$/.test(hex)) throw new Error(`voxel colour "${name}" is not in the palette`);
      const n = parseInt(hex.slice(1), 16);
      c = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => srgbToLinear(v / 255));
      rgb.set(name, c);
    }
    return c;
  };

  const positions: number[] = [];
  const normals: number[] = [];
  const colors: number[] = [];
  const indices: number[] = [];
  let faces = 0;
  for (const [x, y, z, name] of voxels) {
    const base = linear(name);
    const jitter = 1 + (cellNoise(x, y, z) * 2 - 1) * noise;
    for (const f of FACES) {
      const [nx, ny, nz] = f.n;
      if (filled(x + nx, y + ny, z + nz)) continue; // hidden face: culled
      faces++;
      // The two axes across the face, for the corner neighbours of each vertex.
      const axis = f.n.findIndex((v) => v !== 0);
      const [u, w] = [0, 1, 2].filter((i) => i !== axis);
      const first = positions.length / 3;
      const light: number[] = [];
      for (const corner of f.c) {
        positions.push(x + corner[0] + offset[0], y + corner[1] + offset[1], z + corner[2] + offset[2]);
        normals.push(nx, ny, nz);
        let level = 1;
        if (ao) {
          const p = [x + nx, y + ny, z + nz];
          const du = [0, 0, 0];
          const dw = [0, 0, 0];
          du[u] = corner[u] ? 1 : -1;
          dw[w] = corner[w] ? 1 : -1;
          const s1 = filled(p[0] + du[0], p[1] + du[1], p[2] + du[2]);
          const s2 = filled(p[0] + dw[0], p[1] + dw[1], p[2] + dw[2]);
          const cn = filled(p[0] + du[0] + dw[0], p[1] + du[1] + dw[1], p[2] + du[2] + dw[2]);
          level = AO[s1 && s2 ? 3 : s1 + s2 + cn];
        }
        light.push(level);
        const k = f.shade * level * jitter;
        colors.push(base[0] * k, base[1] * k, base[2] * k);
      }
      // Split the quad along its brighter diagonal: a lone dark corner then fades out
      // instead of streaking across the face.
      if (light[0] + light[2] >= light[1] + light[3]) {
        indices.push(first, first + 1, first + 2, first, first + 2, first + 3);
      } else {
        indices.push(first + 1, first + 2, first + 3, first + 1, first + 3, first);
      }
    }
  }
  const size: [number, number, number] = voxels.length ? [max[0] - min[0], max[1] - min[1], max[2] - min[2]] : [0, 0, 0];
  return {
    positions: new Float32Array(positions),
    normals: new Float32Array(normals),
    colors: new Float32Array(colors),
    indices: new Uint32Array(indices),
    faces,
    size,
  };
};
