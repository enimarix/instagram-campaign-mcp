"""
Python side of the Remotion templates in `motion/` (GOAL.md §3.1, §4.1, §5.6).

- `motion/schemas.mjs` exports every template's props schema (JSON Schema, defaults) and
  validates props with the template's own Zod schema: the same check and message as a render.
- `motion/render.mjs` renders a video or a still from a bundle. Bundling is slow and crashes
  when two run at once (step 006a), so this process bundles once, under a lock shared by every
  process on the machine (the worker and the MCP server), and every render reuses that bundle.

Recipes store the voice audio as a media path (`voice.audioSrc`, relative to the media root);
a render copies it into the bundle's `public/` and hands Remotion that URL instead.
Node: `NODE_BIN` (a full path or a command name) overrides `node` on PATH.

Template `CinematicSkit` (style `blender`) is not Remotion: Blender renders it
(src/studio/cinematic.py). The functions below route it there, so callers treat it like any
motion template. Template `Macro3D` (style `macro3d`) is Remotion over Blender plates: the
plates are rendered first (src/studio/macro3d.py) and handed to it as `plate`.
"""

from __future__ import annotations

import atexit
import functools
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..config import InstagramMCPSettings
from ..store import CampaignStore
from . import (  # render.py imports us
    cinematic,
    ffmpeg,
    gpu_lock,
    guard,
    listen,
    macro3d,
    media,
    recipe,
    render,
    styles,
)
from .ffmpeg import MediaInfo, PathLike
from .tts import get_provider

MOTION_DIR = Path(__file__).resolve().parents[2] / "motion"
SCHEMA_TIMEOUT_S = 60.0
BUNDLE_TIMEOUT_S = 300.0
STILL_TIMEOUT_S = 120.0
RENDER_CONCURRENCY = 4  # Chrome tabs per render; 2 renders in parallel (step 006a)


def _concurrency() -> int:
    """Chrome tabs per render: at most half the job's CPUs (171, the heat budget)."""
    return max(1, min(RENDER_CONCURRENCY, guard.heavy_cpus() // 2))
TAIL_CHARS = 2000

def _paper_line(labels: Sequence[Any]) -> str:
    """A PaperStory scene's spoken line: its strips in order, a full stop added where a strip
    ends without punctuation and the next starts a sentence (= sceneLine in
    motion/src/templates/PaperStory/schema.ts)."""
    line = ""
    for label in labels:
        text = label if isinstance(label, str) else label["text"]
        if line and not re.search(r"[.!?…:;,]$", line) and text[:1].isupper():
            line = f"{line}. {text}"
        else:
            line = f"{line} {text}" if line else text
    return line


def _editorial_line(first: str, second: Optional[str] = None) -> str:
    """Two Editorial texts read as one line: where the first ends without punctuation, a full
    stop when the second starts a sentence, else a comma (= joinLine in
    motion/src/templates/Editorial/schema.ts)."""
    if not second:
        return first
    if re.search(r"[.!?…:;,]$", first):
        return f"{first} {second}"
    return f"{first}. {second}" if second[:1].isupper() else f"{first}, {second}"


def _editorial_script(p: Dict[str, Any]) -> List[str]:
    chapters = [c["caption"] if c["scene"] == "anatomy" else _editorial_line(c["title"], c.get("key"))
                for c in p["chapters"]]
    return [_editorial_line(p["hook"]["lead"], p["hook"]["key"]), *chapters,
            _editorial_line(p["payoff"]["lead"], p["payoff"]["key"]),
            *([p["outro"]] if p.get("outro") else [])]


def _cinema_line(parts: Sequence[str]) -> str:
    """A PixelCinema scene's spoken line: its parts with the `*key word*` stars removed,
    joined like `_paper_line` (= joinParts in motion/src/templates/PixelCinema/schema.ts)."""
    return _paper_line([part.replace("*", "") for part in parts if part])


def _cinema_beat(b: Dict[str, Any]) -> str:
    if b["kind"] == "chip":  # the heading is read on the chip that brings it
        return _cinema_line([b.get("title", ""), b["text"]])
    if b["kind"] == "stat":
        return _cinema_line([b["title"], " ".join(filter(None, [b["value"], b.get("unit")])),
                             b.get("label", "")])
    return _cinema_line([b["title"]])


# Script lines (hook first) of templates with a voice, in the order of `voice.lines` (each
# schema's refine). The voice reads the text the viewer sees, as is.
SCRIPTS = {
    "FactQuest": lambda p: [p["hook"], *(f["text"] for f in p["facts"]), p["outro"]],
    "BossBattle": lambda p: [p["hook"], *(r["text"] for r in p["rounds"]), p["verdict"]["text"]],
    "QuizChest": lambda p: [p["hook"], p["question"], p["explanation"], p["cta"]],
    "DialogStory": lambda p: [p["hook"], *(line["text"] for line in p["lines"]),
                              *([p["moral"]] if p.get("moral") else [])],
    "PixelSkit": lambda p: [p["hook"], *(b["line"] for b in p["beats"])],
    "VoxelQuest": lambda p: [p["hook"], *(b["line"] for b in p["beats"]),
                             *([p["outro"]] if p.get("outro") else [])],
    cinematic.TEMPLATE: lambda p: [line["text"] for line in p["lines"]],  # the hook is silent
    "PaperStory": lambda p: [_paper_line(p["hook"]["labels"]),
                             *(_paper_line(b["labels"]) for b in p["beats"]),
                             *([p["outro"]] if p.get("outro") else [])],
    # The title box, then its yellow sub, joined like PaperStory's strips (lineOf in
    # motion/src/templates/Cutaway/schema.ts).
    "Cutaway": lambda p: [_paper_line([s["title"], *([s["sub"]] if s.get("sub") else [])])
                          for s in (p["hook"], *p["beats"], p["payoff"])]
                         + ([p["outro"]] if p.get("outro") else []),
    "Editorial": _editorial_script,
    "PixelCinema": lambda p: [_cinema_line([p["hook"].get("strike", ""), p["hook"]["line"]]),
                              *(_cinema_beat(b) for b in p["beats"]),
                              *([p["outro"]] if p.get("outro") else [])],
    macro3d.TEMPLATE: lambda p: [s["line"] for s in p["scenes"]] + ([p["outro"]] if p.get("outro") else []),
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
        done = guard.run(cmd, cwd=MOTION_DIR, input=stdin, capture_output=True, text=True,
                         encoding="utf-8", timeout=timeout_s)  # low priority (166)
    except subprocess.TimeoutExpired:
        raise MotionError(f"{script} ran past {timeout_s:g} s") from None
    if done.returncode != 0:
        raise MotionError(f"{script} failed: {done.stderr.strip()[-TAIL_CHARS:]}")
    return json.loads(done.stdout.strip().splitlines()[-1])


@functools.lru_cache(maxsize=1)
def list_templates() -> List[Dict[str, Any]]:
    """[{id, style, jsonSchema, defaultProps, description}] (cached: restart after editing
    motion/). `style`: the template's visual style id (motion/src/registry.ts STYLES)."""
    return [*_node("schemas.mjs", [], timeout_s=SCHEMA_TIMEOUT_S)["templates"],
            cinematic.template_info()]


def validate_props(template: str, props: Dict[str, Any]) -> Dict[str, Any]:
    """{props (parsed, defaults filled), fps, durationInFrames, coverFrame, events}; ValueError
    with the template's own message for an unknown template or bad props."""
    if template == cinematic.TEMPLATE:
        return cinematic.validate(props)
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
        filled["audioSrc"] = store_voice(settings, synth.audio_path)
    return {**props, "voice": filled}


def store_voice(settings: InstagramMCPSettings, audio: Path) -> str:
    """Copy synthesised audio into `<media root>/voice/` (once); returns its media path."""
    dest = Path(settings.media_root) / "voice" / audio.name
    if not dest.is_file():
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(audio, dest)
    return media.relative(settings.media_root, dest)


_bundle_lock = threading.Lock()
_bundle: Optional[Path] = None
# Next to the cache the bundler shares between processes (git-ignored with node_modules/).
BUNDLE_LOCK_FILE = MOTION_DIR / "node_modules" / ".growth-studio-bundle.lock"


def bundle_dir() -> Path:
    """This process's bundle, built on first use. ponytail: never rebuilt, so restart the
    worker after editing motion/; key it on a hash of motion/src if that bites."""
    global _bundle
    with _bundle_lock:
        if _bundle is None or not (_bundle / "index.html").is_file():
            path = Path(tempfile.gettempdir()) / f"growth-studio-motion-{os.getpid()}"
            find_node()  # clear error before touching node_modules/
            # Another process may be bundling: wait for it (up to one bundle's time).
            try:
                with gpu_lock.file_lock(BUNDLE_LOCK_FILE, timeout_s=BUNDLE_TIMEOUT_S):
                    _node("render.mjs", ["--bundle-only", "--bundle", path],
                          timeout_s=BUNDLE_TIMEOUT_S)
            except gpu_lock.LockTimeout as e:
                raise MotionError(str(e)) from None
            atexit.register(shutil.rmtree, path, True)
            _bundle = path
        return _bundle


def _stage_audio(bundle: Path, props: Dict[str, Any], media_root: PathLike) -> Dict[str, Any]:
    """Props for Remotion: a media-path `voice.audioSrc` becomes a file in the bundle (as
    every render mixes it: recipe.dialogue_voice)."""
    src = (props.get("voice") or {}).get("audioSrc")
    if not src or "://" in src:
        return props
    path = media.resolve(media_root, src)
    if not path.is_file():
        raise ValueError(f"voice audio {src!r} is missing")
    path = recipe.dialogue_voice(path)
    dest = bundle / "public" / "voice" / path.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(path, dest)
    return {**props, "voice": {**props["voice"], "audioSrc": f"public/voice/{path.name}"}}


def _render(template: str, props: Dict[str, Any], out: Path, work: Path, *, timeout_s: float,
            extra: Sequence[Any] = ()) -> Dict[str, Any]:
    props_file = work / f"{out.stem}.props.json"
    props_file.write_text(json.dumps(props, ensure_ascii=False), encoding="utf-8")
    bundle = bundle_dir()  # bundling is CPU work: before the GPU lock
    # Chrome draws through the GPU (ANGLE): one heavy GPU job at a time (step 145)
    with guard.gpu(f"Remotion {template} render", "remotion"):  # admitted (166)
        return _node("render.mjs", ["--template", template, "--props", props_file, "--out", out,
                                    "--bundle", bundle, *extra], timeout_s=timeout_s)


def preview_stills(template: str, props: Dict[str, Any], media_root: PathLike,
                   frames: Optional[Sequence[int]] = None) -> List[str]:
    """Render a few PNG stills (default: the cover, then three spread over the video) into
    `<media root>/previews/<props hash>/` so the layout can be checked before a full render.
    Returns their media paths."""
    if template == cinematic.TEMPLATE:
        return cinematic.preview_stills(props, media_root, frames, render.recipe_hash)
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
    still_props.pop("plate", None)  # Macro3D: the studio's own plates only, never one from the props
    folder = Path(media_root) / "previews" / render.recipe_hash([template, still_props])
    folder.mkdir(parents=True, exist_ok=True)
    plates = {}
    if template == macro3d.TEMPLATE:
        plates = macro3d.plate_stills(v["plates"], frames, folder, timeout_s=STILL_TIMEOUT_S)
    paths = []
    with tempfile.TemporaryDirectory(dir=folder) as work:
        for f in dict.fromkeys(frames):
            out = folder / f"frame-{f}.png"
            props = still_props
            if f in plates:  # Macro3D: the Blender picture under this frame
                props = {**still_props, "plate": macro3d.stage(
                    bundle_dir(), plates[f], f"{folder.name}-{f}.png")}
            _render(template, props, out, Path(work), timeout_s=STILL_TIMEOUT_S,
                    extra=["--still", "--frame", f])
            paths.append(media.relative(media_root, out))
    return paths


def render_motion_asset(template: str, props: Dict[str, Any], out: PathLike,
                        media_root: PathLike, *, timeout_s: float
                        ) -> Tuple[MediaInfo, int, List[Dict[str, Any]], List[Dict[str, float]]]:
    """Render the master to `out`, then the shared finish (two-pass loudness when there is
    audio). Returns its MediaInfo, the cover time in ms, its timeline (the template's own
    events, motion/src/lib/events.ts, compressed) and where the voice plays (voiceParts in
    motion/src/registry.ts, for the QC's listening). ValueError for bad props."""
    out = Path(out)
    if template == cinematic.TEMPLATE:
        def card(props: Dict[str, Any], backdrop: Optional[Path]) -> Optional[Path]:
            try:
                return render_end_card(media_root, props, backdrop, timeout_s=timeout_s)
            except MotionError:  # Remotion unavailable: the recipe draws the static card
                return None
        return cinematic.render_asset(props, out, media_root, timeout_s=timeout_s, end_card=card)
    v = validate_props(template, props)
    staged = _stage_audio(bundle_dir(), v["props"], media_root)
    if template == macro3d.TEMPLATE:  # the Blender plates first, under the picture
        track = media.resolve(media_root, macro3d.render_plates(v["plates"], media_root,
                                                               timeout_s=timeout_s))
        staged = {**staged, "plate": macro3d.stage(bundle_dir(), track, track.name)}
    with tempfile.TemporaryDirectory(prefix="motion-", dir=out.parent) as work:
        raw = Path(work) / "raw.mp4"
        _render(template, staged, raw, Path(work), timeout_s=timeout_s,
                extra=["--concurrency", _concurrency()])
        if ffmpeg.probe(raw).has_audio:  # a voiced video is normalised by its voice (161)
            voice = listen.voice_track({"kind": "motion", "props": v["props"]}, media_root)
            recipe.normalize_loudness(raw, out, timeout_s=timeout_s,
                                      log_path=Path(work) / "loudnorm.log",
                                      voice=voice and recipe.dialogue_voice(voice))
        else:  # nothing to normalise; QC reports the missing audio
            os.replace(raw, out)
    return (ffmpeg.probe(out), round((v["coverFrame"] or 0) * 1000 / v["fps"]),
            recipe.compress_timeline(v["events"]), v.get("voiceParts") or listen.VOICE_FROM_START)


def render_end_card(media_root: PathLike, props: Dict[str, Any], backdrop: Optional[Path] = None,
                    *, timeout_s: float) -> Path:
    """The animated end card (motion `EndCard`, step 137) as a clip, rendered once and cached
    as `<media root>/endcards/<key>.mp4`, the key hashing the props and the backdrop's bytes
    (the live card animates over `backdrop`, the video's last frame). MotionError when Node or
    Remotion fails (the recipe then draws the static card)."""
    picture = hashlib.sha256(backdrop.read_bytes()).hexdigest()[:16] if backdrop else None
    out = Path(media_root) / "endcards" / f"{render.recipe_hash([props, picture])}.mp4"
    if out.is_file():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    staged = dict(props)
    if backdrop:  # into the bundle, like the voice audio (_stage_audio)
        name = f"{picture}{backdrop.suffix}"
        dest = bundle_dir() / "public" / "endcards" / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(backdrop, dest)
        staged["backdrop"] = f"public/endcards/{name}"
    with tempfile.TemporaryDirectory(prefix="endcard-", dir=out.parent) as work:
        clip = Path(work) / "card.mp4"
        _render("EndCard", staged, clip, Path(work), timeout_s=timeout_s,
                extra=["--concurrency", _concurrency()])
        os.replace(clip, out)  # atomic: a parallel render of the same card is harmless
    return out


def queue_motion_render(store: CampaignStore, settings: InstagramMCPSettings, *,
                        template: str, props: Dict[str, Any], idea_id: Optional[int] = None,
                        asset_id: Optional[int] = None, caption: Optional[str] = None,
                        voice: Optional[str] = None, actor: str = "agent") -> Dict[str, Any]:
    """Store a motion recipe and queue its render; returns {asset, job} at once (the worker
    renders). New asset for `idea_id`, or a re-render of `asset_id` (failed: same asset;
    ready: a child asset). Runs TTS first when the template has a script and no voice yet."""
    if (idea_id is None) == (asset_id is None):
        raise ValueError("give exactly one of idea_id (new asset) or asset_id (re-render)")
    # 138: the template must be in the idea's style (one without takes the template's)
    styles.check_template(store, store.get_idea(
        idea_id if idea_id is not None else store.get_asset(asset_id)["idea_id"]), template)
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

