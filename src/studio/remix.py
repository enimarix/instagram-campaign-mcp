"""
Reaction remixes (GOAL.md §3.1 Track A, §5.1): a downloaded clip becomes a recipe of the
studio's ops, and render_remix() queues it.

The rights rules live here, not in the prompt; each refusal is a ValueError saying why:
- `rights_basis = unknown` is never rendered; `cc`, `permission` and `commentary` need an
  author to credit (sources.check_rights). The on-screen credit names them; for
  `commentary` the caption must carry `@creator` too (checked at submit_asset).
- `commentary` needs a piece of the owner's reaction reel (`reaction_collage`) AND a
  voice-over script about this very clip: the reel piece is generic, so the voice-over
  and the credit carry the commentary. The voice is never faked: no TTS engine, no remix.
- Only the part being reacted to is used (`trim`, at most REMIX_MAX_CLIP_S seconds): a cut,
  never a speed, pitch, mirror or crop trick.
- Sound: unless the source says its audio is covered, the original audio is muted and
  our own music bed may go under it; the clip's speech is shown as captions from its
  transcript (068). Covered audio stays, ducked under the reaction and the voice-over.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..config import InstagramMCPSettings
from ..store import CampaignStore
from . import ffmpeg, media, motion, render, stt
from .assets import transition
from .reactions import next_reaction_piece
from .recipe import (
    Captions,
    Credit,
    HookText,
    Logo,
    Music,
    MuteOriginal,
    ReactionCollage,
    Recipe,
    Trim,
    VoiceOver,
)
from .rights import CREDIT_REQUIRED, attribution, basis, can_publish
from .sources import check_rights, list_clips
from .tts import get_provider

MUSIC_DIR = motion.MOTION_DIR / "public" / "audio"  # our own beds (ASSETS_LICENSES.md)
DEFAULT_MUSIC = "music-overworld"
MIN_CAPTION_S = 0.2  # a transcript line cut shorter than this by the trim is dropped
EXCERPT_CHARS = 200


def transcript_captions(source: Dict[str, Any], start_s: float, end_s: float
                        ) -> List[Dict[str, Any]]:
    """The source's transcript lines (stats.transcript, step 068) inside start_s..end_s,
    in the trimmed clip's seconds."""
    lines = ((source.get("stats") or {}).get("transcript") or {}).get("lines") or []
    out = []
    for line in lines:
        a, b = max(line["start_s"], start_s), min(line["end_s"], end_s)
        if b - a >= MIN_CAPTION_S:
            out.append({"start_s": round(a - start_s, 3), "end_s": round(b - start_s, 3),
                        "text": line["text"]})
    return out


def _trim(trim: Optional[Sequence[Optional[float]]], duration_s: float, max_clip_s: float
          ) -> Tuple[float, float]:
    """(start, end) of the part used: within the clip, at most max_clip_s long. A missing
    start or end is the clip's own."""
    start, end = trim or (None, None)
    start = 0.0 if start is None else float(start)
    end = duration_s if end is None else float(end)
    if not 0 <= start < end <= duration_s + 0.05:
        raise ValueError(f"trim must lie within the clip (0-{duration_s:g} s), start before end")
    return start, min(end, duration_s, start + max_clip_s)


def build_remix(source: Dict[str, Any], *, hook: str, script: Optional[str],
                captions: Optional[List[Dict[str, Any]]] = None, credit: Optional[str] = None,
                trim: Optional[Sequence[float]] = None, layout: str = "pip",
                music: bool = False, max_clip_s: float = 45.0) -> Recipe:
    """A validated reaction-remix recipe of `source` (inputs: source, reaction, voice when
    there is a script, music when `music`). `captions` default to the transcript of the
    trimmed span; `credit` to the source's attribution."""
    b = basis(source)
    check_rights(b, source.get("rights_note"), author=source.get("author"),
                 licence=source.get("licence") or (source.get("stats") or {}).get("licence"))
    if not (script or "").strip() and b == "commentary":
        raise ValueError("commentary needs a voice-over script about this clip: the reaction"
                         " piece alone is not commentary")
    needed = attribution(source)
    credit = (credit or needed or "").strip()
    if b in CREDIT_REQUIRED and needed.lower() not in credit.lower():
        raise ValueError(f"{b}: the on-screen credit must name the creator ({needed})")
    duration = float((source.get("stats") or {}).get("duration_s") or 0)
    start, end = _trim(trim, duration, max_clip_s)
    covered = source.get("audio_rights") == "covered"
    if captions is None:
        captions = transcript_captions(source, start, end)
    ops: List[Any] = [Trim(start_s=start, end_s=end)]
    if not covered:
        ops.append(MuteOriginal())
    # Covered: the clip's sound stays, ducked under the reaction (clip_gain_db) and the voice.
    ops.append(ReactionCollage(layout=layout, pip_corner="top_right"))
    if (script or "").strip():
        ops.append(VoiceOver())
    if music and not covered:
        ops.append(Music())
    ops.append(HookText(text=hook, position="center"))
    if captions:
        ops.append(Captions(lines=captions))
    if credit:
        ops.append(Credit(text=credit))
    ops.append(Logo(position="top_left"))  # never the pip's corner
    return Recipe(ops=ops)


def _music_file(settings: InstagramMCPSettings, name: str) -> str:
    """Copy a bed from our library into `<media root>/music/`; returns its media path."""
    src = MUSIC_DIR / f"{name}.wav"
    if not re.fullmatch(r"music-[a-z0-9-]+", name) or not src.is_file():
        beds = sorted(p.stem for p in MUSIC_DIR.glob("music-*.wav"))
        raise ValueError(f"unknown music bed {name!r}; ours: {', '.join(beds)}")
    dest = Path(settings.media_root) / "music" / src.name
    if not dest.is_file():
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
    return media.relative(settings.media_root, dest)


def _source(store: CampaignStore, settings: InstagramMCPSettings, source_id: int
            ) -> Dict[str, Any]:
    """The clip with its duration and (when an STT engine is set) its transcript."""
    source = store.get_source(source_id)
    if source["role"] != "clip" or not source["local_path"]:
        raise ValueError(f"source {source_id} is not a downloaded clip")
    stats = source.get("stats") or {}
    path = media.resolve(settings.media_root, source["local_path"])
    if not stats.get("duration_s"):
        store.patch_source_stats(source_id, {"duration_s": ffmpeg.probe(path).duration})
    if (settings.stt_provider != "none" and "transcript" not in stats
            and source["audio_rights"] != "no_audio"):
        stt.transcribe_source(store, settings, source_id)
    return store.get_source(source_id)


def render_remix(store: CampaignStore, settings: InstagramMCPSettings, idea_id: int,
                 source_id: int, *, hook: str, script: Optional[str],
                 trim: Optional[Sequence[float]] = None, layout: str = "pip",
                 captions: Optional[List[Dict[str, Any]]] = None,
                 caption: Optional[str] = None, music: Optional[str] = DEFAULT_MUSIC,
                 voice: Optional[str] = None) -> Dict[str, Any]:
    """Build the remix, voice the script, claim the next reaction piece for the new asset
    and queue its render: {asset, job, piece}. Everything is checked before the asset is
    created; a piece that cannot be cut leaves the asset `failed` with the reason."""
    idea = store.get_idea(idea_id)
    if idea["track"] != "remix" or idea["source_id"] != source_id:
        raise ValueError(f"idea {idea_id} must be a remix idea of source {source_id}"
                         f" (create_idea(track='remix', source_id={source_id}))")
    source = _source(store, settings, source_id)
    recipe = build_remix(source, hook=hook, script=script, captions=captions, trim=trim,
                         layout=layout, music=bool(music),
                         max_clip_s=settings.remix_max_clip_s)
    trimmed = recipe.ops[0]
    length = trimmed.end_s - trimmed.start_s
    if store.active_reaction_reel() is None:
        raise ValueError("no reaction reel: upload a reaction reel in Settings first")
    inputs = {"source": source["local_path"]}
    if (script or "").strip():
        if settings.tts_provider == "none":
            raise ValueError("no TTS engine is set up (TTS_PROVIDER=none), so there is no"
                             " voice-over: a remix with a script is refused (never faked)")
        synth = get_provider(settings).synthesize(script, voice)
        if synth.duration_s > length + 0.05:
            raise ValueError(f"the voice-over is {synth.duration_s:.1f} s, longer than the"
                             f" {length:.1f} s clip: shorten the script or widen the trim")
        inputs["voice"] = motion.store_voice(settings, synth.audio_path)
    if any(isinstance(op, Music) for op in recipe.ops):
        inputs["music"] = _music_file(settings, music)
    asset = store.add_asset(idea_id, caption=caption, batch_date=idea["batch_date"])
    try:
        piece = next_reaction_piece(store, settings, length, asset_id=asset["id"])
        env = render.validate_recipe({"kind": "ffmpeg", "recipe": recipe.model_dump(mode="json"),
                                      "inputs": {**inputs, "reaction": piece["path"]}},
                                     settings.media_root)
        asset = store.update_asset(asset["id"], recipe=env)
    except Exception as e:
        store.update_asset(asset["id"], qc={"passed": False, "reason": f"remix: {e}"})
        transition(store, asset["id"], "failed", actor="worker")
        raise
    return {"asset": asset, "job": render.enqueue_render(store, asset["id"]), "piece": piece}


def list_sources(store: CampaignStore, role: str = "clip", limit: int = 50
                 ) -> List[Dict[str, Any]]:
    """Downloaded sources that may be published (rights known, credit possible), newest
    first: {id, author, url, rights_basis, audio_rights, duration_s, attribution,
    transcript (excerpt), used (an idea already uses it)}."""
    with store._tx() as c:
        used = {r[0] for r in c.execute("SELECT source_id FROM ideas WHERE source_id IS NOT NULL")}
    out = []
    for s in list_clips(store, role, limit):
        if not s["local_path"] or not can_publish(s, confirmed=True, licence=s["licence"]):
            continue
        lines = ((s.get("stats") or {}).get("transcript") or {}).get("lines") or []
        text = " ".join(line["text"] for line in lines)
        out.append({"id": s["id"], "author": s["author"], "url": s["url"],
                    "rights_basis": s["rights_basis"], "audio_rights": s["audio_rights"],
                    "duration_s": (s.get("stats") or {}).get("duration_s"),
                    "attribution": s["attribution"], "used": s["id"] in used,
                    "transcript": text[:EXCERPT_CHARS] + ("…" if len(text) > EXCERPT_CHARS
                                                          else "")})
    return out
