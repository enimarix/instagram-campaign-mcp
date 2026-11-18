"""
Batch mix (step 086a, GOAL.md §3.5): the share of the next batch each template, hook type,
pillar and humour vs informative gets. A pure function with tests, not a prompt.

- like rate (fast signal): Thompson sampling. Each option draws from Beta(1 + likes,
  1 + dislikes), DRAWS times, with an rng seeded by the batch date and the dimension; its
  score is how often its draw wins. Verdicts on assets of the last LIKE_DAYS batch days.
- engagement index (slow signal, tag_breakdown of matured Reels over INDEX_DAYS, 1.0 =
  account typical): the options with at least MIX_MIN_POSTS posts re-split
  MIX_INDEX_WEIGHT of the score they hold together in proportion to their index. One such
  option alone keeps its score: the index only ranks options against each other.
- floor: every allowed option gets MIX_FLOOR (min(floor, 1/k) for k options, so floors
  never exceed the whole), the rest is split by score.
- owner rules: an active `dont` learning at confidence `owner` whose scope predicate names
  an option (081) sets its share to 0, outside the floor.
- humour vs informative starts from the owner's HUMOUR_SHARE (website setting, 125): the
  learned shares weigh it, so with no verdicts the split is the owner's.
- pillars are split inside humour vs informative (taxonomy pillar flag `humour`, every
  other pillar or none is informative): pillar share = group share x share inside the
  group, so the two dimensions always agree. A pillar's floor is therefore a floor inside
  its group.
Same date and data, same mix. batch_mix keeps each day's shares in worker state
(MIX_STATE + date, read by todays_quotas for the humour target) and `moved` lists the
shares that changed by MOVED or more since yesterday's.
"""

from __future__ import annotations

import random
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple, Union

from ..config import InstagramMCPSettings
from ..store import CampaignStore
from ..taxonomy import load_taxonomy
from .breakdowns import tag_breakdown
from .evidence import POST_TYPE, predicate
from .quotas import MIX_STATE, flagged_pillars

DRAWS = 2000
LIKE_DAYS = 30
INDEX_DAYS = 90
MOVED = 0.05
MAX_MOVED = 10
TAXONOMY_KINDS = {"template": "templates", "hook_type": "hook_types", "pillar": "pillars"}
DIMENSIONS = ("template", "hook_type", "pillar", "humour")
HUMOUR = ("humour", "informative")
IndexStats = Mapping[str, Tuple[int, Optional[float]]]  # option -> (posts, median index)

_VERDICTS = (
    "SELECT i.pillar, i.hook_type, a.verdict,"
    " CASE WHEN json_extract(a.recipe, '$.kind') = 'motion'"
    " THEN json_extract(a.recipe, '$.template') END AS template"
    " FROM assets a JOIN ideas i ON i.id = a.idea_id"
    " WHERE a.verdict IN ('liked', 'disliked') AND a.batch_date > ? AND a.batch_date <= ?")


def allocate(options: Iterable[str], likes: Mapping[str, int], dislikes: Mapping[str, int],
             index_stats: IndexStats, rules: Iterable[str], *, rng: random.Random,
             floor: float = 0.10, min_posts: int = 5, index_weight: float = 0.5,
             draws: int = DRAWS) -> Dict[str, float]:
    """{option: share} summing to 1 over the options not in `rules` (see the module
    docstring); all 0 when every option is ruled out."""
    options, rules = list(options), set(rules)
    shares = dict.fromkeys(options, 0.0)
    allowed = [o for o in options if o not in rules]
    if not allowed:
        return shares
    wins = Counter(max(allowed, key=lambda o: rng.betavariate(1 + likes.get(o, 0),
                                                              1 + dislikes.get(o, 0)))
                   for _ in range(draws))
    score = {o: wins[o] / draws for o in allowed}
    ripe = [o for o in allowed if o in index_stats and index_stats[o][0] >= min_posts
            and index_stats[o][1] is not None]
    total = sum(index_stats[o][1] for o in ripe)
    if total > 0:
        mass = sum(score[o] for o in ripe)
        for o in ripe:
            score[o] = ((1 - index_weight) * score[o]
                        + index_weight * mass * index_stats[o][1] / total)
    # ponytail: with 1/floor options or more every share is equal (no learning); lower
    # MIX_FLOOR if a dimension ever gets that many options.
    floor = min(floor, 1 / len(allowed))
    for o in allowed:
        shares[o] = floor + (1 - floor * len(allowed)) * score[o]
    return shares


def largest_remainder(shares: Mapping[str, float], n: int) -> Dict[str, int]:
    """Whole counts summing to n in proportion to the shares (0 everywhere when no share)."""
    total = sum(shares.values())
    if total <= 0 or n <= 0:
        return dict.fromkeys(shares, 0)
    exact = {o: s / total * n for o, s in shares.items()}
    counts = {o: int(x) for o, x in exact.items()}
    for o in sorted(exact, key=lambda o: exact[o] - counts[o],
                    reverse=True)[:n - sum(counts.values())]:
        counts[o] += 1
    return counts


def with_counts(mix: Dict[str, Any], n: int) -> Dict[str, Any]:
    """The mix with a `count` per row: n ideas split by share in every dimension."""
    for dim in DIMENSIONS:
        counts = largest_remainder({r["option"]: r["share"] for r in mix[dim]}, n)
        for row in mix[dim]:
            row["count"] = counts[row["option"]]
    return mix


def _verdicts(store: CampaignStore, day: date) -> Tuple[Dict[str, Counter], Dict[str, Counter]]:
    likes: Dict[str, Counter] = defaultdict(Counter)
    dislikes: Dict[str, Counter] = defaultdict(Counter)
    since = (day - timedelta(days=LIKE_DAYS)).isoformat()
    with store._tx() as c:
        for r in c.execute(_VERDICTS, (since, day.isoformat())):
            side = likes if r["verdict"] == "liked" else dislikes
            for dim in TAXONOMY_KINDS:
                side[dim][r[dim]] += 1
    return likes, dislikes


def _owner_rules(store: CampaignStore) -> Dict[str, set]:
    rules: Dict[str, set] = defaultdict(set)
    for row in store.list_learnings(kind="dont", status="active", limit=100_000):
        if row["confidence"] != "owner":
            continue
        try:
            pred = predicate(row["scope"])
        except ValueError:  # a stored scope that no longer validates: not a rule
            continue
        if pred:
            rules[pred[0]].add(pred[1])
    return rules


def _index(store: CampaignStore, settings: InstagramMCPSettings, dim: str, options: set,
           now: Optional[datetime]) -> Dict[str, Tuple[int, Optional[float]]]:
    groups = tag_breakdown(store, settings, tag=dim, post_type=POST_TYPE, days=INDEX_DAYS,
                           now=now)["groups"]
    return {g["tag_value"]: (g["n"], g["engagement_index"] and g["engagement_index"]["median"])
            for g in groups if g["tag_value"] in options}


def _why(rule: bool, likes: int, dislikes: int, posts: int, index: Optional[float],
         min_posts: int) -> str:
    if rule:
        return "owner rule: never"
    why = f"{likes} liked, {dislikes} disliked"
    if index is not None:
        why += f"; index {index} over {posts} Reels"
        if posts < min_posts:
            why += f" (counts from {min_posts})"
    return why


def _owner_humour(learned: Dict[str, float], owner: float) -> Dict[str, float]:
    """The owner's HUMOUR_SHARE is where the humour split starts; likes move it from there:
    each side's learned share is weighted by the owner's (no data, 50/50 learned: exactly
    the owner's share; an owner rule's zero stays zero)."""
    h, i = learned["humour"] * owner, learned["informative"] * (1 - owner)
    return learned if h + i == 0 else {"humour": h / (h + i), "informative": i / (h + i)}


def batch_mix(store: CampaignStore, settings: InstagramMCPSettings,
              batch_date: Union[date, str], *, now: Optional[datetime] = None) -> Dict[str, Any]:
    """{template, hook_type, pillar, humour: [{option, share, likes, dislikes, posts, index,
    why}], moved: [{dimension, option, from, to, why}]} for the batch of `batch_date`;
    stores today's shares (see the module docstring)."""
    day = date.fromisoformat(batch_date) if isinstance(batch_date, str) else batch_date
    tax = load_taxonomy()
    options = {d: [v["id"] for v in tax[k]["values"]] for d, k in TAXONOMY_KINDS.items()}
    humour = flagged_pillars("humour")
    group = {p: "humour" if p in humour else "informative" for p in options["pillar"]}
    likes, dislikes = _verdicts(store, day)
    rules = _owner_rules(store)
    index = {d: _index(store, settings, d, set(options[d]), now) for d in TAXONOMY_KINDS}

    for side in (likes, dislikes):
        for p, n in list(side["pillar"].items()):
            side["humour"][group.get(p, "informative")] += n
    index["humour"] = {}
    for g in HUMOUR:
        rows = [(n, i) for p, (n, i) in index["pillar"].items() if group[p] == g and i is not None]
        posts = sum(n for n, _ in rows)
        index["humour"][g] = (posts, round(sum(n * i for n, i in rows) / posts, 2) if posts
                              else None)
    rules["humour"] = {g for g in HUMOUR
                       if all(p in rules["pillar"] for p in options["pillar"] if group[p] == g)}

    kw = {"floor": settings.mix_floor, "min_posts": settings.mix_min_posts,
          "index_weight": settings.mix_index_weight}

    def mix(dim: str, opts: Iterable[str], seed: str) -> Dict[str, float]:
        return allocate(opts, likes[dim], dislikes[dim], index[dim], rules[dim],
                        rng=random.Random(f"{day.isoformat()}:{seed}"), **kw)

    shares = {d: mix(d, options[d], d) for d in ("template", "hook_type")}
    shares["humour"] = _owner_humour(mix("humour", HUMOUR, "humour"), settings.humour_share)
    shares["pillar"] = {}
    for g in HUMOUR:
        inner = mix("pillar", [p for p in options["pillar"] if group[p] == g], f"pillar:{g}")
        shares["pillar"].update({p: s * shares["humour"][g] for p, s in inner.items()})
    shares["pillar"] = {p: shares["pillar"][p] for p in options["pillar"]}  # taxonomy order

    out: Dict[str, Any] = {}
    for dim in DIMENSIONS:
        out[dim] = []
        for o, s in shares[dim].items():
            posts, idx = index[dim].get(o, (0, None))
            out[dim].append({"option": o, "share": round(s, 3), "likes": likes[dim][o],
                             "dislikes": dislikes[dim][o], "posts": posts, "index": idx,
                             "why": _why(o in rules[dim], likes[dim][o], dislikes[dim][o],
                                         posts, idx, settings.mix_min_posts)})

    current = {d: {r["option"]: r["share"] for r in out[d]} for d in DIMENSIONS}
    before = store.get_state(MIX_STATE + (day - timedelta(days=1)).isoformat())
    store.set_state(MIX_STATE + day.isoformat(), current)
    moved = [] if before is None else [
        {"dimension": d, "option": r["option"], "from": before.get(d, {}).get(r["option"], 0.0),
         "to": r["share"], "why": r["why"]}
        for d in DIMENSIONS for r in out[d]
        if abs(r["share"] - before.get(d, {}).get(r["option"], 0.0)) >= MOVED]
    moved.sort(key=lambda m: -abs(m["to"] - m["from"]))
    return {**out, "moved": moved[:MAX_MOVED]}
