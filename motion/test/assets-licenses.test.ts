// Every file in public/ is accounted for in ASSETS_LICENSES.md (GOAL.md §5.1: sound and art
// have their own rights), and the registry and generated files match what is on disk.
import assert from "node:assert/strict";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { build } from "../scripts/make-assets.ts";
import { ASSETS } from "../src/assets.ts";

const root = join(import.meta.dirname, "..");

/** Files under public/, as `public/a/b` paths, sorted (CI order differs from Windows). */
const walk = (dir: string): string[] =>
  readdirSync(join(root, dir), { withFileTypes: true })
    .flatMap((e) => (e.isDirectory() ? walk(`${dir}/${e.name}`) : [`${dir}/${e.name}`]))
    .sort();

/** Every `public/...` path written in backticks in ASSETS_LICENSES.md (table rows and licence texts). */
const listed = (): Set<string> =>
  new Set([...readFileSync(join(root, "ASSETS_LICENSES.md"), "utf8").matchAll(/`(public\/[^`]+)`/g)].map((m) => m[1]));

test("every file in public/ is listed in ASSETS_LICENSES.md", () => {
  const unlisted = walk("public").filter((f) => !listed().has(f));
  assert.deepEqual(unlisted, [], "add these files to ASSETS_LICENSES.md with licence and source");
});

test("every file listed in ASSETS_LICENSES.md exists", () => {
  const missing = [...listed()].filter((f) => !existsSync(join(root, f))).sort();
  assert.deepEqual(missing, []);
});

test("generated files match scripts/make-assets.ts (re-run it after changing art or songs)", () => {
  for (const [path, data] of build()) {
    const disk = readFileSync(join(root, path));
    if (typeof data === "string") assert.equal(disk.toString("utf8").replace(/\r\n/g, "\n"), data, path);
    else assert.ok(disk.equals(data), path);
  }
});

test("registry files exist and sheet sizes match the files", () => {
  for (const [id, a] of Object.entries(ASSETS)) {
    const path = join(root, "public", a.file);
    assert.ok(existsSync(path), `${id}: ${a.file}`);
    if (!("frames" in a)) continue;
    const svg = readFileSync(path, "utf8");
    assert.match(svg, new RegExp(`width="${a.frameWidth * a.frames}" height="${a.frameHeight}"`), id);
  }
});
