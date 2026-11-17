"""
Dev seed: a realistic fake batch so the website can be built and demoed before
the pipeline exists (`ig-campaign dev seed`).

Every status is reached through transition() with the right actor, exactly as the
real pipeline will move assets, so the seed also exercises the lifecycle. All text
is marked "[demo]" so nobody publishes it by mistake.

The video is samples/sample.mp4 (2 s, 270x480, ~30 KB), made once with:
  ffmpeg -f lavfi -i testsrc2=size=270x480:rate=15:duration=2 \
    -f lavfi -i sine=frequency=440:duration=2 -c:v libx264 -preset veryslow -crf 35 \
    -pix_fmt yuv420p -c:a aac -b:a 24k -movflags +faststart -map_metadata -1 \
    -fflags +bitexact -shortest src/studio/samples/sample.mp4
It lives inside the package so an editable install finds it without the tests folder.
"""

from __future__ import annotations

import random
import shutil
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from ..store import CampaignStore, utcnow
from ..taxonomy import valid_values
from .assets import set_verdict, transition

SAMPLE = Path(__file__).parent / "samples" / "sample.mp4"

# One entry per asset in every batch: (status, verdict). Extras are added at random.
PLAN = [
    ("ready", "liked"), ("ready", "none"), ("ready", "disliked"), ("approved", "liked"),
    ("archived", "disliked"), ("revision_requested", "none"), ("needs_reaction", "none"),
    ("failed", "none"),
]
EXTRAS = [("ready", "liked"), ("ready", "none"), ("approved", "liked"), ("archived", "none")]
QC_FAILURES = ["[demo] audio clipped at 0:01", "[demo] black frames in the first second",
               "[demo] render timed out"]
COMMENTS = [("[demo] hook is too slow", ["weak_hook", "too_slow"]),
            ("[demo] not my tone", ["wrong_tone"]), (None, ["repetitive"]),
            ("[demo] check that fact", ["factual_error"])]


def local_today(timezone: str, now: Optional[datetime] = None) -> date:
    """The owner's calendar date: batches are dated in local time, not UTC."""
    return (now or utcnow()).astimezone(ZoneInfo(timezone)).date()


def refusal(store: CampaignStore, *, production_live: bool) -> Optional[str]:
    """Why seeding this database is unsafe without --force, or None."""
    if production_live:
        return ("this is the configured production database and Instagram is configured;"
                " fake posts could end up published")
    if store.list_assets(limit=1) or store.list_scheduled(limit=1):
        return "the database already has assets or scheduled posts"
    return None


def _place_media(media_root: Path, batch_date: date, asset_id: int) -> Dict[str, str]:
    # ponytail: private stand-in for the media layout helper of step 011
    folder = Path(media_root) / batch_date.isoformat() / str(asset_id)
    folder.mkdir(parents=True, exist_ok=True)
    out = {}
    for field, name in (("file_path", "master.mp4"), ("preview_path", "preview.mp4")):
        shutil.copyfile(SAMPLE, folder / name)
        out[field] = str((folder / name).resolve())
    return out


def _walk(store: CampaignStore, asset_id: int, *moves: tuple) -> None:
    for to, actor in moves:
        transition(store, asset_id, to, actor=actor)


def _new_asset(store, rng, batch_date, track, status, media_root, *, n, parent=None):
    """An idea (or the parent's idea for a new version) plus its asset, files placed."""
    if parent:
        idea = store.get_idea(parent["idea_id"])
    else:
        pillar = rng.choice(valid_values("pillars"))
        explore = n == 0 or rng.random() < 0.3
        fields: Dict[str, Any] = dict(
            pillar=pillar, hook_type=rng.choice(valid_values("hook_types")),
            hook=f"[demo] hook {batch_date} #{n + 1}", script=f"[demo] script for idea {n + 1}",
            strategy="explore" if explore else "exploit", batch_date=batch_date)
        if explore:
            fields["hypothesis"] = f"[demo] {pillar} works better with a {fields['hook_type']}"
        if pillar in ("fun_facts", "myths"):
            fields["citations"] = [{"title": f"[demo] source {n + 1}",
                                    "url": f"https://example.org/demo/{batch_date}/{n + 1}"}]
        if track == "remix":
            src = store.add_source("demo", url=f"https://example.org/clip/{batch_date}/{n}",
                                   author="[demo] creator",
                                   rights_basis=rng.choice(["own", "licensed"]))
            fields["source_id"] = src["id"]
        idea = store.add_idea(track, **fields)
    recipe = ({"template": rng.choice(valid_values("templates"))} if track == "motion"
              else {"edit": "[demo] reaction split screen"})
    asset = store.add_asset(
        idea["id"], status="needs_reaction" if status == "needs_reaction" else "rendering",
        batch_date=batch_date, recipe=recipe, parent_asset_id=parent and parent["id"],
        caption=f"[demo] caption {batch_date} #{n + 1} #demo", duration=2.0,
        self_score=rng.randint(1, 10), self_score_reason=f"[demo] reason {n + 1}",
        # the first (liked) asset of older batches is already past its best-before
        best_before=batch_date + timedelta(days=1 if n == 0 else rng.randint(1, 4)))
    if status in ("needs_reaction", "failed") or (parent and status == "rendering"):
        return asset
    return store.update_asset(asset["id"], **_place_media(media_root, batch_date, asset["id"]))


def seed(store: CampaignStore, media_root: Path, days: int = 3,
         rng: Optional[random.Random] = None, today: Optional[date] = None
         ) -> Dict[str, Dict[str, Dict[str, int]]]:
    """Add a demo batch for each of the last `days` days; return counts per day."""
    rng = rng or random.Random()
    today = today or utcnow().date()
    summary = {}
    for back in range(days - 1, -1, -1):
        batch_date = today - timedelta(days=back)
        plan = PLAN + [rng.choice(EXTRAS) for _ in range(rng.randint(0, 4))]
        ids: List[int] = []
        for n, (status, verdict) in enumerate(plan):
            track = "remix" if status == "needs_reaction" else rng.choice(["remix", "motion"])
            asset = _new_asset(store, rng, batch_date, track, status, media_root, n=n)
            aid = asset["id"]
            ids.append(aid)
            if status == "needs_reaction":
                continue
            if status == "failed":
                _walk(store, aid, ("failed", "worker"))
                store.update_asset(aid, qc={"passed": False, "reason": rng.choice(QC_FAILURES)})
                continue
            _walk(store, aid, ("ready", "worker"))
            if status == "approved":
                _walk(store, aid, ("approved", "owner"))
            elif status == "archived":
                _walk(store, aid, ("archived", "owner"))
            elif status == "revision_requested":
                _walk(store, aid, ("revision_requested", "owner"))
                store.add_feedback(aid, "[demo] shorter intro, please", ["too_long"],
                                   video_time_s=0.5, wants_changes=True)
                # Today's new version is still rendering; older ones are done, which
                # archives the old version (the system move "when the new version is ready").
                done = back > 0
                child = _new_asset(store, rng, batch_date, track,
                                   "ready" if done else "rendering", media_root, n=n,
                                   parent=asset)
                ids.append(child["id"])
                if done:
                    _walk(store, child["id"], ("ready", "worker"))
                    _walk(store, aid, ("archived", "system"))
            if verdict != "none":
                set_verdict(store, aid, verdict)
            if verdict == "disliked":
                text, reasons = rng.choice(COMMENTS)
                store.add_feedback(aid, text, reasons)
        rows = [store.get_asset(i) for i in ids]
        summary[batch_date.isoformat()] = {
            "status": dict(Counter(r["status"] for r in rows)),
            "verdict": dict(Counter(r["verdict"] for r in rows)),
        }
    return summary
