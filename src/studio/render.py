"""
Render jobs (GOAL.md §3.1, §3.2, §4.3): render an asset from its recipe into its folder.

`assets.recipe` is an envelope (docs/DECISIONS.md):
  {"kind": "ffmpeg", "recipe": <Recipe>, "inputs": {"source": <media path>, ...}}  Track A
  {"kind": "motion", "template": <id>, "props": {...}}                             Track B
plus an optional `thumb_offset_ms` (cover frame, also sent to Instagram). Motion renders
arrive in step 048 (Remotion); until then such a job fails.

A render writes, into media.asset_dir(): `video.mp4` (the master), `preview.mp4` (light copy
the inbox plays), `poster.jpg` (cover frame) and `thumb.jpg`. The worker render loop
(src/worker.py) claims jobs and calls run_job() in a thread.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Annotated, Any, Callable, Dict, Literal, Optional, Tuple, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator

from ..config import InstagramMCPSettings, get_settings
from ..store import CampaignStore, to_iso, utcnow
from . import ffmpeg, media
from .assets import InvalidTransition, transition
from .ffmpeg import MediaInfo, PathLike
from .qc import run_qc
from .recipe import DEFAULT_PRESET, DEFAULT_TIMEOUT_S, Recipe, render

MAX_ATTEMPTS = 3
FAILURE_CHARS = 2000
POSTER_AT_S = 1.0  # cover frame when the recipe names none
PREVIEW_ARGS = ("-vf", "scale=720:1280", "-c:v", "libx264", "-b:v", "1500k", "-maxrate", "1500k",
                "-bufsize", "3000k", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k",
                "-movflags", "+faststart")
THUMB_WIDTH = 270

Progress = Callable[[float], None]


class _Envelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    thumb_offset_ms: Optional[int] = Field(None, ge=0)


class FfmpegRecipe(_Envelope):
    kind: Literal["ffmpeg"]
    recipe: Recipe
    inputs: Dict[str, str]

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


_ENVELOPE = TypeAdapter(Annotated[Union[FfmpegRecipe, MotionRecipe], Field(discriminator="kind")])


def validate_recipe(value: Any, media_root: PathLike) -> Dict[str, Any]:
    """The envelope as stored, or ValueError (unknown kind or op, input path outside the root)."""
    env = _ENVELOPE.validate_python(value)
    if isinstance(env, FfmpegRecipe):
        for rel in env.inputs.values():
            media.resolve(media_root, rel)
    return env.model_dump(mode="json", exclude_none=True)


def recipe_hash(recipe: Any) -> str:
    return hashlib.sha256(json.dumps(recipe, sort_keys=True).encode()).hexdigest()[:16]


def enqueue_render(store: CampaignStore, asset_id: int, *, key: Optional[str] = None
                   ) -> Dict[str, Any]:
    """Queue a render of the asset's current recipe; the same key gives the same job, so a
    restarted batch never renders an asset twice. A finished (failed or done) job is queued
    again only when the asset is back in `rendering` (a re-render of the same recipe, e.g.
    after a failed QC)."""
    asset = store.get_asset(asset_id)
    job = store.add_render_job(asset_id, key or f"{asset_id}:{recipe_hash(asset['recipe'])}")
    if job["state"] in ("failed", "done") and asset["status"] == "rendering":
        job = store.update_render_job(job["id"], state="queued", attempts=0, progress=0,
                                      failure=None, finished_at=None)
    return job


def rerender(store: CampaignStore, media_root: PathLike, asset_id: int, recipe: Any,
             *, actor: str = "owner") -> Dict[str, Any]:
    """Render an asset again with an edited recipe. From `failed` the asset itself goes back
    to `rendering`; from `ready` a new child asset (parent_asset_id) is rendered, so the one
    under review is never overwritten. Returns {asset, job}."""
    env = validate_recipe(recipe, media_root)
    asset = store.get_asset(asset_id)
    if asset["status"] == "failed":
        transition(store, asset_id, "rendering", actor=actor)
        asset = store.update_asset(asset_id, recipe=env)
    elif asset["status"] == "ready":
        asset = store.add_asset(
            asset["idea_id"], parent_asset_id=asset_id, recipe=env,
            batch_date=asset["batch_date"], caption=asset["caption"],
            audio_name=asset["audio_name"], best_before=asset["best_before"])
    else:
        raise InvalidTransition(f"asset {asset_id} is {asset['status']}: only failed or ready"
                                " assets can be re-rendered")
    return {"asset": asset, "job": enqueue_render(store, asset["id"])}


def render_files(asset: Dict[str, Any], media_root: PathLike, progress: Progress, *,
                 preset: str = DEFAULT_PRESET, timeout_s: float = DEFAULT_TIMEOUT_S
                 ) -> Tuple[MediaInfo, Dict[str, str]]:
    """Render the master, preview, poster and thumbnail; return the master's MediaInfo and
    the asset fields (relative paths)."""
    env = _ENVELOPE.validate_python(asset["recipe"])
    if isinstance(env, MotionRecipe):
        raise ValueError("motion renders arrive in step 048")
    folder = media.asset_dir(media_root, asset["batch_date"], asset["id"])
    inputs = {k: media.resolve(media_root, v) for k, v in env.inputs.items()}
    video, preview = folder / "video.mp4", folder / "preview.mp4"
    poster, thumb = folder / "poster.jpg", folder / "thumb.jpg"
    info = render(env.recipe, inputs, video, timeout_s=timeout_s, preset=preset)
    progress(0.8)
    ffmpeg.run(["-i", video, *PREVIEW_ARGS, "-preset", preset, preview], timeout_s=timeout_s)
    progress(0.9)
    at = POSTER_AT_S if env.thumb_offset_ms is None else env.thumb_offset_ms / 1000
    at = max(min(at, info.duration - 0.1), 0.0)  # a frame that exists in short clips
    ffmpeg.run(["-ss", f"{at:.3f}", "-i", video, "-frames:v", "1", "-q:v", "3", poster],
               timeout_s=timeout_s)
    ffmpeg.run(["-i", poster, "-vf", f"scale={THUMB_WIDTH}:-2", "-q:v", "4", thumb],
               timeout_s=timeout_s)
    paths: Dict[str, Path] = {"file_path": video, "preview_path": preview,
                              "poster_path": poster, "thumbnail_path": thumb}
    return info, {k: media.relative(media_root, p) for k, p in paths.items()}


def run_job(store: CampaignStore, media_root: PathLike, job: Dict[str, Any], *,
            render_fn: Callable[..., Tuple[MediaInfo, Dict[str, str]]] = render_files,
            qc_fn: Callable[..., Dict[str, Any]] = run_qc,
            settings: Optional[InstagramMCPSettings] = None) -> Dict[str, Any]:
    """Render one claimed job (state running), then run the quality check (src/studio/qc.py):
    the asset becomes `ready`, or `failed` with the reasons in `assets.qc`. Errors are retried
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
    try:
        info, files = render_fn(asset, media_root,
                                lambda p: store.update_render_job(job_id, progress=p))
        qc = qc_fn(asset, store.get_idea(asset["idea_id"]), files["file_path"], media_root,
                   settings or get_settings())
    except Exception as e:  # noqa: BLE001 - any render error is the job's failure reason
        reason = f"{type(e).__name__}: {e}"[:FAILURE_CHARS]
        if isinstance(e, ValueError) or job["attempts"] >= MAX_ATTEMPTS:
            return _fail(store, job, reason)
        return store.update_render_job(job_id, state="queued", failure=reason)
    render_ms = round((time.monotonic() - start) * 1000)
    store.update_asset(asset["id"], **files, duration=info.duration, qc=qc)
    transition(store, asset["id"], "ready" if qc["passed"] else "failed", actor="worker")
    return _finish(store, job_id, "done", progress=1, render_ms=render_ms)


def _finish(store: CampaignStore, job_id: int, state: str, **fields: Any) -> Dict[str, Any]:
    return store.update_render_job(job_id, state=state, finished_at=to_iso(utcnow()), **fields)


def _fail(store: CampaignStore, job: Dict[str, Any], reason: str) -> Dict[str, Any]:
    store.update_asset(job["asset_id"], qc={"passed": False, "reason": f"render failed: {reason}"})
    transition(store, job["asset_id"], "failed", actor="worker")
    return _finish(store, job["id"], "failed", failure=reason)
