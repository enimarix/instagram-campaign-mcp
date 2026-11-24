"""
Today's quotas (step 056, GOAL.md §3.1-3.2): how many ideas of each kind a daily batch may
hold, and how many it already holds. create_idea refuses ideas over a limit; the creative
brief (055) shows the same numbers to the agent.

- batch: BATCH_SIZE ideas in all, fewer when the bench is full (step 055): every liked,
  unpublished video beyond BENCH_TARGET_DAYS x MAX_POSTS_PER_DAY takes one idea off, down
  to BATCH_FLOOR, so learning never stops. That effective size is the batch below.
  BATCH_SIZE 0 = no limit (owner, 206): limits.ideas and effective_batch_size are None, no
  bench brake, and the shares below apply to the batch so far, the next idea included.
- explore: at most ceil(BATCH_SIZE x EXPLORE_SHARE) ideas with strategy `explore`, from the
  configured size (the cut comes out of exploit), capped at the effective batch.
- humour: target round(batch x share), allowed +/- 1, where share is the humour share of
  the day's batch mix (086a, stored when the brief is made; it starts from HUMOUR_SHARE)
  or HUMOUR_SHARE before that,
  so humour <= target + 1 and informative (every other idea, with or without a pillar) <= batch - target + 1. A humour
  idea is one whose pillar has `"humour": true` in brand/taxonomy.json.
- reactions (track `remix`): at most MAX_REACTIONS_PER_DAY + REACTION_MARGIN, and never more
  than the clips available. A clip is available when it is a `clip` source (research
  references never count), downloaded (a source with a
  `local_path`), its rights are known (rights_basis != unknown: such a clip is never
  queued) and no idea uses it yet.
- reactions_plan (073): how many reactions a run still makes, DM picks first (picks `new`
  or `downloaded`, not made yet), then viral finds; limits.reactions grows as downloads
  land, the plan says how many to download.
- styles (138): today's ideas per style, and for a style the owner gave a daily share
  (Settings, src/studio/styles.py) a limit of ceil(batch x share), at least 1.
"""

from __future__ import annotations

from datetime import date, datetime
from math import ceil
from typing import Any, Dict, List, Optional, Set, Union

from ..config import InstagramMCPSettings
from ..store import CampaignStore, utcnow
from ..studio import styles
from ..studio.scheduling import bench
from ..taxonomy import load_taxonomy

_AVAILABLE_CLIPS = ("SELECT COUNT(*) FROM sources s WHERE s.role = 'clip'"
                    " AND s.local_path IS NOT NULL AND s.rights_basis != 'unknown'"
                    " AND NOT EXISTS (SELECT 1 FROM ideas i WHERE i.source_id = s.id)")
MIX_STATE = "batch_mix:"  # + batch date: that day's mix shares (src/learning/mix.py)


def flagged_pillars(flag: str) -> Set[str]:
    """Ids of the pillars with `flag: true` in brand/taxonomy.json."""
    return {p["id"] for p in load_taxonomy()["pillars"]["values"] if p.get(flag)}


def available_clips(store: CampaignStore) -> int:
    with store._tx() as c:
        return c.execute(_AVAILABLE_CLIPS).fetchone()[0]


def reaction_plan(settings: InstagramMCPSettings, made: int, picks: int) -> Dict[str, int]:
    """{room, picks, viral}: reactions still allowed today (MAX_REACTIONS_PER_DAY +
    REACTION_MARGIN minus the `made` ones), DM picks first; picks over the cap wait for
    the next day."""
    room = max(0, settings.max_reactions_per_day + settings.reaction_margin - made)
    from_picks = min(picks, room)
    return {"room": room, "picks": from_picks, "viral": room - from_picks}


def effective_batch_size(settings: InstagramMCPSettings, bench_count: int) -> Dict[str, int]:
    """{effective_batch_size, bench_surplus}: the configured size minus the bench surplus,
    never below batch_floor nor above batch_size."""
    surplus = max(0, bench_count - settings.bench_target_days * settings.max_posts_per_day)
    if not settings.batch_size:  # 0: no limit (206)
        return {"effective_batch_size": None, "bench_surplus": surplus}
    effective = min(settings.batch_size, max(settings.batch_floor, settings.batch_size - surplus))
    return {"effective_batch_size": effective, "bench_surplus": surplus}


def todays_quotas(store: CampaignStore, settings: InstagramMCPSettings,
                  day: Union[date, str], now: Optional[datetime] = None) -> Dict[str, Any]:
    """{date, limits, counts, humour_target, clips_available, reactions_plan, batch_size,
    effective_batch_size, bench_surplus, styles} for the batch of `day`; the bench is read
    at `now`. limits and counts share the keys ideas, explore, humour, informative,
    reactions; styles: {style: {count, limit (None: no share set)}}."""
    day = date.fromisoformat(day) if isinstance(day, str) else day
    ideas = store.list_ideas(batch_date=day, limit=100_000)
    humour = flagged_pillars("humour")
    sizes = effective_batch_size(settings, len(bench(store, settings, now or utcnow())["assets"]))
    batch = sizes["effective_batch_size"]
    counts = {
        "ideas": len(ideas),
        "explore": sum(i["strategy"] == "explore" for i in ideas),
        "humour": sum(i["pillar"] in humour for i in ideas),
        "reactions": sum(i["track"] == "remix" for i in ideas),
    }
    counts["informative"] = counts["ideas"] - counts["humour"]
    # no limit: the shares apply to the batch so far, the next idea included
    size = batch if batch is not None else counts["ideas"] + 1
    # round() first: 10 * 0.3 is 3.0000000000000004 in floats, and ceil would make it 4.
    explore_max = min(size, ceil(round((settings.batch_size or size) * settings.explore_share, 6)))
    mix = store.get_state(MIX_STATE + day.isoformat()) or {}
    target = round(size * mix.get("humour", {}).get("humour", settings.humour_share))
    clips = available_clips(store)
    limits = {
        "ideas": batch, "explore": explore_max, "humour": target + 1,
        "informative": size - target + 1,
        "reactions": min(settings.max_reactions_per_day + settings.reaction_margin,
                         counts["reactions"] + clips),
    }
    with store._tx() as c:
        picks = c.execute("SELECT COUNT(*) FROM dm_picks"
                          " WHERE status IN ('new','downloaded')").fetchone()[0]
    return {"date": day.isoformat(), "limits": limits, "counts": counts,
            "humour_target": target, "clips_available": clips,
            "reactions_plan": reaction_plan(settings, counts["reactions"], picks),
            "batch_size": settings.batch_size, **sizes,
            "styles": style_quotas(store, ideas, size)}


def style_quotas(store: CampaignStore, ideas: List[Dict[str, Any]],
                 batch: int) -> Dict[str, Dict[str, Any]]:
    """{style: {count, limit}} for the styles used today or given a share by the owner."""
    shares = {s: c["share"] for s, c in styles.owner_choices(store).items() if c.get("share")}
    counts: Dict[str, int] = {}
    for i in ideas:
        if i["style"]:
            counts[i["style"]] = counts.get(i["style"], 0) + 1
    return {s: {"count": counts.get(s, 0),
                "limit": max(1, ceil(round(batch * shares[s], 6))) if s in shares else None}
            for s in {**counts, **shares}}
