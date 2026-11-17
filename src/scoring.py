"""
Winner scoring for organic posts.

A post is judged against the account's own recent posts of the same kind
(feed posts vs Reels vs Stories), never against generic industry numbers:
a small new account and a big one have very different "normal".

For each signal we compute a per-reach rate (shares/reach, saves/reach, ...),
divide by the median rate of the baseline posts, and take a weighted average.
That gives the engagement index: 1.0 = typical post, 2.0 = twice as engaging.
Reach is indexed the same way. Saves, shares and follows weigh most because
they predict paid performance better than likes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from statistics import mean, median
from typing import Any, Dict, List, Optional

DEFAULT_WEIGHTS: Dict[str, float] = {
    "shares": 3.0,
    "saved": 3.0,
    "follows": 4.0,
    "profile_visits": 2.0,
    "comments": 1.5,
    "likes": 0.5,
    "ig_reels_avg_watch_time": 2.0,  # absolute (ms), not divided by reach
}
ABSOLUTE_SIGNALS = {"ig_reels_avg_watch_time"}
RATIO_CAP = 5.0          # one freak metric can't carry a post
SMOOTHING = 0.0005       # avoids divide-by-zero when the baseline rate is ~0
STORY_MIN_AGE_HOURS = 20.0
STORY_LIFETIME = timedelta(hours=24)
# Second way to win: reach this many times the median with at least median
# engagement (a post that travelled far without diluting engagement).
REACH_WINNER_INDEX = 2.0


@dataclass
class ScoringConfig:
    min_age_hours: float = 48.0
    min_reach: int = 300
    winner_threshold: float = 1.5
    baseline_window: int = 30
    weights: Dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))


def group_of(snapshot: Dict[str, Any]) -> str:
    pt = (snapshot.get("media_product_type") or "FEED").upper()
    if pt == "REELS":
        return "REELS"
    if pt == "STORY":
        return "STORY"
    return "FEED"


def _num(v: Any) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _signal_value(metrics: Dict[str, Any], signal: str) -> Optional[float]:
    if signal not in metrics or metrics[signal] is None:
        return None
    value = _num(metrics[signal])
    if signal in ABSOLUTE_SIGNALS:
        return value
    reach = _num(metrics.get("reach"))
    return value / reach if reach > 0 else None


def _is_matured(snap: Dict[str, Any], cfg: ScoringConfig) -> bool:
    age = snap.get("age_hours")
    if age is None:
        return False
    limit = STORY_MIN_AGE_HOURS if group_of(snap) == "STORY" else cfg.min_age_hours
    return age >= limit


def _story_expired(snap: Dict[str, Any], now: datetime) -> bool:
    posted = snap.get("posted_at")
    if not posted:
        return False
    try:
        dt = datetime.fromisoformat(str(posted).replace("Z", "+00:00"))
    except ValueError:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return now - dt >= STORY_LIFETIME


def _at_age(
    snap: Dict[str, Any],
    history: Dict[str, List[Dict[str, Any]]],
    target_age: Optional[float],
    cfg: "ScoringConfig",
) -> Dict[str, Any]:
    """The matured snapshot of `snap`'s post whose age is closest to target_age.

    Comparing a 48h-old post with baseline posts measured at 30 days would make
    every new post look weak on reach, so baselines are read at a similar age
    when the history has it.
    """
    if target_age is None:
        return snap
    candidates = [s for s in history.get(snap["media_id"], []) if _is_matured(s, cfg)]
    if not candidates:
        return snap
    return min(candidates, key=lambda s: abs((s.get("age_hours") or 0) - target_age))


def score_posts(
    snapshots: List[Dict[str, Any]],
    cfg: Optional[ScoringConfig] = None,
    labels: Optional[Dict[str, Dict[str, Any]]] = None,
    history: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Score the latest snapshot of each post. Returns newest-first list.

    history: all snapshots per media_id (optional). When given, each baseline
    post is read at the age closest to the scored post's age.
    """
    cfg = cfg or ScoringConfig()
    labels = labels or {}
    history = history or {}
    now = now or datetime.now(timezone.utc)
    matured_by_group: Dict[str, List[Dict[str, Any]]] = {}
    for s in snapshots:  # snapshots arrive newest-first
        if _is_matured(s, cfg):
            matured_by_group.setdefault(group_of(s), []).append(s)

    results = []
    for snap in snapshots:
        grp = group_of(snap)
        metrics = snap.get("metrics") or {}
        reach = _num(metrics.get("reach"))
        baseline = [
            _at_age(b, history, snap.get("age_hours"), cfg)
            for b in matured_by_group.get(grp, []) if b["media_id"] != snap["media_id"]
        ][: cfg.baseline_window]

        res: Dict[str, Any] = {
            "media_id": snap["media_id"],
            "group": grp,
            "posted_at": snap.get("posted_at"),
            "age_hours": snap.get("age_hours"),
            "permalink": snap.get("permalink"),
            "caption": (snap.get("caption") or "")[:120],
            "reach": int(reach),
            "baseline_posts": len(baseline),
            "confidence": "low" if len(baseline) < 5 else "medium" if len(baseline) < 15 else "high",
            "label": labels.get(snap["media_id"]),
        }

        if not _is_matured(snap, cfg):
            if grp == "STORY" and _story_expired(snap, now):
                res.update(verdict="incomplete", engagement_index=None, reach_index=None,
                           drivers=[], why=(
                               f"Story expired before a snapshot at {STORY_MIN_AGE_HOURS:.0f}h+; "
                               "keep the scheduler daemon running (it snapshots live "
                               "Stories hourly) or run `ig-campaign collect --stories-only` hourly"))
            else:
                res.update(verdict="too_early", engagement_index=None, reach_index=None,
                           drivers=[], why="Insights still accumulating")
            results.append(res)
            continue
        if not baseline:
            res.update(verdict="no_baseline", engagement_index=None, reach_index=None,
                       drivers=[], why="Need at least one other matured post of the same type")
            results.append(res)
            continue

        weighted, total_w, ratios = 0.0, 0.0, {}
        for signal, w in cfg.weights.items():
            value = _signal_value(metrics, signal)
            if value is None:
                continue
            base_vals = [
                v for v in (_signal_value(b.get("metrics") or {}, signal) for b in baseline)
                if v is not None
            ]
            if not base_vals:
                continue
            smooth = 0.0 if signal in ABSOLUTE_SIGNALS else SMOOTHING
            base = median(base_vals)
            if base + smooth <= 0:
                continue
            ratio = min((value + smooth) / (base + smooth), RATIO_CAP)
            ratios[signal] = round(ratio, 2)
            weighted += w * ratio
            total_w += w

        base_reach = median([_num((b.get("metrics") or {}).get("reach")) for b in baseline])
        reach_index = round(reach / base_reach, 2) if base_reach > 0 else None
        eng = round(weighted / total_w, 2) if total_w else None
        drivers = sorted(ratios, key=ratios.get, reverse=True)[:3]

        verdict, why = _verdict(eng, reach_index, reach, cfg)
        res.update(
            engagement_index=eng,
            reach_index=reach_index,
            signal_ratios=ratios,
            drivers=[f"{d} x{ratios[d]}" for d in drivers],
            verdict=verdict,
            why=why,
        )
        results.append(res)
    return results


def _verdict(eng: Optional[float], reach_index: Optional[float], reach: float,
             cfg: ScoringConfig) -> tuple[str, str]:
    if eng is None:
        return "no_signal", "No comparable metrics returned for this post"
    if reach < cfg.min_reach:
        if eng >= cfg.winner_threshold:
            return "promising", f"Strong engagement but reach {int(reach)} < {cfg.min_reach}; too small a sample"
        return "inconclusive", f"Reach {int(reach)} < {cfg.min_reach}"
    if eng >= cfg.winner_threshold:
        return "winner", f"Engagement {eng}x the account median"
    if reach_index is not None and reach_index >= REACH_WINNER_INDEX and eng >= 1.0:
        return "winner", f"Reach {reach_index}x median with above-median engagement"
    if eng >= 1.2:
        return "promising", f"Engagement {eng}x median, below the {cfg.winner_threshold}x bar"
    if eng < 0.7:
        return "weak", f"Engagement {eng}x median"
    return "average", f"Engagement {eng}x median"


def compare_variants(scored: List[Dict[str, Any]], campaign: str) -> Dict[str, Any]:
    """Aggregate scored posts of one campaign by variant label."""
    by_variant: Dict[str, List[Dict[str, Any]]] = {}
    for r in scored:
        label = r.get("label") or {}
        if label.get("campaign") != campaign or r.get("engagement_index") is None:
            continue
        by_variant.setdefault(label.get("variant") or "unlabelled", []).append(r)

    rows = []
    for variant, posts in by_variant.items():
        rows.append({
            "variant": variant,
            "posts": len(posts),
            "avg_engagement_index": round(mean(p["engagement_index"] for p in posts), 2),
            "avg_reach": int(mean(p["reach"] for p in posts)),
            "winners": sum(1 for p in posts if p["verdict"] == "winner"),
            "hypothesis": next(((p.get("label") or {}).get("hypothesis") for p in posts
                                if (p.get("label") or {}).get("hypothesis")), None),
            "media_ids": [p["media_id"] for p in posts],
        })
    rows.sort(key=lambda r: r["avg_engagement_index"], reverse=True)

    note = None
    if len(rows) < 2:
        note = "Need at least two variants with matured posts to compare."
    elif min(r["posts"] for r in rows) < 3:
        note = ("Fewer than 3 matured posts in some variant: treat the leader as a hint, "
                "not a result. Organic reach varies a lot post to post.")
    elif rows[0]["avg_engagement_index"] < rows[1]["avg_engagement_index"] * 1.2:
        note = "Leader is less than 20% ahead: likely noise. Keep testing."
    return {
        "campaign": campaign,
        "variants": rows,
        "leader": rows[0]["variant"] if rows and not note else None,
        "note": note,
    }
