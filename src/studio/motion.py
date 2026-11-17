"""
Python side of the Remotion templates in `motion/` (GOAL.md §3.1, §4.1, §5.6).

- `motion/schemas.mjs` exports every template's props schema (JSON Schema, defaults) and
  validates props with the template's own Zod schema: the same check and message as a render.
- `motion/render.mjs` renders a video or a still from a bundle. Bundling is slow and crashes
  when two run at once (step 006a), so this process bundles once, under a lock, and every
  render reuses that bundle.

Recipes store the voice audio as a media path (`voice.audioSrc`, relative to the media root);
a render copies it into the bundle's `public/` and hands Remotion that URL instead.
Node: `NODE_BIN` (a full path or a command name) overrides `node` on PATH.
"""

from __future__ import annotations

import atexit
import functools
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..config import InstagramMCPSettings
from ..store import CampaignStore
from . import ffmpeg, media, recipe, render  # render.py imports this module back
from .ffmpeg import MediaInfo, PathLike
from .tts import get_provider

MOTION_DIR = Path(__file__).resolve().parents[2] / "motion"
SCHEMA_TIMEOUT_S = 60.0
BUNDLE_TIMEOUT_S = 300.0
STILL_TIMEOUT_S = 120.0
RENDER_CONCURRENCY = 4  # Chrome tabs per render; 2 renders in parallel (step 006a)
TAIL_CHARS = 2000

# Script lines (hook first) of templates with a voice, in the order of `voice.lines`.
SCRIPTS = {
    "FactQuest": lambda p: [p["hook"], *(f["text"] for f in p["facts"]), p["outro"]],
}


class MotionError(RuntimeError):
    """Node, a bundle or a render failed (worth a retry; bad props raise ValueError)."""


def find_node() -> str:
    name = os.environ.get("NODE_BIN") or "node"
    found = shutil.which(name)
    if not found:
        hint = ("winget install OpenJS.NodeJS.LTS" if sys.platform == "win32"
                else "install Node.js 22.12+ from nodejs.org or your package manager")
        raise MotionError(f"Node.js not found ({name!r}): {hint}, or set NODE_BIN")
    if not (MOTION_DIR / "node_modules").is_dir():
        raise MotionError(f"motion dependencies missing: run `npm ci` in {MOTION_DIR}")
    return found


def _node(script: str, args: Sequence[Any], *, timeout_s: float,
          stdin: Optional[str] = None) -> Dict[str, Any]:
    """Run a motion/ script; its last stdout line is JSON."""
    cmd = [find_node(), str(MOTION_DIR / script), *map(str, args)]
    try:
        done = subprocess.run(cmd, cwd=MOTION_DIR, input=stdin, capture_output=True,
                              text=True, encoding="utf-8", timeout=timeout_s)
    except subprocess.TimeoutExpired:
        raise MotionError(f"{script} ran past {timeout_s:g} s") from None
    if done.returncode != 0:
        raise MotionError(f"{script} failed: {done.stderr.strip()[-TAIL_CHARS:]}")
    return json.loads(done.stdout.strip().splitlines()[-1])


@functools.lru_cache(maxsize=1)
def list_templates() -> List[Dict[str, Any]]:
    """[{id, jsonSchema, defaultProps, description}] (cached: restart after editing motion/)."""
    return _node("schemas.mjs", [], timeout_s=SCHEMA_TIMEOUT_S)["templates"]


def validate_props(template: str, props: Dict[str, Any]) -> Dict[str, Any]:
    """{props (parsed, defaults filled), fps, durationInFrames, coverFrame}; ValueError with
    the template's own message for an unknown template or bad props."""
    out = _node("schemas.mjs", ["--validate", template], timeout_s=SCHEMA_TIMEOUT_S,
                stdin=json.dumps(props, ensure_ascii=False))
    if not out.pop("ok"):
        raise ValueError(out["error"])
    return out


def build_props(template: str, props: Dict[str, Any], settings: InstagramMCPSettings,
                voice: Optional[str] = None) -> Dict[str, Any]:
    """`props` with `voice` filled from the TTS provider (line timings, plus the audio copied
    to `<media root>/voice/` when there is a voice). Templates without a script, or props
    that already carry a voice, come back unchanged."""
    script = SCRIPTS.get(template)
    if script is None or "voice" in props:
        return props
    lines = [" ".join(line.split()) for line in script(props)]  # one script line per line
    synth = get_provider(settings).synthesize("\n".join(lines), voice)
    filled: Dict[str, Any] = {"lines": [{"text": t.text, "start_s": t.start_s, "end_s": t.end_s}
                                        for t in synth.lines]}
    if synth.audio_path:
        dest = Path(settings.media_root) / "voice" / synth.audio_path.name
        if not dest.is_file():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(synth.audio_path, dest)
        filled["audioSrc"] = media.relative(settings.media_root, dest)
    return {**props, "voice": filled}


_bundle_lock = threading.Lock()
_bundle: Optional[Path] = None


def bundle_dir() -> Path:
    """This process's bundle, built on first use. ponytail: never rebuilt, so restart the
    worker after editing motion/; key it on a hash of motion/src if that bites."""
    global _bundle
    with _bundle_lock:
        if _bundle is None or not (_bundle / "index.html").is_file():
            path = Path(tempfile.gettempdir()) / f"growth-studio-motion-{os.getpid()}"
            _node("render.mjs", ["--bundle-only", "--bundle", path], timeout_s=BUNDLE_TIMEOUT_S)
            atexit.register(shutil.rmtree, path, True)
            _bundle = path
        return _bundle


def _stage_audio(bundle: Path, props: Dict[str, Any], media_root: PathLike) -> Dict[str, Any]:
    """Props for Remotion: a media-path `voice.audioSrc` becomes a file in the bundle."""
    src = (props.get("voice") or {}).get("audioSrc")
    if not src or "://" in src:
        return props
    path = media.resolve(media_root, src)
    if not path.is_file():
        raise ValueError(f"voice audio {src!r} is missing")
    dest = bundle / "public" / "voice" / path.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(path, dest)
    return {**props, "voice": {**props["voice"], "audioSrc": f"public/voice/{path.name}"}}


def _render(template: str, props: Dict[str, Any], out: Path, work: Path, *, timeout_s: float,
            extra: Sequence[Any] = ()) -> Dict[str, Any]:
    props_file = work / f"{out.stem}.props.json"
    props_file.write_text(json.dumps(props, ensure_ascii=False), encoding="utf-8")
    return _node("render.mjs", ["--template", template, "--props", props_file, "--out", out,
                                "--bundle", bundle_dir(), *extra], timeout_s=timeout_s)


def preview_stills(template: str, props: Dict[str, Any], media_root: PathLike,
                   frames: Optional[Sequence[int]] = None) -> List[str]:
    """Render a few PNG stills (default: the cover, then three spread over the video) into
    `<media root>/previews/<props hash>/` so the layout can be checked before a full render.
    Returns their media paths."""
    v = validate_props(template, props)
    last = v["durationInFrames"] - 1
    if frames is None:
        frames = [v["coverFrame"] or 0, last // 3, 2 * last // 3, last]
    if any(not 0 <= f <= last for f in frames):
        raise ValueError(f"frames must lie in 0..{last}")
    # A still plays no sound: leave the voice audio out.
    still_props = {**v["props"]}
    if "voice" in still_props:
        still_props["voice"] = {k: x for k, x in still_props["voice"].items() if k != "audioSrc"}
    folder = Path(media_root) / "previews" / render.recipe_hash([template, still_props])
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    with tempfile.TemporaryDirectory(dir=folder) as work:
        for f in dict.fromkeys(frames):
            out = folder / f"frame-{f}.png"
            _render(template, still_props, out, Path(work), timeout_s=STILL_TIMEOUT_S,
                    extra=["--still", "--frame", f])
            paths.append(media.relative(media_root, out))
    return paths


def render_motion_asset(template: str, props: Dict[str, Any], out: PathLike,
                        media_root: PathLike, *, timeout_s: float) -> Tuple[MediaInfo, int]:
    """Render the master to `out`, then the shared finish (two-pass loudness when there is
    audio). Returns its MediaInfo and the cover time in ms. ValueError for bad props."""
    out = Path(out)
    v = validate_props(template, props)
    staged = _stage_audio(bundle_dir(), v["props"], media_root)
    with tempfile.TemporaryDirectory(prefix="motion-", dir=out.parent) as work:
        raw = Path(work) / "raw.mp4"
        _render(template, staged, raw, Path(work), timeout_s=timeout_s,
                extra=["--concurrency", RENDER_CONCURRENCY])
        if ffmpeg.probe(raw).has_audio:
            recipe.normalize_loudness(raw, out, timeout_s=timeout_s,
                                      log_path=Path(work) / "loudnorm.log")
        else:  # nothing to normalise; QC reports the missing audio
            os.replace(raw, out)
    return ffmpeg.probe(out), round((v["coverFrame"] or 0) * 1000 / v["fps"])


def queue_motion_render(store: CampaignStore, settings: InstagramMCPSettings, *,
                        template: str, props: Dict[str, Any], idea_id: Optional[int] = None,
                        asset_id: Optional[int] = None, caption: Optional[str] = None,
                        voice: Optional[str] = None, actor: str = "agent") -> Dict[str, Any]:
    """Store a motion recipe and queue its render; returns {asset, job} at once (the worker
    renders). New asset for `idea_id`, or a re-render of `asset_id` (failed: same asset;
    ready: a child asset). Runs TTS first when the template has a script and no voice yet."""
    if (idea_id is None) == (asset_id is None):
        raise ValueError("give exactly one of idea_id (new asset) or asset_id (re-render)")
    v = validate_props(template, props)  # before TTS: build_props needs well-formed props
    voiced = build_props(template, v["props"], settings, voice)
    if voiced is not v["props"]:
        v = validate_props(template, voiced)
    env: Dict[str, Any] = {"kind": "motion", "template": template, "props": v["props"]}
    if v["coverFrame"] is not None:  # the publish guard sends it to Instagram as the cover
        env["thumb_offset_ms"] = round(v["coverFrame"] * 1000 / v["fps"])
    if asset_id is not None:
        return render.rerender(store, settings.media_root, asset_id, env, actor=actor)
    idea = store.get_idea(idea_id)
    asset = store.add_asset(idea_id, recipe=env, caption=caption, batch_date=idea["batch_date"])
    return {"asset": asset, "job": render.enqueue_render(store, asset["id"])}

