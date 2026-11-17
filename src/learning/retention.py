"""
Retention diagnosis (step 111, GOAL.md §3.5 "The late-night analysis"): for a matured Reel,
where and why viewers left, from its metrics lined up with the video's own timeline (110:
assets.timeline, [{"t": start_s, "d": dur_s, "e": "what happens"}]). No AI.

What the Graph API gives (Media Insights reference, Graph API v25): no per-second retention
curve. `reels_skip_rate` = % of views skipped in the first 3 s (estimated, in development);
`ig_reels_avg_watch_time` = average play time (no unit stated; ms, as 075 reads it);
`ig_reels_video_view_total_time` = total play time including replays (in development). Replay counts (`clips_replays_count`,
`ig_reels_aggregated_all_plays_count`) were removed in v22. So the only "exit second" is the
average watch time: one number, the spread of the real exits around it is unknown.

Baselines are the scorer's (scoring.baseline_for: the newest matured Reels of the account,
read at a similar age), compared by median. Findings:
- hook: skip rate >= WORSE x the median; quotes the events starting in the first 3 s.
- exit: the average viewer's exit second (< the video length) and the event playing then.
  Always low confidence (an average of a spread we cannot see).
- payoff: watch ratio at or above the median but shares+saves per reach < BETTER x it.
- strong: skip rate <= BETTER x the median, or watch ratio >= WORSE x it; quotes the hook.
Other comparisons carry scoring.confidence(n) of the baseline posts with that metric (n < 5:
low). A missing metric or baseline gives no finding; without a timeline, no event.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from statistics import median
from typing import Any, Dict, List, Optional

from ..campaign import scoring_config
from ..config import InstagramMCPSettings
from ..scoring import (
    WATCH_TIME,
    _is_matured,
    _min_age,
    baseline_for,
    confidence,
    group_of,
    matured_by_group,
    watch_ratio,
)
from ..store import CampaignStore, parse_dt

HOOK_S = 3.0  # reels_skip_rate's window
HOOK_EVENTS = 3
WORSE, BETTER = 1.2, 0.8  # x the baseline median
SKIP, RATIO, SHARE_SAVE = "reels_skip_rate", "watch_ratio", "share_save_rate"


def share_save_rate(metrics: Dict[str, Any]) -> Optional[float]:
    """(shares + saves) / reach; None when any of them is unknown."""
    if any(metrics.get(k) is None for k in ("shares", "saved")) or not metrics.get("reach"):
        return None
    return (metrics["shares"] + metrics["saved"]) / metrics["reach"]


def _values(metrics: Dict[str, Any], duration_s: Any) -> Dict[str, Optional[float]]:
    return {SKIP: metrics.get(SKIP), RATIO: watch_ratio(metrics, duration_s),
            SHARE_SAVE: share_save_rate(metrics)}


def baseline_medians(snaps: List[Dict[str, Any]],
                     durations: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """{metric: {median, n}} over the baseline posts that have the metric."""
    rows = [_values(s.get("metrics") or {}, durations.get(s["media_id"])) for s in snaps]
    out = {}
    for name in (SKIP, RATIO, SHARE_SAVE):
        vals = [r[name] for r in rows if r[name] is not None]
        out[name] = {"median": median(vals) if vals else None, "n": len(vals)}
    return out


def diagnose(timeline: Optional[List[Dict[str, Any]]], duration_s: Optional[float],
             metrics: Dict[str, Any],
             baseline: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The findings of one Reel (see the module docstring), pure."""
    timeline = sorted(timeline or [], key=lambda e: e["t"])
    v = _values(metrics, duration_s)
    hook = [e["e"] for e in timeline if e["t"] < HOOK_S][:HOOK_EVENTS]
    hook_txt = f" On screen then: {'; '.join(repr(e) for e in hook)}." if hook else ""

    def ev(name: str) -> Optional[Dict[str, Any]]:
        b = baseline.get(name) or {}
        if v[name] is None or not b.get("median"):
            return None
        return {name: round(v[name], 4), "baseline_median": round(b["median"], 4), "n": b["n"]}

    def finding(kind: str, evidence: Dict[str, Any], text: str, *, at_s: Optional[float] = None,
                event: Optional[str] = None, conf: Optional[str] = None) -> Dict[str, Any]:
        f = {"kind": kind, "evidence": evidence, "confidence": conf or confidence(evidence["n"]),
             "text": text}
        if at_s is not None:
            f["at_s"] = round(at_s, 1)
        if event:
            f["event"] = event
        return f

    out = []
    skip, ratio, ss = ev(SKIP), ev(RATIO), ev(SHARE_SAVE)
    if skip and v[SKIP] >= WORSE * skip["baseline_median"]:
        out.append(finding("hook", skip, (
            f"{v[SKIP]:g}% of views skipped in the first 3 s vs a median of "
            f"{skip['baseline_median']:g}% ({skip['n']} Reels): a hook problem.{hook_txt}"),
            at_s=0, event="; ".join(hook)))
    avg_ms = metrics.get(WATCH_TIME)
    if avg_ms is not None and (not duration_s or avg_ms / 1000 < duration_s):
        at = avg_ms / 1000
        playing = [e for e in timeline if e["t"] <= at < e["t"] + e.get("d", 0)]
        event = playing[-1]["e"] if playing else None
        out.append(finding("exit", {"avg_watch_s": round(at, 1),
                                    **(ratio or {"baseline_median": None, "n": 0})},
                           f"The average viewer leaves around {_clock(at)}"
                           + (f", during '{event}'" if event else "")
                           + ". Low confidence: an average, the real exits spread around it"
                           " and the API gives no curve.",
                           at_s=at, event=event, conf="low"))
    if ratio and ss and v[RATIO] >= ratio["baseline_median"] \
            and v[SHARE_SAVE] < BETTER * ss["baseline_median"]:
        end = timeline[-1] if timeline else None
        out.append(finding("payoff", {**ss, RATIO: ratio[RATIO],
                                      "watch_ratio_baseline_median": ratio["baseline_median"]}, (
            f"Watch ratio {v[RATIO]:.0%} (median {ratio['baseline_median']:.0%}) but shares+saves"
            f" per reach {v[SHARE_SAVE]:.2%} vs a median of {ss['baseline_median']:.2%}: viewers"
            " stay but don't act, a payoff problem"
            + (f". The ending: '{end['e']}'." if end else ".")),
            conf=confidence(min(ss["n"], ratio["n"])),
            at_s=end and end["t"], event=end and end["e"]))
    if skip and v[SKIP] <= BETTER * skip["baseline_median"]:
        out.append(finding("strong", skip, (
            f"Only {v[SKIP]:g}% of views skipped in the first 3 s vs a median of "
            f"{skip['baseline_median']:g}%: the hook holds.{hook_txt}"),
            at_s=0, event="; ".join(hook)))
    if ratio and v[RATIO] >= WORSE * ratio["baseline_median"]:
        out.append(finding("strong", ratio, (
            f"Watch ratio {v[RATIO]:.0%} vs a median of {ratio['baseline_median']:.0%}: "
            f"viewers stay.{hook_txt}"), at_s=0, event="; ".join(hook)))
    return out


def _clock(s: float) -> str:
    return f"{int(s) // 60}:{int(s) % 60:02d}"


def _diagnoser(store: CampaignStore, settings: InstagramMCPSettings):
    """(latest snapshots, cfg, findings(snap)) sharing one read of the snapshots and labels."""
    latest, cfg, labels = store.latest_snapshots(), scoring_config(settings), store.labels()
    matured = matured_by_group(latest, cfg)
    durations = {m: lb.get("duration_s") for m, lb in labels.items()}

    def findings(snap: Dict[str, Any]) -> List[Dict[str, Any]]:
        if group_of(snap) != "REELS" or not _is_matured(snap, cfg):
            return []
        base = baseline_for(snap, matured, cfg, near_age=store.snapshots_near_age)
        label = labels.get(snap["media_id"]) or {}
        asset = store.get_asset(label["asset_id"]) if label.get("asset_id") else None
        return diagnose(asset and asset["timeline"], label.get("duration_s"),
                        snap.get("metrics") or {}, baseline_medians(base, durations))

    return latest, cfg, findings


def retention_for(store: CampaignStore, settings: InstagramMCPSettings,
                  media_id: str) -> List[Dict[str, Any]]:
    """The findings of one post; [] unless it is a matured Reel."""
    latest, _, findings = _diagnoser(store, settings)
    snap = next((s for s in latest if s["media_id"] == media_id), None)
    return findings(snap) if snap else []


def retention_all(store: CampaignStore, settings: InstagramMCPSettings, *, since: datetime,
                  until: datetime) -> Dict[str, List[Dict[str, Any]]]:
    """{media_id: findings} of the Reels that matured (posted_at + the scoring min age) in
    [since, until)."""
    latest, cfg, findings = _diagnoser(store, settings)
    return {s["media_id"]: findings(s) for s in latest
            if group_of(s) == "REELS" and _is_matured(s, cfg) and s["posted_at"]
            and since <= parse_dt(s["posted_at"]) + timedelta(hours=_min_age("REELS", cfg))
            < until}
