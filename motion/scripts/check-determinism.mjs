#!/usr/bin/env node
// Renders the same VoxelPreview still twice (one bundle) and fails unless both PNGs are
// byte-identical: the voxel engine must be deterministic (no Math.random, no clock).
// Usage: node scripts/check-determinism.mjs [--frame N] [--gl <renderer>]  (npm run check:voxel)
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";

const motion = join(dirname(fileURLToPath(import.meta.url)), "..");
const { values: a } = parseArgs({ options: { frame: { type: "string", default: "150" }, gl: { type: "string" } } });
const dir = mkdtempSync(join(tmpdir(), "voxel-determinism-"));
const render = (...args) => execFileSync(process.execPath, [join(motion, "render.mjs"), ...args], { stdio: ["ignore", "pipe", "inherit"] });
try {
  render("--bundle-only", "--bundle", join(dir, "bundle"));
  const hashes = ["a", "b"].map((name) => {
    const out = join(dir, `${name}.png`);
    render("--template", "VoxelPreview", "--props", join(motion, "props", "voxel-preview.json"), "--out", out,
      "--still", "--frame", a.frame, "--bundle", join(dir, "bundle"), ...(a.gl ? ["--gl", a.gl] : []));
    return createHash("sha256").update(readFileSync(out)).digest("hex");
  });
  process.stdout.write(`${JSON.stringify({ frame: Number(a.frame), hashes, same: hashes[0] === hashes[1] })}\n`);
  if (hashes[0] !== hashes[1]) process.exitCode = 1;
} finally {
  rmSync(dir, { recursive: true, force: true });
}
