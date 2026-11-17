"""
Today's quotas (step 056, GOAL.md §3.1-3.2): how many ideas of each kind a daily batch may
hold, and how many it already holds. create_idea refuses ideas over a limit; the creative
brief (055) shows the same numbers to the agent.

- batch: BATCH_SIZE ideas in all.
- explore: at most ceil(batch x EXPLORE_SHARE) ideas with strategy `explore`.
- humour: target round(batch x HUMOUR_SHARE), allowed +/- 1, so humour <= target + 1 and
  informative (every other idea, with or without a pillar) <= batch - target + 1. A humour
  idea is one whose pillar has `"humour": true` in brand/taxonomy.json.
- reactions (track `remix`): at most MAX_REACTIONS_PER_DAY + REACTION_MARGIN, and never more
  than the clips available. A clip is available when it is downloaded (a source with a
  `local_path`), its rights are known (rights_basis != unknown: such a clip is never
  queued) and no idea uses it yet.
"""

from __future__ import annotations

from datetime import date
from math import ceil
from typing import Any, Dict, Set, Union

from ..config import InstagramMCPSettings
from ..store import CampaignStore
from ..taxonomy import load_taxonomy

_AVAILABLE_CLIPS = ("SELECT COUNT(*) FROM sources s WHERE s.local_path IS NOT NULL"
                    " AND s.rights_basis != 'unknown'"
                    " AND NOT EXISTS (SELECT 1 FROM ideas i WHERE i.source_id = s.id)")


def flagged_pillars(flag: str) -> Set[str]:
    """Ids of the pillars with `flag: true` in brand/taxonomy.json."""
    return {p["id"] for p in load_taxonomy()["pillars"]["values"] if p.get(flag)}


def available_clips(store: CampaignStore) -> int:
    with store._tx() as c:
        return c.execute(_AVAILABLE_CLIPS).fetchone()[0]


def todays_quotas(store: CampaignStore, settings: InstagramMCPSettings,
                  day: Union[date, str]) -> Dict[str, Any]:
    """{date, limits, counts, humour_target, clips_available} for the batch of `day`.
    limits and counts share the keys ideas, explore, humour, informative, reactions."""
    day = date.fromisoformat(day) if isinstance(day, str) else day
    ideas = store.list_ideas(batch_date=day, limit=100_000)
    humour = flagged_pillars("humour")
    batch = settings.batch_size
    # round() first: 10 * 0.3 is 3.0000000000000004 in floats, and ceil would make it 4.
    explore_max = ceil(round(batch * settings.explore_share, 6))
    target = round(batch * settings.humour_share)
    clips = available_clips(store)
    counts = {
        "ideas": len(ideas),
        "explore": sum(i["strategy"] == "explore" for i in ideas),
        "humour": sum(i["pillar"] in humour for i in ideas),
        "reactions": sum(i["track"] == "remix" for i in ideas),
    }
    counts["informative"] = counts["ideas"] - counts["humour"]
    limits = {
        "ideas": batch, "explore": explore_max, "humour": target + 1,
        "informative": batch - target + 1,
        "reactions": min(settings.max_reactions_per_day + settings.reaction_margin,
                         counts["reactions"] + clips),
    }
    return {"date": day.isoformat(), "limits": limits, "counts": counts,
            "humour_target": target, "clips_available": clips}
