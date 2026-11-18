// Voxel engine (step 129): builder, palette, models and animation maths. No GPU needed.
import assert from "node:assert/strict";
import { test } from "node:test";
import * as THREE from "three";
import { cameraPosition, easeInOut, hop, ISO, popIn, poseAt, projectIso, turntable } from "../src/voxel/anim.ts";
import { buildMesh, VoxelGrid } from "../src/voxel/mesh.ts";
import { golem, island, kitchen, kitchenScale, mbTile, phone, plate, platform, PROPS } from "../src/voxel/models.ts";
import { COLORS, FORMS, mix } from "../src/voxel/palette.ts";

const PAL = { a: "#FF0000", b: "#0000FF" };

test("buildMesh culls the faces between touching cubes", () => {
  const one = buildMesh([[0, 0, 0, "a"]], PAL);
  assert.equal(one.faces, 6);
  assert.equal(one.positions.length, 6 * 4 * 3);
  assert.equal(one.indices.length, 6 * 6);
  assert.equal(buildMesh([[0, 0, 0, "a"], [1, 0, 0, "b"]], PAL).faces, 10);
  const cube = new VoxelGrid().box(0, 0, 0, 2, 2, 2, "a");
  assert.equal(cube.voxels().length, 27);
  assert.equal(buildMesh(cube.voxels(), PAL).faces, 6 * 9); // only the outer skin
  // Diagonal neighbours share no face.
  assert.equal(buildMesh([[0, 0, 0, "a"], [1, 1, 0, "a"]], PAL).faces, 12);
});

test("buildMesh maps palette names to linear colours and rejects unknown ones", () => {
  const m = buildMesh([[0, 0, 0, "a"]], PAL, { ao: false, noise: 0 });
  // Top face (shade 1): pure linear red.
  const top = [...m.normals].findIndex((_, i) => i % 3 === 1 && m.normals[i] === 1) - 1;
  assert.deepEqual([...m.colors.slice(top, top + 3)], [1, 0, 0]);
  // Every colour is red only, darker on the sides and bottom.
  for (let i = 0; i < m.colors.length; i += 3) {
    assert.ok(m.colors[i] > 0.7 && m.colors[i] <= 1);
    assert.equal(m.colors[i + 1], 0);
  }
  // sRGB -> linear: #808080 is about 0.216 in linear light.
  const grey = buildMesh([[0, 0, 0, "g"]], { g: "#808080" }, { ao: false, noise: 0 });
  assert.ok(Math.abs(Math.max(...grey.colors) - 0.2158) < 0.001);
  assert.throws(() => buildMesh([[0, 0, 0, "nope"]], PAL), /"nope" is not in the palette/);
});

test("buildMesh centres x/z, stands on y = 0 and reports the size", () => {
  const m = buildMesh(new VoxelGrid().box(4, 2, 4, 7, 5, 5, "a").voxels(), PAL);
  assert.deepEqual(m.size, [4, 4, 2]);
  const xs = [...m.positions].filter((_, i) => i % 3 === 0);
  const ys = [...m.positions].filter((_, i) => i % 3 === 1);
  assert.deepEqual([Math.min(...xs), Math.max(...xs)], [-2, 2]);
  assert.deepEqual([Math.min(...ys), Math.max(...ys)], [0, 4]);
  assert.equal(Math.min(...[...buildMesh([[3, 3, 3, "a"]], PAL, { center: false }).positions]), 3);
});

test("ambient occlusion darkens inner corners only, and the build is repeatable", () => {
  const flat = buildMesh([[0, 0, 0, "a"]], PAL, { noise: 0 });
  assert.ok(flat.colors.every((c, i) => i % 3 !== 0 || c > 0.7)); // a lone cube: no occlusion
  // A floor with a wall on it: the floor vertices against the wall get darker.
  const corner = new VoxelGrid().box(0, 0, 0, 2, 0, 2, "a").set(1, 1, 0, "a").voxels();
  const m = buildMesh(corner, PAL, { noise: 0, center: false });
  let darkest = 1;
  for (let v = 0; v < m.positions.length / 3; v++) {
    if (m.normals[v * 3 + 1] === 1 && m.positions[v * 3 + 1] === 1) darkest = Math.min(darkest, m.colors[v * 3]);
  }
  assert.ok(darkest < 0.9, `floor next to the wall should be occluded, got ${darkest}`);
  const again = buildMesh(golem(6).voxels(), COLORS);
  assert.deepEqual(again.colors, buildMesh(golem(6).voxels(), COLORS).colors);
});

test("layers: rows back to front, characters through the key", () => {
  const g = new VoxelGrid().layers([["ab", ".a"], ["b."]], { a: "a", b: "b" });
  assert.deepEqual(g.voxels().sort(), [[0, 0, 0, "a"], [0, 1, 0, "b"], [1, 0, 0, "b"], [1, 0, 1, "a"]].sort());
  assert.throws(() => new VoxelGrid().layers([["x"]], {}), /no colour for "x"/);
});

test("every model uses palette colours only and gains parts per golem form", () => {
  const models = {
    ...Object.fromEntries(Object.entries(PROPS).map(([k, f]) => [k, f()])),
    island: island(7),
    platform: platform(10),
    kitchen: kitchen(),
    mbTile: mbTile(),
    plate: plate(),
  };
  for (const [name, g] of Object.entries(models)) {
    assert.ok(g.voxels().length > 50, name);
    for (const [, , , c] of g.voxels()) assert.ok(COLORS[c], `${name}: ${c} not in palette`);
    assert.doesNotThrow(() => buildMesh(g.voxels(), COLORS), name);
  }
  const sizes = FORMS.map((_, i) => golem(i + 1).voxels().length);
  for (let i = 1; i < sizes.length; i++) assert.ok(sizes[i] > sizes[i - 1], `form ${i + 1} adds parts`);
  FORMS.forEach((f, i) => assert.ok(golem(i + 1).voxels().some(([, , , c]) => c === f.id), f.name));
  assert.equal(COLORS.emerald, "#10B981");
  assert.equal(COLORS.titan, "#C593FF");
  assert.equal(mix("#000000", "#FFFFFF", 0.5), "#808080");
});

test("animation helpers: pop-in overshoots, hop squashes and lands, turntable and camera", () => {
  assert.equal(popIn(5, 10), 0);
  assert.ok(Math.max(...Array.from({ length: 12 }, (_, i) => popIn(10 + i, 10, 12))) > 1.05);
  assert.ok(Math.abs(popIn(22, 10, 12) - 1) < 1e-9);
  const crouch = hop(2, 0, 24);
  assert.equal(crouch.y, 0);
  assert.ok(crouch.scale[1] < 1 && crouch.scale[0] > 1); // squash keeps volume
  assert.ok(Math.abs(crouch.scale[0] ** 2 * crouch.scale[1] - 1) < 1e-9);
  assert.ok(Math.abs(hop(12, 0, 24, 4).y - 4) < 0.1); // apex mid-air
  assert.deepEqual(hop(24, 0, 24), { y: 0, scale: [1, 1, 1] });
  // Continuous: no frame jumps in height or scale.
  for (let f = 0; f < 240; f++) {
    const [a, b] = [hop(f / 10, 0, 24), hop((f + 1) / 10, 0, 24)];
    assert.ok(Math.abs(a.scale[1] - b.scale[1]) < 0.05 && Math.abs(a.y - b.y) < 0.2, `jump at ${f / 10}`);
  }
  assert.ok(Math.abs(turntable(120, 240) - Math.PI) < 1e-9);
  assert.equal(easeInOut(0.5), 0.5);
  const pose = { ...ISO, distance: 10, target: [0, 0, 0] as [number, number, number], lens: 20 };
  const [x, y, z] = cameraPosition(pose);
  assert.ok(Math.abs(x - z) < 1e-9 && Math.abs(y - 10 / Math.sqrt(3)) < 1e-9); // true isometric
  const move = { from: pose, to: { ...pose, azimuth: 90 }, start: 10, duration: 20 };
  assert.equal(poseAt(0, move).azimuth, 45);
  assert.equal(poseAt(20, move).azimuth, 67.5);
  assert.equal(poseAt(99, move).azimuth, 90);
});

test("projectIso lands where three.js's orthographic camera puts a point", () => {
  const pose = { ...ISO, azimuth: 20, elevation: 30, distance: 160, target: [5, 20, -10] as [number, number, number], lens: 26 };
  const camera = new THREE.OrthographicCamera(-540, 540, 960, -960, 0.5, 1000);
  camera.position.set(...cameraPosition(pose));
  camera.lookAt(...pose.target);
  camera.zoom = pose.lens;
  camera.updateProjectionMatrix();
  camera.updateMatrixWorld();
  for (const p of [[0, 0, 0], [12, 11, -16], [-8, 25, -2]] as [number, number, number][]) {
    const v = new THREE.Vector3(...p).project(camera);
    const [x, y] = projectIso(pose, p);
    assert.ok(Math.abs(x - (v.x + 1) * 540) < 1e-6 && Math.abs(y - (1 - v.y) * 960) < 1e-6, `${p}: ${x},${y}`);
  }
});

test("step 130 props: a scale with a lit reading, a phone ring that fills, the mB tile", () => {
  const lit = (g: ReturnType<typeof kitchenScale>) => g.voxels().filter(([, , , c]) => c === "lcdOn").length;
  assert.ok(lit(kitchenScale("72.4")) > lit(kitchenScale("1")) && lit(kitchenScale("1")) > 0);
  const size = buildMesh(kitchenScale().voxels(), COLORS).size;
  assert.ok(size[1] <= 3 && size[0] >= 18, "flat and wide: a scale, not a toaster");
  const ring = (f: number) => phone(f).voxels().filter(([, , , c]) => ["protein", "carbs", "fat"].includes(c)).length;
  assert.equal(ring(0), 0);
  assert.ok(ring(0.5) > 0 && ring(0.5) < ring(1));
  assert.deepEqual(phone(1).voxels().length, phone(0).voxels().length); // same cubes, only colours change
  const tile = mbTile().voxels();
  assert.ok(tile.filter(([, , z, c]) => z === 1 && c === "white").length > 60, "mB letters stand proud");
  assert.deepEqual(buildMesh(tile, COLORS).size.slice(0, 2), [26, 26]);
});
