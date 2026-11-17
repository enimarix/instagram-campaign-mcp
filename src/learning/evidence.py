"""
Evidence engine (step 081, GOAL.md §3.5): learnings checked against the numbers.

A learning whose scope names a predicate, `{"tag": "<dimension>", "value": "<value>"}` (the
dimensions tag_breakdown groups by), is compared every night with its matured Reels:
n = matching posts, index = their median engagement index (already relative to the account
baseline, 1.0 = typical). One `audience_index` evidence item carries the latest result.
- do/dont, audience or ads origin: n below EVIDENCE_MIN_N_MEDIUM → confidence low (the
  item notes "needs n ≥ X"); index past 1 ± EVIDENCE_MIN_EFFECT the right way → medium or
  high by n; the wrong way with n ≥ medium → status `contradicted` (a flag: the row stays,
  and goes back to active when the numbers turn). Confidence `owner` is never changed, nor
  is the status of an owner rule.
- taste learnings keep their confidence (it measures the owner's likes): they only get the
  item, and a `conflict` item when the numbers or an active audience learning on the same
  predicate (≥ medium) point the other way. Both sides of a conflict are marked; neither is
  retired. Conflicts are recomputed by refresh_learnings.
Learnings without a predicate are left alone.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from ..config import InstagramMCPSettings
from ..store import CampaignStore, to_iso
from ..taxonomy import validate
from .breakdowns import TAGS, duration_bucket, tag_breakdown

TAXONOMY_KINDS = {"track": "tracks", "pillar": "pillars", "hook_type": "hook_types",
                  "template": "templates"}
STRATEGIES = ("explore", "exploit")
DURATIONS = tuple(duration_bucket(s) for s in (0, 15, 30, 60))
AUDIENCE, CONFLICT = "audience_index", "conflict"
POST_TYPE = "REELS"  # ponytail: the studio makes Reels; add scope["post_type"] if feed returns


def predicate(scope: Any) -> Optional[Tuple[str, str]]:
    """(tag, value) of a scope's predicate, None when it has none; ValueError when invalid."""
    if not isinstance(scope, dict) or ("tag" not in scope and "value" not in scope):
        return None
    tag, value = scope.get("tag"), scope.get("value")
    if tag not in TAGS:
        raise ValueError(f"predicate tag must be one of {', '.join(TAGS)}, not {tag!r}")
    if value is None or isinstance(value, bool) or str(value).strip() == "":
        raise ValueError("a predicate needs a value")
    value = str(value).strip()
    if tag in TAXONOMY_KINDS:
        validate(TAXONOMY_KINDS[tag], value)
    elif tag == "strategy" and value not in STRATEGIES:
        raise ValueError(f"strategy must be one of {', '.join(STRATEGIES)}")
    elif tag == "duration" and value not in DURATIONS:
        raise ValueError(f"duration must be one of {', '.join(DURATIONS)}")
    elif tag == "hour" and not (value.isdigit() and 0 <= int(value) <= 23):
        raise ValueError("hour must be an owner-local hour 0-23")
    return tag, str(int(value)) if tag == "hour" else value


def _level(n: int, settings: InstagramMCPSettings) -> str:
    return ("low" if n < settings.evidence_min_n_medium
            else "medium" if n < settings.evidence_min_n_high else "high")


def _verdict(kind: str, n: int, index: Optional[float],
             settings: InstagramMCPSettings) -> str:
    """supports | contradicts | inconclusive (effect too small) | needs_n | untested (a
    hypothesis has no direction)."""
    if kind not in ("do", "dont"):
        return "untested"
    if index is None or _level(n, settings) == "low":
        return "needs_n"
    effect = (index - 1) if kind == "do" else (1 - index)
    if effect > settings.evidence_min_effect:
        return "supports"
    return "contradicts" if effect < -settings.evidence_min_effect else "inconclusive"


def evaluate_learning(store: CampaignStore, settings: InstagramMCPSettings,
                      learning: Dict[str, Any], *, now: datetime,
                      breakdowns: Optional[Dict[str, List[Dict[str, Any]]]] = None
                      ) -> Dict[str, Any]:
    """Check one learning against the numbers and store the result (see the module
    docstring); returns the row, unchanged without a predicate. `breakdowns` caches
    tag_breakdown groups per tag across calls."""
    pred = predicate(learning["scope"])
    if pred is None:
        return learning
    tag, value = pred
    cache = {} if breakdowns is None else breakdowns
    if tag not in cache:
        cache[tag] = tag_breakdown(store, settings, tag=tag, post_type=POST_TYPE,
                                   now=now)["groups"]
    group = next((g for g in cache[tag] if str(g["tag_value"]) == value), None)
    n = group["n"] if group else 0
    index = group and group["engagement_index"] and group["engagement_index"]["median"]
    verdict = _verdict(learning["kind"], n, index, settings)
    item: Dict[str, Any] = {"kind": AUDIENCE, "n": n, "index": index, "verdict": verdict,
                            "computed_at": to_iso(now)}
    if verdict == "needs_n":
        item["note"] = f"needs n ≥ {settings.evidence_min_n_medium}"

    fields: Dict[str, Any] = {"evidence": [e for e in learning["evidence"]
                                           if e.get("kind") != AUDIENCE] + [item]}
    if (learning["origin"] != "taste" and verdict != "untested"
            and learning["confidence"] != "owner"):
        if verdict == "contradicts":
            fields["status"] = "contradicted"
        else:
            fields["confidence"] = _level(n, settings) if verdict == "supports" else "low"
            if learning["status"] == "contradicted":
                fields["status"] = "active"
    return store.update_learning(learning["id"], **fields)


def _conflicts(learnings: List[Dict[str, Any]]) -> Dict[int, List[Dict[str, Any]]]:
    """Conflict items per learning id: a taste do/dont against an active audience
    learning of the opposite kind on the same predicate (≥ medium), or against the numbers."""
    out: Dict[int, List[Dict[str, Any]]] = {r["id"]: [] for r in learnings}
    audience = [r for r in learnings if r["origin"] == "audience" and r["status"] == "active"
                and r["kind"] in ("do", "dont") and r["confidence"] != "low"]
    for t in learnings:
        if t["origin"] != "taste" or t["kind"] not in ("do", "dont"):
            continue
        for a in audience:
            if a["scope_pred"] == t["scope_pred"] and a["kind"] != t["kind"]:
                out[t["id"]].append({"kind": CONFLICT, "with": a["id"],
                                     "detail": f"audience learning says {a['kind']}"})
                out[a["id"]].append({"kind": CONFLICT, "with": t["id"],
                                     "detail": f"the owner's taste says {t['kind']}"})
        item = next((e for e in t["evidence"] if e.get("kind") == AUDIENCE), None)
        if item and item["verdict"] == "contradicts":
            out[t["id"]].append({"kind": CONFLICT, "with": None,
                                 "detail": f"audience index {item['index']} over"
                                           f" {item['n']} posts"})
    return out


def refresh_learnings(store: CampaignStore, settings: InstagramMCPSettings,
                      now: datetime) -> Dict[str, Any]:
    """Re-evaluate every active or contradicted learning with a predicate, then recompute
    the conflict items. A stored predicate that no longer validates is skipped and listed."""
    breakdowns: Dict[str, List[Dict[str, Any]]] = {}
    evaluated, skipped = [], []
    # ponytail: every learning in one read; page it if the table ever passes ~10k rows
    for row in store.list_learnings(limit=1_000_000):
        if row["status"] == "retired":
            continue
        try:
            pred = predicate(row["scope"])
        except ValueError as e:
            skipped.append({"id": row["id"], "error": str(e)})
            continue
        if pred is not None:
            new = evaluate_learning(store, settings, row, now=now, breakdowns=breakdowns)
            evaluated.append({**new, "scope_pred": pred})
    conflicts = _conflicts(evaluated)
    for row in evaluated:
        kept = [e for e in row["evidence"] if e.get("kind") != CONFLICT]
        if kept + conflicts[row["id"]] != row["evidence"]:
            store.update_learning(row["id"], evidence=kept + conflicts[row["id"]])
    return {"evaluated": len(evaluated),
            "contradicted": [r["id"] for r in evaluated if r["status"] == "contradicted"],
            "conflicts": sorted(i for i, c in conflicts.items() if c), "skipped": skipped}
