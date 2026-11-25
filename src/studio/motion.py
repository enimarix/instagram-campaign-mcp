"""
Python side of the Remotion templates in `motion/` (GOAL.md §3.1, §4.1, §5.6).

- `motion/schemas.mjs` exports every template's props schema (JSON Schema, defaults) and
  validates props with the template's own Zod schema: the same check and message as a render.
- `motion/render.mjs` renders a video or a still from a bundle. Bundling is slow and crashes
  when two run at once (step 006a), so this process bundles once, under a lock shared by every
  process on the machine (the worker and the MCP server), and every render reuses that bundle.

Recipes store the voice audio as a media path (`voice.audioSrc`, relative to the media root);
a render copies it into the bundle's `public/` and hands Remotion that URL instead. Library
sounds (`ov:<id>` in sfx props, src/studio/sfx.py) are copied there too.
Node: `NODE_BIN` (a full path or a command name) overrides `node` on PATH.

Template `CinematicSkit` (style `blender`) is not Remotion: Blender renders it
(src/studio/cinematic.py). The functions below route it there, so callers treat it like any
motion template. Template `Macro3D` (style `macro3d`) is Remotion over Blender plates: the
plates are rendered first (src/studio/macro3d.py) and handed to it as `plate`. Template
`SitcomSkit` (style `sitcom`) is Remotion over the troupe's Blender shots: its timed parts become
a shot list (src/studio/sitcom.py, validated with the props), rendered first and handed over as
`plate` too; its character lines get their own voices.
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
    music,
    recipe,
    render,
    sfx,
    sitcom,
    styles,
    tts,
    voices,
)
from .assets import checked_fields, clean_caption
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
        # ElevenLabs tags (204) never change the join: tagged and plain lines must match
        if (line and not re.search(r"[.!?…:;,]$", tts.strip_tags(line))
                and tts.strip_tags(text)[:1].isupper()):
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
    if re.search(r"[.!?…:;,]$", tts.strip_tags(first)):  # tags never change the join (204)
        return f"{first} {second}"
    return f"{first}. {second}" if tts.strip_tags(second)[:1].isupper() else f"{first}, {second}"


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
    # The narrator: the hook, every beat's line, the outro (character lines: sitcom.voice_says).
    sitcom.TEMPLATE: lambda p: [p["hook"], *(b["line"] for s in p["scenes"] for b in s["beats"]),
                                *([p["outro"]] if p.get("outro") else [])],
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
    if template == sitcom.TEMPLATE:  # the troupe checks the cast, sets, spots and actions
        out["shots"] = sitcom.shot_list(out["props"], out["plates"])
    return out


def strip_props(value: Any, spoken: Sequence[str] = ()) -> Any:
    """`value` (props) with ElevenLabs audio tags taken out of the strings the voice reads
    (each one a part of a `spoken` line, raw_lines): the viewer never sees them (step 204);
    the voice gets them from tagged_lines. Other strings (sources, titles) stay as written."""
    if isinstance(value, str):
        if not tts.TAG.search(value):
            return value
        flat = " ".join(value.replace("*", "").split())  # PixelCinema's *key word* stars
        return tts.strip_tags(value) if any(flat in line for line in spoken) else value
    if isinstance(value, list):
        return [strip_props(v, spoken) for v in value]
    if isinstance(value, dict):
        return {k: strip_props(v, spoken) for k, v in value.items()}
    return value


def raw_lines(template: str, props: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    """(narrator lines, sitcom character lines) of `props` as written, tags kept; ([], [])
    when the props do not fit the template yet (validate_props says why)."""
    try:
        spoken = [" ".join(line.split()) for line in SCRIPTS[template](props)]
        says = ([" ".join(s["text"].split()) for s in sitcom.says(props)]
                if template == sitcom.TEMPLATE else [])
    except (KeyError, TypeError, AttributeError):
        return [], []
    return spoken, says


def tagged_lines(template: str, props: Dict[str, Any]) -> Dict[str, List[str]]:
    """The voice's own lines of `props` as the agent wrote them, audio tags kept, for the
    voice todo: {spoken: narrator lines, spoken_says: sitcom character lines}; only those
    that carry a tag ({} when none does, or the props do not fit the template yet)."""
    out: Dict[str, List[str]] = {}
    spoken, says = raw_lines(template, props)
    if any(tts.TAG.search(line) for line in spoken):
        out["spoken"] = spoken
    if any(tts.TAG.search(line) for line in says):
        out["spoken_says"] = says
    return out


def voiced_by(synths: List[Any]) -> Optional[Dict[str, Any]]:
    """What spoke a video (the asset page's badge): {engine, voice, fallback}, the
    narrator's engine (the last synthesis), a fallback reason when any engine fell back."""
    spoke = [s for s in synths if getattr(s, "audio_path", None)]
    if not spoke:
        return None
    reasons = [s.fallback for s in spoke if getattr(s, "fallback", None)]
    return {"engine": getattr(spoke[-1], "provider", None), "voice": getattr(spoke[-1], "voice", None),
            "fallback": reasons[0] if reasons else None}


def build_props(template: str, props: Dict[str, Any], settings: InstagramMCPSettings,
                voice: Optional[str] = None,
                cast: Optional[Dict[str, Tuple[str, str]]] = None,
                spoken: Optional[List[str]] = None, spoken_says: Optional[List[str]] = None,
                report: Optional[List[Any]] = None) -> Dict[str, Any]:
    """`props` with `voice` filled from the TTS provider (line timings, plus the audio copied
    to `<media root>/voice/` when there is a voice). Templates without a script, or props
    that already carry a voice, come back unchanged. `cast`: the sitcom's character voices
    (voices.say_cast). `spoken` / `spoken_says`: the same lines with audio tags (tagged_lines),
    used when they still match the props' lines one for one. `report` collects every
    Synthesis made (voiced_by)."""
    script = SCRIPTS.get(template)
    if script is None:
        return props
    provider = get_provider(settings)  # one per video: an engine that failed stays skipped
    if template == sitcom.TEMPLATE:  # each character line in its own voice
        props = sitcom.voice_says(props, settings, voice, cast, spoken_says, report, provider)
    if "voice" in props:
        return props
    lines = [" ".join(line.split()) for line in script(props)]  # one script line per line
    lines = tts.retag(lines, spoken)  # the tags ride along; the timings come back without them
    synth = provider.synthesize("\n".join(lines), voice)
    if report is not None:
        report.append(synth)
    filled: Dict[str, Any] = {"lines": [{"text": t.text, "start_s": t.start_s, "end_s": t.end_s}
                                        for t in synth.lines]}
    if synth.audio_path:
        filled["audioSrc"] = store_voice(settings, synth.audio_path)
    return {**props, "voice": filled}


def voice_pending(template: str, props: Dict[str, Any]) -> bool:
    """Whether build_props would call the TTS provider for these props."""
    if template not in SCRIPTS:
        return False
    if template == sitcom.TEMPLATE and any("seconds" not in say for say in sitcom.says(props)):
        return True
    return "voice" not in props


def voice_recipe(env: Dict[str, Any], settings: InstagramMCPSettings, todo: Dict[str, Any],
                 v: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The motion recipe `env` with its voice-over made (build_props, `todo` as in
    render.VoiceTodo), then cut on the Instagram track when it has one, and its cover time.
    `v`: validate_props of env's props when the caller has it. The render job runs this for
    a recipe queued with `voice_todo` (step 188a), queue_motion_render for the others."""
    template = env["template"]
    report: List[Any] = []
    voiced = build_props(template, env["props"], settings, todo.get("voice"), todo.get("cast"),
                         todo.get("spoken"), todo.get("spoken_says"), report)
    if v is None or voiced is not v["props"]:
        v = validate_props(template, voiced)
    env = {**env, "props": v["props"]}
    by = voiced_by(report)
    if by:  # the asset page's badge: which engine spoke, and why it fell back
        env["voiced_by"] = by
    if todo.get("music_audio_id"):  # the lines on the track's beat; publish attaches the track
        props, env["ig_audio"] = music.apply(v["props"], settings.media_root,
                                             todo["music_audio_id"])
        v = validate_props(template, props)
        env["props"] = v["props"]
    if v["coverFrame"] is not None:  # the publish guard sends it to Instagram as the cover
        env["thumb_offset_ms"] = round(v["coverFrame"] * 1000 / v["fps"])
    return env


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
            prune_bundles(path.parent)
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


def prune_bundles(folder: Path) -> None:
    """Delete the bundles in `folder` of processes gone without their atexit (killed, a crash,
    a power cut: 28 of them held 1.8 GB of %TEMP%, 2026-11-25)."""
    from ..agent import proc  # stdlib only

    for old in folder.glob("growth-studio-motion-*"):
        pid = old.name.rsplit("-", 1)[1]
        if pid.isdigit() and int(pid) != os.getpid() and proc.started(int(pid)) is None:
            shutil.rmtree(old, ignore_errors=True)


def _stage_audio(bundle: Path, props: Dict[str, Any], media_root: PathLike) -> Dict[str, Any]:
    """Props for Remotion: a media-path `voice.audioSrc` becomes a file in the bundle (as
    every render mixes it: recipe.dialogue_voice)."""
    src = (props.get("voice") or {}).get("audioSrc")
    if not src or "://" in src:
        return props
    path = media.resolve(media_root, src)
    if not path.is_file():
        raise ValueError(f"voice audio {src!r} is missing")
    return {**props, "voice": {**props["voice"], "audioSrc": _stage_voice(bundle, path)}}


def _stage_voice(bundle: Path, path: Path) -> str:
    """A voice file, mixed as every render mixes it (recipe.dialogue_voice), into the bundle."""
    path = recipe.dialogue_voice(path)
    dest = bundle / "public" / "voice" / path.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(path, dest)
    return f"public/voice/{path.name}"


def _stage_says(bundle: Path, props: Dict[str, Any], media_root: PathLike) -> Dict[str, Any]:
    """SitcomSkit: the character lines' audio into the bundle too."""
    def stage(b: Dict[str, Any]) -> Dict[str, Any]:
        src = (b.get("say") or {}).get("audioSrc")
        if not src or "://" in src:
            return b
        path = media.resolve(media_root, src)
        if not path.is_file():
            raise ValueError(f"character line audio {src!r} is missing")
        return {**b, "say": {**b["say"], "audioSrc": _stage_voice(bundle, path)}}
    return {**props, "scenes": [{**s, "beats": [stage(b) for b in s["beats"]]}
                                for s in props["scenes"]]}


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
    still_props.pop("plate", None)  # Macro3D / SitcomSkit: the studio's own plates only, never the props'
    for say in sitcom.says(still_props) if template == sitcom.TEMPLATE else ():
        say.pop("audioSrc", None)
    if sfx.refs(still_props):  # silent in a still, but the file must load
        sfx.stage(bundle_dir() / "public", still_props)
    folder = Path(media_root) / "previews" / render.recipe_hash([template, still_props])
    folder.mkdir(parents=True, exist_ok=True)
    plates = {}
    if template == macro3d.TEMPLATE:
        plates = macro3d.plate_stills(v["plates"], frames, folder, timeout_s=STILL_TIMEOUT_S)
    elif template == sitcom.TEMPLATE:
        plates = sitcom.track_stills(v["shots"], {f: f / v["fps"] for f in frames}, folder,
                                     timeout_s=STILL_TIMEOUT_S * 4)
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
    sfx.stage(bundle_dir() / "public", staged)
    if template == macro3d.TEMPLATE:  # the Blender plates first, under the picture
        track = media.resolve(media_root, macro3d.render_plates(v["plates"], media_root,
                                                               timeout_s=timeout_s))
        staged = {**staged, "plate": macro3d.stage(bundle_dir(), track, track.name)}
    elif template == sitcom.TEMPLATE:  # the troupe's shots first, then their voices
        track = media.resolve(media_root, sitcom.render_track(v["shots"], media_root,
                                                              timeout_s=timeout_s))
        staged = {**_stage_says(bundle_dir(), staged, media_root),
                  "plate": macro3d.stage(bundle_dir(), track, track.name)}
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


@functools.lru_cache(maxsize=1)
def endcards_hash() -> str:
    """The end cards' code (motion/src/endcards): an edit renders the cards again, like
    troupe.engine_hash. Read once per process, like the bundle it renders with (bundle_dir).
    ponytail: the shared motion/src code they import (brand.ts, components) is not hashed."""
    h = hashlib.sha256()
    for f in sorted((MOTION_DIR / "src" / "endcards").rglob("*")):
        if f.is_file():
            h.update(f.name.encode() + f.read_bytes())
    return h.hexdigest()[:12]


def render_end_card(media_root: PathLike, props: Dict[str, Any], backdrop: Optional[Path] = None,
                    *, timeout_s: float) -> Path:
    """The animated end card (motion `EndCard`, step 137) as a clip, rendered once and cached
    as `<media root>/endcards/<key>.mp4`, the key hashing the props, the backdrop's bytes
    (the live card animates over `backdrop`, the video's last frame) and the cards' code
    (endcards_hash). MotionError when Node or Remotion fails (the recipe then draws the static
    card)."""
    picture = hashlib.sha256(backdrop.read_bytes()).hexdigest()[:16] if backdrop else None
    key = render.recipe_hash([props, picture, endcards_hash()])
    out = Path(media_root) / "endcards" / f"{key}.mp4"
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
                        voice: Optional[str] = None, music_audio_id: Optional[str] = None,
                        actor: str = "agent", plan: bool = False,
                        description: Optional[str] = None) -> Dict[str, Any]:
    """Store a motion recipe and queue its render; returns {asset, job} at once (the worker
    renders). New asset for `idea_id`, or a re-render of `asset_id` (failed: same asset;
    ready: a child asset). Never waits for the voice: a template with a script and no voice yet
    is stored with `voice_todo` (the voice checked on now) and the render job makes it.
    `music_audio_id`: an Instagram track (fetched with music.fetch) the video is cut to and
    published with, in place of the template's bed (step 178). `description` (checked as
    edit_asset does) is stored on the new asset or the re-render's (193).
    `plan` (188b): a new asset `planned` with its recipe, caption and description, and no
    job (job None): nothing renders or is voiced until the owner releases it
    (src/studio/planned.py); refused past the places left for Claude's ideas in its batch
    (planned.take_place, 188c). The night run (packet.RUNS kind `produce`, running) renders
    only the owner's items: a new video of an idea no work order made is refused unless
    planned (the owner reviews Claude's own ideas before anything renders)."""
    if (idea_id is None) == (asset_id is None):
        raise ValueError("give exactly one of idea_id (new asset) or asset_id (re-render)")
    if plan and asset_id is not None:
        raise ValueError("plan a new video (idea_id), not a re-render")
    if not plan and asset_id is None and actor == "agent":
        from ..agent.packet import RUNS  # here: the packet imports most of the studio

        night = [p for p, (kind, _) in RUNS.items() if kind == "produce"]
        with store._tx() as c:
            own = c.execute(
                "SELECT NOT EXISTS (SELECT 1 FROM work_orders WHERE idea_id = ?) AND EXISTS"
                " (SELECT 1 FROM agent_runs WHERE status = 'running' AND playbook IN"
                f" ({','.join('?' * len(night))}))", (idea_id, *night)).fetchone()[0]
        if own:
            raise ValueError(f"idea {idea_id} is your own idea and this is the night run: it"
                             " only writes ideas; render_motion(..., plan=True,"
                             " description=...) puts it on the owner's Planning page")
    # 193: the description is stored for every video; a queued one's caption is written
    # again at submit_asset
    fields = checked_fields("planned" if plan else "rendering", **{k: x for k, x in (
        ("caption", caption if plan else None), ("description", description)) if x is not None})
    idea = store.get_idea(idea_id if idea_id is not None
                          else store.get_asset(asset_id)["idea_id"])
    old = (store.get_asset(asset_id)["recipe"] or {}) if asset_id is not None else {}
    keep = old.get("voice_todo") or old.get("voiced_with")  # a re-render keeps its tags (204)
    env = motion_recipe(store, settings, idea, template, props, voice, music_audio_id, plan,
                        keep=keep)
    if asset_id is not None:
        out = render.rerender(store, settings.media_root, asset_id, env, actor=actor)
        if fields:  # a re-render's description: what the new version changed
            out["asset"] = store.update_asset(out["asset"]["id"], **fields)
        return out
    if plan:
        from .planned import take_place  # here: planned imports this module

        take_place(store, settings, idea["batch_date"])  # 188c: only the batch's rest
        asset = store.add_asset(idea_id, recipe=env, batch_date=idea["batch_date"],
                                status="planned", **fields)
        return {"asset": asset, "job": None}
    asset = store.add_asset(idea_id, recipe=env, caption=clean_caption(caption),
                            batch_date=idea["batch_date"], **fields)
    return {"asset": asset, "job": render.enqueue_render(store, asset["id"])}


def motion_recipe(store: CampaignStore, settings: InstagramMCPSettings, idea: Dict[str, Any],
                  template: str, props: Dict[str, Any], voice: Optional[str],
                  music_audio_id: Optional[str], plan: bool = False,
                  keep: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The checked recipe queue_motion_render stores (ValueError names the problem). `plan`:
    always with `voice_todo`, so the voice, the track and the cover are made at render time
    and an edit of a planned card (planned.edit) only re-runs this. `keep`: the voice todo
    being rebuilt: its tagged lines stay when the new props carry none (tts.retag drops a
    line's tags once the line itself changed)."""
    styles.check_template(store, idea, template)  # 138: the template in the idea's style
    if music_audio_id and template in (cinematic.TEMPLATE, sitcom.TEMPLATE):
        # ponytail: the Blender engines time shots and character voices off the narrator
        # lines; moving the narrator alone would desync them. Remotion templates only.
        raise ValueError(f"{template} cannot take an Instagram track yet: use its own bed")
    tagged = tagged_lines(template, props) or {  # 204: the voice hears the tags, never the viewer
        k: keep[k] for k in ("spoken", "spoken_says") if keep and keep.get(k)}
    narrator, says = raw_lines(template, props)
    props = strip_props(props, [line.replace("*", "") for line in narrator + says])
    v = validate_props(template, props)  # at once: the agent gets bad props now, not at render
    cast = None
    if tts.voiced(settings):  # only voices the owner keeps on (Voix page)
        if "voice" not in v["props"]:  # a new voice-over; a re-render keeps its own audio
            voice = voices.check_voice(store, voice)
        elif voice is None:  # the sitcom compares character voices with the narrator's
            # ponytail: the props keep no voice id, so the default stands in for the
            # narrator; storing the id in the recipe would make this exact.
            voice = voices.default_voice(store)
        if template == sitcom.TEMPLATE:
            cast = voices.say_cast(store)
    env: Dict[str, Any] = {"kind": "motion", "template": template, "props": v["props"]}
    credits = sfx.credits(v["props"])  # ValueError for a library sound not cached (150)
    if credits:  # the caption must carry them: submit_asset adds them, the publish guard checks
        env["sfx_credits"] = credits
    todo = {"voice": voice, "cast": cast, "music_audio_id": music_audio_id, **tagged}
    if plan or (tts.voiced(settings) and voice_pending(template, v["props"])):
        if music_audio_id:  # what music.apply can tell before the voice exists
            music.load_beats(settings.media_root, music_audio_id)
        # 188a: the render job makes the voice (render.voice_first), in line order
        env["voice_todo"] = {k: x for k, x in todo.items() if x is not None}
        return env
    # nothing to synthesise (no script, a voice already, or the reading estimate)
    return voice_recipe(env, settings, todo, v)
