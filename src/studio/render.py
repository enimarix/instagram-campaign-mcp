"""
Render jobs (GOAL.md §3.1, §3.2, §4.3): render an asset from its recipe into its folder.

`assets.recipe` is an envelope (docs/DECISIONS.md):
  {"kind": "ffmpeg", "recipe": <Recipe>, "inputs": {"source": <media path>, ...}}  Track A
  {"kind": "motion", "template": <id>, "props": {...}}                             Track B
plus an optional `thumb_offset_ms` (cover frame, also sent to Instagram) and `voice_todo` (a
voice-over the job makes before rendering, step 188a: VoiceTodo), kept as `voiced_with` once
made (step 191: the check run's re-render takes the same voice and script); a remix may carry
its source's `clip_timeline` (step 119) for the asset's timeline. Motion recipes
render through src/studio/motion.py (Remotion); their cover is the template's cover frame.

A render writes, into media.asset_dir(): `video.mp4` (the master), `preview.mp4` (light copy
the inbox plays), `poster.jpg` (cover frame) and `thumb.jpg`. The worker render loop
(src/worker.py) claims jobs and calls run_job() in a thread.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import timedelta
from pathlib import Path
from typing import Annotated, Any, Callable, Dict, List, Literal, Optional, Tuple, Union

import structlog
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator

from ..config import InstagramMCPSettings, get_settings
from ..store import CampaignStore, parse_iso, to_iso, utcnow
from . import ffmpeg, gpu_lock, guard, media, motion, music
from .assets import DESCRIPTION_CHARS, InvalidTransition, transition
from .ffmpeg import MediaInfo, PathLike
from .qc import run_qc
from .recipe import DEFAULT_PRESET, DEFAULT_TIMEOUT_S, Recipe, recipe_timeline, render
from .tts import TTSError

logger = structlog.get_logger(__name__)

MAX_ATTEMPTS = 3
# A machine failure (machine_failure, step 197) waits and retries without counting against
# the video: the job keeps its place in the line behind a timer of MACHINE_BACKOFF_MIN[n]
# (the last one after that), its failure "machine <n>/<MACHINE_RETRIES>: <reason>".
MACHINE_RETRIES = 6
MACHINE_BACKOFF_MIN = (5, 15, 45)
MACHINE = "machine"
_MACHINE_N = re.compile(rf"^{MACHINE} (\d+)/")
# While the voice model is warm, a job that made a voice also makes the voices of the next
# waiting voiced renders (voice_ahead): one model load per batch, not one per video.
VOICE_AHEAD = 6
FAILURE_CHARS = 2000
POSTER_AT_S = 1.0  # cover frame when the recipe names none
PREVIEW_ARGS = ("-vf", "scale=720:1280", "-c:v", "libx264", "-b:v", "1500k", "-maxrate", "1500k",
                "-bufsize", "3000k", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k",
                "-movflags", "+faststart")
THUMB_WIDTH = 270
WARNING_CHARS = 300

Progress = Callable[[float], None]


class IgAudio(BaseModel):
    """An Instagram track attached at publish (src/studio/music.py), never in the file."""
    model_config = ConfigDict(extra="forbid")
    audio_id: str = Field(pattern=r"^\d{5,25}$")
    title: Optional[str] = None
    artist: Optional[str] = None
    track: str  # media path of the local copy: beats and the review preview only
    audio_volume: int = Field(ge=1, le=100)
    video_volume: int = Field(100, ge=1, le=100)


class VoiceTodo(BaseModel):
    """A voice-over the render job makes before rendering (step 188a, voice_first): queueing
    never waits for the voice service. The lines are the recipe's own text (motion: the
    template's script, motion.SCRIPTS; remix: `script`)."""
    model_config = ConfigDict(extra="forbid")
    voice: Optional[str] = None  # checked on at queue time; None = the engine's default
    cast: Optional[Dict[str, List[str]]] = None  # SitcomSkit character voices (voices.say_cast)
    music_audio_id: Optional[str] = None  # motion: the Instagram track, applied once voiced
    script: Optional[str] = None  # remix: the voice-over text
    max_s: Optional[float] = None  # remix: the trimmed clip it must fit in
    # 204: motion lines with ElevenLabs audio tags (motion.tagged_lines): narrator, sitcom says
    spoken: Optional[List[str]] = None
    spoken_says: Optional[List[str]] = None


class _Envelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    thumb_offset_ms: Optional[int] = Field(None, ge=0)
    ig_audio: Optional[IgAudio] = None
    voice_todo: Optional[VoiceTodo] = None
    voiced_with: Optional[VoiceTodo] = None  # the voice_todo its voice was made from (191)
    voiced_by: Optional[Dict[str, Any]] = None  # 204: {engine, voice, fallback} (motion.voiced_by)


class FfmpegRecipe(_Envelope):
    kind: Literal["ffmpeg"]
    recipe: Recipe
    inputs: Dict[str, str]
    clip_timeline: Optional[List[Dict[str, Any]]] = None  # the source's (remix, step 119)

    @field_validator("inputs")
    @classmethod
    def _source(cls, v: Dict[str, str]) -> Dict[str, str]:
        if "source" not in v:
            raise ValueError("inputs must contain 'source'")
        return v


class MotionRecipe(_Envelope):
    kind: Literal["motion"]
    template: str
    props: Dict[str, Any] = {}
    sfx_credits: Optional[List[str]] = None  # CC BY library sounds' credit lines (150, 179)


_ENVELOPE = TypeAdapter(Annotated[Union[FfmpegRecipe, MotionRecipe], Field(discriminator="kind")])


def validate_recipe(value: Any, media_root: PathLike) -> Dict[str, Any]:
    """The envelope as stored, or ValueError (unknown kind or op, input path outside the root)."""
    env = _ENVELOPE.validate_python(value)
    if isinstance(env, FfmpegRecipe):
        for rel in env.inputs.values():
            media.resolve(media_root, rel)
    if env.ig_audio:
        media.resolve(media_root, env.ig_audio.track)
    return env.model_dump(mode="json", exclude_none=True)


def recipe_hash(recipe: Any) -> str:
    return hashlib.sha256(json.dumps(recipe, sort_keys=True).encode()).hexdigest()[:16]


def enqueue_render(store: CampaignStore, asset_id: int, *, key: Optional[str] = None
                   ) -> Dict[str, Any]:
    """Queue a render of the asset's current recipe; the same key gives the same job, so a
    restarted batch never renders an asset twice. A finished (failed or done) job is queued
    again only when the asset is back in `rendering` (a re-render of the same recipe, e.g.
    after a failed QC): as a new arrival, counted (store.requeue_render_job), unless it
    failed for the machine (machine_wait: a machine problem is not the video's fault)."""
    asset = store.get_asset(asset_id)
    job = store.add_render_job(asset_id, key or f"{asset_id}:{recipe_hash(asset['recipe'])}")
    if job["state"] in ("failed", "done") and asset["status"] == "rendering":
        job = store.requeue_render_job(job["id"], count=not (job["failure"] or "").startswith(
            f"{MACHINE}:"))
    return job


def rerender(store: CampaignStore, media_root: PathLike, asset_id: int, recipe: Any,
             *, actor: str = "owner") -> Dict[str, Any]:
    """Render an asset again with an edited recipe. From `failed` the asset itself goes back
    to `rendering`; from `ready` or `revision_requested` a new child asset (parent_asset_id) is
    rendered, so the one under review is never overwritten. A video the check run dropped
    is revived first (checks.revive, 200). Returns {asset, job}."""
    from . import checks  # here: checks imports remix, which imports this module

    env = validate_recipe(recipe, media_root)
    asset = check_rerender(store.get_asset(asset_id))
    checks.revive(store, asset_id)
    if asset["status"] == "failed":
        transition(store, asset_id, "rendering", actor=actor)
        asset = store.update_asset(asset_id, recipe=env)
    else:
        asset = store.add_asset(
            asset["idea_id"], parent_asset_id=asset_id, recipe=env,
            batch_date=asset["batch_date"], caption=asset["caption"],
            audio_name=asset["audio_name"], best_before=asset["best_before"])
    return {"asset": asset, "job": enqueue_render(store, asset["id"])}


def check_rerender(asset: Dict[str, Any]) -> Dict[str, Any]:
    """The asset, or InvalidTransition when rerender() would refuse it."""
    if asset["status"] not in ("failed", "ready", "revision_requested"):
        raise InvalidTransition(f"asset {asset['id']} is {asset['status']}: only failed, ready"
                                " or revision_requested assets can be re-rendered")
    return asset


def render_files(asset: Dict[str, Any], media_root: PathLike, progress: Progress, *,
                 preset: str = DEFAULT_PRESET, timeout_s: float = DEFAULT_TIMEOUT_S
                 ) -> Tuple[MediaInfo, Dict[str, Any]]:
    """Render the master, preview, poster and thumbnail; return the master's MediaInfo and
    the asset fields (relative paths, and the timeline: what happens when, step 110), plus
    for QC `render_warnings` when the render had to fall back (the static end card) and
    `voice_parts` (where a motion template plays the voice, src/studio/listen.py)."""
    env = _ENVELOPE.validate_python(asset["recipe"])
    folder = media.asset_dir(media_root, asset["batch_date"], asset["id"])
    video, preview = folder / "video.mp4", folder / "preview.mp4"
    poster, thumb = folder / "poster.jpg", folder / "thumb.jpg"
    cover_ms = env.thumb_offset_ms
    warnings: List[str] = []
    parts = None  # the voice from 0
    if isinstance(env, MotionRecipe):
        info, template_cover_ms, timeline, parts = motion.render_motion_asset(
            env.template, env.props, video, media_root, timeout_s=timeout_s)
        cover_ms = template_cover_ms if cover_ms is None else cover_ms
    else:
        inputs = {k: media.resolve(media_root, v) for k, v in env.inputs.items()}

        def end_card(props: Dict[str, Any], backdrop: Optional[Path]) -> Optional[Path]:
            try:
                return motion.render_end_card(media_root, props, backdrop, timeout_s=timeout_s)
            except motion.MotionError as e:  # Remotion unavailable: the static card, flagged
                warnings.append(f"static end card (fallback): the animated card could not be"
                                f" rendered: {e}"[:WARNING_CHARS])
                return None

        info = render(env.recipe, inputs, video, timeout_s=timeout_s, preset=preset,
                      end_card=end_card)
        timeline = recipe_timeline(env.recipe, info.duration, env.clip_timeline or ())
    progress(0.8)
    mix: List[Any] = []
    if env.ig_audio:  # the review preview plays the track as Instagram will; the master stays clean
        mix = ["-i", media.resolve(media_root, env.ig_audio.track),
               *music.preview_args(env.ig_audio.model_dump())]
    ffmpeg.run(["-i", video, *mix, *PREVIEW_ARGS, "-preset", preset, preview],
               timeout_s=timeout_s)
    progress(0.9)
    at = POSTER_AT_S if cover_ms is None else cover_ms / 1000
    at = max(min(at, info.duration - 0.1), 0.0)  # a frame that exists in short clips
    ffmpeg.run(["-ss", f"{at:.3f}", "-i", video, "-frames:v", "1", "-q:v", "3", poster],
               timeout_s=timeout_s)
    ffmpeg.run(["-i", poster, "-vf", f"scale={THUMB_WIDTH}:-2", "-q:v", "4", thumb],
               timeout_s=timeout_s)
    paths: Dict[str, Path] = {"file_path": video, "preview_path": preview,
                              "poster_path": poster, "thumbnail_path": thumb}
    return info, {**{k: media.relative(media_root, p) for k, p in paths.items()},
                  "timeline": timeline, **({"render_warnings": warnings} if warnings else {}),
                  **({"voice_parts": parts} if parts else {})}


def auto_description(idea: Dict[str, Any], asset: Dict[str, Any]) -> str:
    """The description when the agent wrote none: the kind of video, its hook and angle."""
    env = asset.get("recipe") or {}
    if env.get("kind") == "motion":
        kind = f"A {env.get('template')} video"
    else:
        ops = {op.get("op") for op in (env.get("recipe") or {}).get("ops", [])}
        kind = "A reaction remix" if "reaction_collage" in ops else "A remix"
    text = kind + (f" with the hook \"{idea['hook']}\"." if idea.get("hook") else ".")
    if idea.get("hypothesis"):
        text += f" Angle: {idea['hypothesis']}"
    return text[:DESCRIPTION_CHARS]


def voice_first(store: CampaignStore, asset: Dict[str, Any], settings: InstagramMCPSettings
                ) -> Dict[str, Any]:
    """The asset, its recipe's `voice_todo` made first (step 188a: the TTS runs here, in the
    worker, in line order). The voiced recipe replaces the queued one, so a retry or a
    re-render never synthesises it again; a recipe without `voice_todo` (no voice to make, or
    queued before 188a with its audio filled) is untouched. TTSError when the voice service
    fails (retried like any render error), ValueError when the voice does not fit."""
    env = dict(asset["recipe"] or {})
    if "voice_todo" not in env:
        return asset
    todo = env.pop("voice_todo")
    from . import remix  # remix imports us
    try:
        env = (motion.voice_recipe(env, settings, todo) if env["kind"] == "motion"
               else remix.voice_over(env, settings, todo))
    except TTSError as e:
        raise TTSError(f"voice-over failed: {e}", status=e.status,
                       unreachable=e.unreachable) from None
    env["voiced_with"] = todo  # 191: the voice and script, gone from the voiced props
    why = (env.get("voiced_by") or {}).get("fallback")
    if why:  # 204: the owner hears of a fallback once per new failure (the bell)
        from . import alerts  # alerts imports us

        engine = env["voiced_by"]["engine"]
        alerts.raise_alert(store, "tts_fallback", None, "warn",
                           "ElevenLabs n'a pas parlé : la voix locale a pris le relais"
                           if engine == "http"
                           else "La voix locale a échoué : ElevenLabs a pris le relais",
                           f"Vidéo {asset['id']} : {why}", "/voices", utcnow(), renew=True)
    return store.update_asset(asset["id"], recipe=validate_recipe(env, settings.media_root))


def voice_ahead(store: CampaignStore, settings: InstagramMCPSettings) -> int:
    """Make the voices of the next VOICE_AHEAD waiting renders that still need one, in line
    order (line.waiting), each through voice_first; films and items on a timer or held are
    passed over, and it stops once the studio is paused (line.pause, looked at before each
    voice). A failure is left to that job's own run (logged, never raised); a machine one
    (machine_failure) stops it: the next ones would wait for the same machine, inside this
    running job. Returns how many were voiced.
    ponytail: a job claimed meanwhile (RENDER_CONCURRENCY > 1) may voice the same recipe at
    once: the TTS cache answers the second, both store the same voiced recipe."""
    from . import line  # line imports us (through work_orders and lemo)

    now, done = utcnow(), 0
    for item in line.waiting(store):
        if done >= VOICE_AHEAD or line.paused(store):  # paused: the owner needs the GPU
            break
        if item["kind"] != "render" or (item["not_before"]
                                        and parse_iso(item["not_before"]) > now):
            continue
        asset = store.get_asset(store.get_render_job(item["id"])["asset_id"])
        if asset["status"] != "rendering" or "voice_todo" not in (asset["recipe"] or {}):
            continue
        try:
            voice_first(store, asset, settings)
        except Exception as e:  # noqa: BLE001 - its own job retries or fails with the reason
            logger.warning("render.voice_ahead_failed", job=item["id"], error=str(e))
            if machine_failure(e):
                break
            continue
        done += 1
    return done


def run_job(store: CampaignStore, media_root: PathLike, job: Dict[str, Any], *,
            render_fn: Callable[..., Tuple[MediaInfo, Dict[str, Any]]] = render_files,
            qc_fn: Callable[..., Dict[str, Any]] = run_qc,
            settings: Optional[InstagramMCPSettings] = None) -> Dict[str, Any]:
    """Render one claimed job (state running): its voice-over first when the recipe still
    needs one (voice_first, then voice_ahead for the next ones in line), then the render and
    the quality check (src/studio/qc.py):
    the asset becomes `ready` (and a `revision_requested` parent it replaces is archived), or
    `failed` with the reasons in `assets.qc`; the asset keeps the render's timeline and gets
    an automatic description if it has none (auto_description). A machine failure waits
    (machine_wait); other errors are retried
    up to MAX_ATTEMPTS, except ValueError (a bad recipe: retrying gives the same result);
    then the job fails with the reason and the asset moves rendering -> failed. Returns the
    job. `settings` defaults to get_settings() (QC thresholds, hashtag cap)."""
    job_id = job["id"]
    asset = store.get_asset(job["asset_id"])
    if asset["status"] != "rendering":
        return _finish(store, job_id, "failed", failure=f"asset is {asset['status']}, not rendering")
    if job["attempts"] > MAX_ATTEMPTS:  # re-queued after crashes during every attempt
        return _fail(store, job, f"gave up after {MAX_ATTEMPTS} attempts (worker stopped)")
    start = time.monotonic()
    settings = settings or get_settings()
    try:
        idea = store.get_idea(asset["idea_id"])
        voiced = voice_first(store, asset, settings)
        if voiced is not asset:  # the voice model is warm: the next voices while it is
            voice_ahead(store, settings)
        asset = voiced
        info, files = render_fn(asset, media_root,
                                lambda p: store.update_render_job(job_id, progress=p))
        notes = files.pop("render_warnings", [])
        qc = qc_fn({**asset, "timeline": files.get("timeline"),  # this render's (149, 158)
                    "voice_parts": files.pop("voice_parts", None)}, idea, files["file_path"],
                   media_root, settings)
        if notes:
            qc = {**qc, "warnings": [*qc.get("warnings", []), *notes]}
    except Exception as e:  # noqa: BLE001 - any render error is the job's failure reason
        reason = f"{type(e).__name__}: {e}"[:FAILURE_CHARS]
        if machine_failure(e):
            return machine_wait(store, job, reason)
        if isinstance(e, ValueError) or job["attempts"] >= MAX_ATTEMPTS:
            return _fail(store, job, reason)
        return store.update_render_job(job_id, state="queued", failure=reason)
    render_ms = round((time.monotonic() - start) * 1000)
    store.update_asset(asset["id"], **files, duration=info.duration, qc=qc,
                       description=asset["description"] or auto_description(idea, asset))
    transition(store, asset["id"], "ready" if qc["passed"] else "failed", actor="worker")
    parent = asset["parent_asset_id"] and store.get_asset(asset["parent_asset_id"])
    if qc["passed"] and parent and parent["status"] == "revision_requested":
        transition(store, parent["id"], "archived", actor="system")  # the new version is in
    return _finish(store, job_id, "done", progress=1, render_ms=render_ms)


def machine_failure(e: BaseException) -> bool:
    """Whether the machine, not the video, made the job fail (step 197), the one place that
    decides it. Machine: the voice service down, not answering in time or answering HTTP 5xx
    (TTSError.machine: 503 when its engine died, was stopped by the guard or is loading),
    the GPU lock not had in time (gpu_lock.LockTimeout), the resource guard killing the
    render for free RAM (guard.Stopped). Everything else is the video's: a QC fail, a bad
    recipe or props (ValueError), a render tool's error, a TTS 4xx or unreadable answer."""
    if isinstance(e, TTSError):
        return e.machine
    return isinstance(e, (gpu_lock.LockTimeout, guard.Stopped))


def machine_retries(job: Dict[str, Any]) -> int:
    """How many machine failures in a row the waiting job has had (its failure's count)."""
    m = _MACHINE_N.match(job.get("failure") or "")
    return int(m.group(1)) if m else 0


def machine_wait(store: CampaignStore, job: Dict[str, Any], reason: str) -> Dict[str, Any]:
    """A machine failure: the job goes back to the line at its place (arrival, line_pos and
    requeues untouched: the check run's re-render count stays as it was; the claim's attempt
    is given back), skipped until a backoff timer, the asset still `rendering`. Past
    MACHINE_RETRIES it fails with the reason and one website alert per video."""
    n = machine_retries(job) + 1
    if n > MACHINE_RETRIES:
        from . import alerts  # alerts imports the worker, which imports us

        why = (f"{MACHINE}: the machine could not make the voice or the render after"
               f" {MACHINE_RETRIES} tries: {reason}")[:FAILURE_CHARS]
        alerts.raise_alert(store, "render_machine", job["asset_id"], "error",
                           "La machine n'arrive pas à faire la voix / le rendu",
                           f"Vidéo {job['asset_id']} : {MACHINE_RETRIES} essais sans succès"
                           f" ({reason}). Libère de la RAM ou vérifie le service de voix, puis"
                           " relance-la.", f"/assets/{job['asset_id']}", utcnow(), renew=True)
        return _fail(store, job, why)
    wait = MACHINE_BACKOFF_MIN[min(n, len(MACHINE_BACKOFF_MIN)) - 1]
    logger.warning("render.machine_wait", job=job["id"], retry=n, minutes=wait, error=reason)
    return store.update_render_job(
        job["id"], state="queued", attempts=max(job["attempts"] - 1, 0),
        failure=f"{MACHINE} {n}/{MACHINE_RETRIES}: {reason}"[:FAILURE_CHARS],
        not_before=to_iso(utcnow() + timedelta(minutes=wait)))


def _finish(store: CampaignStore, job_id: int, state: str, **fields: Any) -> Dict[str, Any]:
    return store.update_render_job(job_id, state=state, finished_at=to_iso(utcnow()), **fields)


def _fail(store: CampaignStore, job: Dict[str, Any], reason: str) -> Dict[str, Any]:
    store.update_asset(job["asset_id"], qc={"passed": False, "reason": f"render failed: {reason}"})
    transition(store, job["asset_id"], "failed", actor="worker")
    return _finish(store, job["id"], "failed", failure=reason)
