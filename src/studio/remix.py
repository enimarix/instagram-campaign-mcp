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
from . import ffmpeg, frames, media, motion, render, stt, tts, voices
from .assets import checked_fields, clean_caption, transition
from .reactions import next_reaction_piece
from .recipe import (
    EVENT_CHARS,
    MAX_CAPTION,
    TIMELINE_EVENTS,
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
    compress_timeline,
)
from .rights import CREDIT_REQUIRED, attribution, basis, can_publish
from .sources import check_rights, list_clips
from .tts import get_provider

MUSIC_DIR = motion.MOTION_DIR / "public" / "audio"  # our own beds (ASSETS_LICENSES.md)
DEFAULT_MUSIC = "music-overworld"
MIN_CAPTION_S = 0.2  # a transcript line cut shorter than this by the trim is dropped
EXCERPT_CHARS = 200
MAX_CLIP_FRAMES = 12
SUMMARY_CHARS = 400


def _lines(source: Dict[str, Any]) -> List[Dict[str, Any]]:
    return ((source.get("stats") or {}).get("transcript") or {}).get("lines") or []


def span_lines(source: Dict[str, Any], start_s: float, end_s: float) -> List[int]:
    """Indices of the transcript lines shown as captions in the start_s..end_s part."""
    return [i for i, line in enumerate(_lines(source))
            if min(line["end_s"], end_s) - max(line["start_s"], start_s) >= MIN_CAPTION_S]


def transcript_captions(source: Dict[str, Any], start_s: float, end_s: float
                        ) -> List[Dict[str, Any]]:
    """The source's transcript lines (stats.transcript, step 068) inside start_s..end_s,
    in the trimmed clip's seconds."""
    lines = _lines(source)
    return [{"start_s": round(max(line["start_s"], start_s) - start_s, 3),
             "end_s": round(min(line["end_s"], end_s) - start_s, 3), "text": line["text"]}
            for line in (lines[i] for i in span_lines(source, start_s, end_s))]


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
                 voice: Optional[str] = None, plan: bool = False,
                 description: Optional[str] = None) -> Dict[str, Any]:
    """Build the remix, claim the next reaction piece for the new asset and queue its render
    (the job voices the script first: voice_over): {asset, job, piece, warnings}. Everything
    else is checked before the asset is created; a piece that cannot be cut leaves the asset
    `failed` with the reason. `description` is stored either way (193); `music`: a bed
    `music-...` or `none` (the values a planned card's edit takes). `plan` (188b): a
    `planned` asset with the recipe, caption and description, no piece and no job (None):
    src/studio/planned.py releases it; refused past the places left for Claude's ideas
    (planned.take_place, 188c)."""
    # 193: the description is stored for every video; a queued one's caption is written
    # again at submit_asset
    fields = checked_fields("planned" if plan else "rendering", **{k: x for k, x in (
        ("caption", caption if plan else None), ("description", description)) if x is not None})
    env, recipe, source = _remix_env(store, settings, idea_id, source_id, hook=hook,
                                     script=script, trim=trim, layout=layout,
                                     captions=captions, music=music, voice=voice)
    warnings = _warnings(source, recipe, settings)
    batch = store.get_idea(idea_id)["batch_date"]
    if plan:
        from .planned import take_place  # here: planned imports this module

        recipe_env = render.validate_recipe(env, settings.media_root)
        take_place(store, settings, batch)  # 188c: Claude's ideas only fill the batch's rest
        asset = store.add_asset(idea_id, recipe=recipe_env,
                                batch_date=batch, status="planned", **fields)
        return {"asset": asset, "job": None, "piece": None, "warnings": warnings}
    asset = store.add_asset(idea_id, caption=clean_caption(caption), batch_date=batch,
                            **fields)
    try:
        asset, piece = attach_piece(store, settings, asset["id"], env)
    except Exception as e:
        store.update_asset(asset["id"], qc={"passed": False, "reason": f"remix: {e}"})
        transition(store, asset["id"], "failed", actor="worker")
        raise
    return {"asset": asset, "job": render.enqueue_render(store, asset["id"]), "piece": piece,
            "warnings": warnings}


def _remix_env(store: CampaignStore, settings: InstagramMCPSettings, idea_id: int,
               source_id: int, *, hook: str, script: Optional[str],
               trim: Optional[Sequence[float]], layout: str,
               captions: Optional[List[Dict[str, Any]]], music: Optional[str],
               voice: Optional[str]) -> Tuple[Dict[str, Any], Recipe, Dict[str, Any]]:
    """(recipe envelope without its reaction piece, the remix, the source): every check
    render_remix makes, the rights first. `music`: a bed `music-...`, or None / `none`."""
    music = None if music == "none" else music
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
    todo = {}
    if (script or "").strip():
        if not tts.voiced(settings):
            raise ValueError("no TTS engine is set up (TTS_PROVIDER=none), so there is no"
                             " voice-over: a remix with a script is refused (never faked)")
        # 188a: the render job makes the voice (voice_over), in line order
        todo = {"voice_todo": {"script": script, "max_s": length,
                               "voice": voices.check_voice(store, voice)}}
    if any(isinstance(op, Music) for op in recipe.ops):
        inputs["music"] = _music_file(settings, music)
    clip = {"clip_timeline": t} if (t := source["stats"].get("timeline")) else {}
    env = {"kind": "ffmpeg", "recipe": recipe.model_dump(mode="json"), "inputs": inputs,
           **clip, **todo}
    return env, recipe, source


def attach_piece(store: CampaignStore, settings: InstagramMCPSettings, asset_id: int,
                 env: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """(asset, piece): the next piece of the active reaction reel, claimed for the asset, in
    its recipe `env` (render_remix; a planned remix at its release)."""
    trim = env["recipe"]["ops"][0]  # build_remix's first
    piece = next_reaction_piece(store, settings, trim["end_s"] - trim["start_s"],
                                asset_id=asset_id)
    env = render.validate_recipe({**env, "inputs": {**env["inputs"], "reaction": piece["path"]}},
                                 settings.media_root)
    return store.update_asset(asset_id, recipe=env), piece


def remix_params(env: Dict[str, Any]) -> Dict[str, Any]:
    """render_remix's arguments as a remix's recipe `env` holds them (planned.py rebuilds a
    planned one through _remix_env on an edit and at its release; the check run, 191,
    re-renders a voiced one from them: its script and voice in `voiced_with`). music: the
    bed, or `none`."""
    ops = {op["op"]: op for op in env["recipe"]["ops"]}
    todo = env.get("voice_todo") or env.get("voiced_with") or {}
    music = env["inputs"].get("music")
    return {"hook": ops["hook_text"]["text"], "script": todo.get("script"),
            "voice": todo.get("voice"), "trim": (ops["trim"]["start_s"], ops["trim"]["end_s"]),
            "layout": ops["reaction_collage"]["layout"],
            "captions": (ops.get("captions") or {}).get("lines") or None,
            "music": Path(music).stem if music else "none"}


def written_captions(env: Dict[str, Any], source: Dict[str, Any]
                     ) -> Optional[List[Dict[str, Any]]]:
    """The remix's captions when someone wrote them, None when they are the source's
    transcript for its trim (193: render_remix derives them again for a changed trim)."""
    params = remix_params(env)
    derived = transcript_captions(source, *params["trim"])
    if not params["captions"] or not derived:
        return params["captions"]
    try:  # as the Captions op stores them (text cleaned)
        derived = Captions(lines=derived).model_dump(mode="json")["lines"]
    except ValueError:  # a transcript build_remix could not have used: so they were written
        return params["captions"]
    return None if params["captions"] == derived else params["captions"]


def replan(store: CampaignStore, settings: InstagramMCPSettings, asset: Dict[str, Any],
           **changes: Any) -> Dict[str, Any]:
    """A planned remix's recipe rebuilt with `changes` (script, voice, music: a bed or None)
    through every check render_remix makes (rights included), without a piece."""
    idea = store.get_idea(asset["idea_id"])
    env, _, _ = _remix_env(store, settings, idea["id"], idea["source_id"],
                           **{**remix_params(asset["recipe"]), **changes})
    return render.validate_recipe(env, settings.media_root)


def voice_over(env: Dict[str, Any], settings: InstagramMCPSettings, todo: Dict[str, Any]
               ) -> Dict[str, Any]:
    """The remix recipe `env` with its voice-over made (`todo`: render.VoiceTodo's voice,
    script, max_s) as its `voice` input. Run by the render job (render.voice_first)."""
    synth = get_provider(settings).synthesize(todo["script"], todo.get("voice"))
    if synth.duration_s > todo["max_s"] + 0.05:
        raise ValueError(f"the voice-over is {synth.duration_s:.1f} s, longer than the"
                         f" {todo['max_s']:.1f} s clip: shorten the script or widen the trim")
    out = {**env, "inputs": {**env["inputs"],
                             "voice": motion.store_voice(settings, synth.audio_path)}}
    by = motion.voiced_by([synth])
    if by:  # 204: the asset page's badge
        out["voiced_by"] = by
    return out


def _warnings(source: Dict[str, Any], recipe: Recipe, settings: InstagramMCPSettings
              ) -> List[str]:
    """What the agent should know before keeping this remix (it may pick another clip)."""
    ops = {op.op for op in recipe.ops}
    if "mute_original" in ops and "captions" not in ops and source["audio_rights"] != "no_audio":
        why = ("STT not set up" if settings.stt_provider == "none"
               else "no transcript lines in the trimmed part")
        return [f"the clip's speech is muted and has no captions ({why})"]
    return []


def _excerpt(source: Dict[str, Any]) -> str:
    text = " ".join(line["text"] for line in _lines(source))
    return text[:EXCERPT_CHARS] + ("…" if len(text) > EXCERPT_CHARS else "")


def list_sources(store: CampaignStore, role: str = "clip", limit: int = 50
                 ) -> List[Dict[str, Any]]:
    """Downloaded sources that may be published (rights known, credit possible), newest
    first: {id, author, url, rights_basis, audio_rights, duration_s, attribution,
    transcript (excerpt), used (an idea already uses it), summary and has_timeline
    (set_clip_timeline)}."""
    with store._tx() as c:
        used = {r[0] for r in c.execute("SELECT source_id FROM ideas WHERE source_id IS NOT NULL")}
    out = []
    for s in list_clips(store, role, limit):
        if not s["local_path"] or not can_publish(s, confirmed=True, licence=s["licence"]):
            continue
        stats = s.get("stats") or {}
        out.append({"id": s["id"], "author": s["author"], "url": s["url"],
                    "rights_basis": s["rights_basis"], "audio_rights": s["audio_rights"],
                    "duration_s": stats.get("duration_s"),
                    "attribution": s["attribution"], "used": s["id"] in used,
                    "transcript": _excerpt(s), "summary": stats.get("summary"),
                    "has_timeline": bool(stats.get("timeline"))})
    return out


# --- Looking at a clip before reacting to it (119) ---------------------------------------

def clip_frames(store: CampaignStore, settings: InstagramMCPSettings, source_id: int,
                times_s: Optional[Sequence[float]] = None, n: int = 6
                ) -> Tuple[List[bytes], Dict[str, Any]]:
    """JPEG frames of a downloaded clip (as frames.asset_frames) at `times_s` (at most
    MAX_CLIP_FRAMES, within the clip) or `n` spread evenly, and {source_id, duration_s,
    frame_times_s, transcript (excerpt), timeline, summary}."""
    source = _source(store, settings, source_id)
    stats = source["stats"]
    duration = float(stats["duration_s"])
    last = max(duration - 0.1, 0.0)  # a frame that exists
    if times_s:
        if len(times_s) > MAX_CLIP_FRAMES:
            raise ValueError(f"at most {MAX_CLIP_FRAMES} times per call")
        if not all(0 <= t <= duration for t in times_s):
            raise ValueError(f"times must lie within the clip (0-{duration:g} s)")
        times = [round(min(float(t), last), 3) for t in times_s]
    elif 1 <= n <= MAX_CLIP_FRAMES:
        times = [round(min((k + 0.5) * duration / n, last), 3) for k in range(n)]
    else:
        raise ValueError(f"n must be 1..{MAX_CLIP_FRAMES}")
    video = media.resolve(settings.media_root, source["local_path"])
    return frames.video_frames(settings.media_root, video, f"clip-{source_id}", times), {
        "source_id": source_id, "duration_s": round(duration, 3), "frame_times_s": times,
        "transcript": _excerpt(source), "timeline": stats.get("timeline"),
        "summary": stats.get("summary")}


def set_clip_timeline(store: CampaignStore, settings: InstagramMCPSettings, source_id: int,
                      events: Sequence[Dict[str, Any]], summary: str) -> Dict[str, Any]:
    """Store what happens in a downloaded clip, as the agent saw it (clip_frames): events
    [{t, d, e}] in the clip's seconds, compressed like an asset's timeline (110), and a
    summary of at most SUMMARY_CHARS, as stats.timeline / stats.summary. A re-run
    overwrites both. Returns {source_id, timeline, summary}."""
    source = _source(store, settings, source_id)
    duration = float(source["stats"]["duration_s"])
    summary = " ".join((summary or "").split())
    if not summary or len(summary) > SUMMARY_CHARS:
        raise ValueError(f"summary must be 1-{SUMMARY_CHARS} characters")
    if not 1 <= len(events) <= TIMELINE_EVENTS:
        raise ValueError(f"send 1-{TIMELINE_EVENTS} events")
    raw = []
    for i, ev in enumerate(events, 1):
        try:
            t, d, e = float(ev["t"]), float(ev["d"]), " ".join(str(ev["e"]).split())
        except (KeyError, TypeError, ValueError):
            raise ValueError(f"event {i}: needs t and d (seconds) and e (what happens)"
                             ) from None
        if not (0 <= t < duration and d >= 0):
            raise ValueError(f"event {i}: t must lie within the clip (0-{duration:g} s),"
                             " d not negative")
        if not e or len(e) > EVENT_CHARS:
            raise ValueError(f"event {i}: e must be one line of 1-{EVENT_CHARS} characters")
        raw.append({"t": t, "d": min(d, duration - t), "e": e})
    timeline = compress_timeline(raw)
    store.patch_source_stats(source_id, {"timeline": timeline, "summary": summary})
    return {"source_id": source_id, "timeline": timeline, "summary": summary}


# --- The owner's review (072): the piece used, the next piece, the clip's speech ---------

def _remix(store: CampaignStore, asset_id: int
           ) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Tuple[float, float]]:
    """(asset, recipe envelope, source, (trim start, end)); ValueError if not a reaction remix."""
    asset = store.get_asset(asset_id)
    env = asset.get("recipe") or {}
    if env.get("kind") != "ffmpeg" or "reaction" not in env.get("inputs", {}):
        raise ValueError(f"video {asset_id} is not a reaction remix")
    trim = next(op for op in env["recipe"]["ops"] if op["op"] == "trim")  # build_remix's first
    source = store.get_source(store.get_idea(asset["idea_id"])["source_id"])
    return asset, env, source, (trim["start_s"], trim["end_s"])


def reaction_info(store: CampaignStore, asset_id: int) -> Dict[str, Any]:
    """What the asset page shows: {piece {id, start_s, end_s, url}, reel {id, duration_s,
    created_at}, source {id, author, url, rights_basis, attribution}, trim {start_s, end_s},
    transcript [{index, start_s, end_s, text}] (the lines of the trimmed part, clip seconds)}."""
    _, env, source, (start, end) = _remix(store, asset_id)
    path = env["inputs"]["reaction"]
    piece = store.get_reaction_piece(int(Path(path).stem))  # pieces/<piece id>.mp4
    reel = store.get_reaction_reel(piece["reel_id"])
    lines = _lines(source)
    return {
        "piece": {"id": piece["id"], "start_s": piece["start_s"], "end_s": piece["end_s"],
                  "url": media.media_url(path)},
        "reel": {k: reel[k] for k in ("id", "duration_s", "created_at")},
        "source": {"id": source["id"], "author": source["author"], "url": source["url"],
                   "rights_basis": source["rights_basis"], "attribution": attribution(source)},
        "trim": {"start_s": start, "end_s": end},
        "transcript": [{"index": i, **lines[i]} for i in span_lines(source, start, end)],
    }


def use_next_piece(store: CampaignStore, settings: InstagramMCPSettings, asset_id: int
                   ) -> Dict[str, Any]:
    """Re-render the remix with the next piece of the active reel: {asset, job, piece}. A
    `failed` remix is re-rendered in place, a `ready` one gets a child (render.rerender)."""
    asset, env, _, (start, end) = _remix(store, asset_id)
    render.check_rerender(asset)  # before claiming: a refused re-render must not use a piece
    piece = next_reaction_piece(store, settings, end - start)
    out = render.rerender(store, settings.media_root, asset_id,
                          {**env, "inputs": {**env["inputs"], "reaction": piece["path"]}})
    store.set_reaction_piece_asset(piece["piece_id"], out["asset"]["id"])
    return {**out, "piece": piece}


def fix_transcript(store: CampaignStore, settings: InstagramMCPSettings, asset_id: int,
                   texts: List[str]) -> Dict[str, Any]:
    """The owner's corrected text for the lines reaction_info() lists (same order, same
    timings), saved on the source, then a re-render with captions rebuilt from it:
    {asset, job}."""
    asset, env, source, (start, end) = _remix(store, asset_id)
    render.check_rerender(asset)
    span = span_lines(source, start, end)
    if not span:
        raise ValueError("this part of the clip has no transcript lines to correct")
    if len(texts) != len(span):
        raise ValueError(f"send {len(span)} lines, one per transcript line (got {len(texts)})")
    lines = [dict(line) for line in _lines(source)]
    for n, (i, text) in enumerate(zip(span, texts), 1):
        text = " ".join(text.split())
        if not text:
            raise ValueError(f"line {n} is empty")
        if len(text) > MAX_CAPTION:
            raise ValueError(f"line {n} is longer than {MAX_CAPTION} characters")
        lines[i]["text"] = text
    fixed = {**source, "stats": {**source["stats"],
                                 "transcript": {**source["stats"]["transcript"], "lines": lines}}}
    ops = list(env["recipe"]["ops"])
    # Replace the captions op, or put one where build_remix does (before credit and logo).
    i = next((i for i, op in enumerate(ops) if op["op"] in ("captions", "credit", "logo")),
             len(ops))
    had = i < len(ops) and ops[i]["op"] == "captions"
    ops[i:i + had] = [{**(ops[i] if had else {"op": "captions"}),
                       "lines": transcript_captions(fixed, start, end)}]
    new = render.validate_recipe({**env, "recipe": {**env["recipe"], "ops": ops}},
                                 settings.media_root)  # nothing is saved if a line is refused
    store.patch_source_stats(source["id"], {"transcript": {"lines": lines}})
    return render.rerender(store, settings.media_root, asset_id, new)
