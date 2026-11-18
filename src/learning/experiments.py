"""
Experiments (step 086, GOAL.md §3.5): one variable, 2-4 variants, a target sample per
variant and an end date. The late-night report's "ideas to try" (083) become `proposed`
rows; the owner or the agent opens them, at most MAX_OPEN_EXPERIMENTS at once.

- variable: a tag dimension of the evidence engine (src/learning/evidence.py predicate:
  track, pillar, hook_type, strategy, template, hour, duration); variants are values of it.
- An idea belongs to a variant through ideas.experiment = 'exp:<id>:<variant>'
  (parse_label); older free-text values are no experiment and stay as they are.
- explore_plan: the explore ideas of a batch fill the open variants furthest from target.
- evaluate: per variant, n = matured Reels and their median engagement index; an
  experiment is done when every variant reached the target or ends_on (owner-local) passed.
  Trial Reels (088) and normal Reels are never compared: variants are compared within one
  group (`group`), the one whose smallest variant is largest (then the most posts, REELS
  on a tie).
- finish: stores the result and a learning (origin audience): do / dont when the best and
  worst variants differ by more than EVIDENCE_MIN_EFFECT with at least medium n on both,
  else a hypothesis "no clear difference"; the worker does this once a day (run_daily).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from statistics import median
from typing import Any, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from ..campaign import scoring_config
from ..config import InstagramMCPSettings
from ..scoring import REEL_GROUPS, _is_matured
from ..store import CampaignStore, parse_dt
from ..studio.seed import local_today
from .analytics import scored_posts
from .breakdowns import TAGS
from .evidence import _level, predicate

STATUSES = ("proposed", "open", "finished", "abandoned")
MAX_VARIANTS = 4
MAX_TARGET, MAX_DAYS = 100, 90
QUIET_BATCH_DAYS = 3  # the report warns when an open experiment got no approved video in these
IDEA_TAGS = ("pillar", "hook_type", "strategy")  # set on the idea itself (track: positional)
# Ideas still on their way to a post: no asset yet, or one not failed, archived or disliked.
_PLANNED = (
    "SELECT i.experiment, COUNT(*) AS n FROM ideas i WHERE i.experiment LIKE 'exp:%'"
    " AND (NOT EXISTS (SELECT 1 FROM assets a WHERE a.idea_id = i.id)"
    " OR EXISTS (SELECT 1 FROM assets a WHERE a.idea_id = i.id"
    " AND a.status NOT IN ('failed', 'archived') AND a.verdict != 'disliked'))"
    " GROUP BY i.experiment")


def label(experiment_id: int, variant: str) -> str:
    return f"exp:{experiment_id}:{variant}"


def parse_label(value: Any) -> Optional[Tuple[int, str]]:
    """(experiment id, variant) of an ideas.experiment value; None for anything else."""
    parts = value.split(":", 2) if isinstance(value, str) else []
    if len(parts) != 3 or parts[0] != "exp" or not parts[1].isdigit():
        return None
    return int(parts[1]), parts[2]


def _variants(variable: Any, variants: Any) -> List[str]:
    """The variants as normalised tag values; ValueError when the variable is not a tag
    dimension or a variant is not one of its values."""
    if variable not in TAGS:
        raise ValueError(f"variable must be a tag dimension ({', '.join(TAGS)}),"
                         f" not {variable!r}")
    if not isinstance(variants, (list, tuple)) or not 2 <= len(variants) <= MAX_VARIANTS:
        raise ValueError(f"an experiment needs 2-{MAX_VARIANTS} variants")
    out = [predicate({"tag": variable, "value": v})[1] for v in variants]
    if len(set(out)) != len(out):
        raise ValueError("variants must differ")
    return out


def open_experiment(store: CampaignStore, settings: InstagramMCPSettings,
                    hypothesis: Optional[str] = None, variable: Optional[str] = None,
                    variants: Optional[Sequence[str]] = None, target_per_variant: int = 5,
                    days: int = 14, *, proposed_id: Optional[int] = None,
                    now: datetime) -> Dict[str, Any]:
    """Open a new experiment, or the proposed one `proposed_id` (its fields unless given).
    ValueError: invalid fields, not proposed, or MAX_OPEN_EXPERIMENTS already open."""
    row = store.get_experiment(proposed_id) if proposed_id is not None else None
    if row is not None:
        if row["status"] != "proposed":
            raise ValueError(f"experiment {proposed_id} is {row['status']}, not proposed")
        hypothesis, variable = hypothesis or row["hypothesis"], variable or row["variable"]
        variants = variants or row["variants"]
    hypothesis = (hypothesis or "").strip()
    if not hypothesis:
        raise ValueError("a hypothesis is required")
    variants = _variants(variable, variants)
    if not 1 <= target_per_variant <= MAX_TARGET or not 1 <= days <= MAX_DAYS:
        raise ValueError(f"target_per_variant must be 1-{MAX_TARGET}, days 1-{MAX_DAYS}")
    cap = settings.max_open_experiments
    if len(store.list_experiments("open")) >= cap:
        raise ValueError(f"{cap} experiments are open already (MAX_OPEN_EXPERIMENTS):"
                         " wait until one finishes")
    fields = {"hypothesis": hypothesis, "variable": variable, "variants": variants}
    row = (store.update_experiment(row["id"], **fields) if row
           else store.add_experiment(**fields))
    ends_on = local_today(settings.timezone, now) + timedelta(days=days)
    if not store.open_experiment(row["id"], cap, target_per_variant=target_per_variant,
                                 ends_on=ends_on):  # another process opened one meanwhile
        raise ValueError(f"MAX_OPEN_EXPERIMENTS reached: experiment {row['id']} stays proposed")
    return store.get_experiment(row["id"])


def list_experiments(store: CampaignStore, status: Optional[str] = None,
                     limit: int = 50) -> List[Dict[str, Any]]:
    if status is not None and status not in STATUSES:
        raise ValueError(f"status must be one of {', '.join(STATUSES)}")
    return store.list_experiments(status, limit=max(1, min(limit, 100)))


def propose_from_report(store: CampaignStore, report_date: str) -> Dict[str, Any]:
    """The report's proposals (083 analysis.experiments) as `proposed` rows, replacing the
    ones an earlier save of that day made. Proposals that are no valid experiment (e.g. a
    variable that is no tag dimension) are skipped with the error."""
    report = store.get_daily_report(report_date)
    if not report:
        raise KeyError(f"No daily report for {report_date}")
    store.delete_proposed_experiments(report["report_date"])
    proposed, skipped = [], []
    for p in report["analysis"].get("experiments", []):
        try:
            variants = _variants(p["variable"], p["variants"])
        except ValueError as e:
            skipped.append({**p, "error": str(e)})
            continue
        proposed.append(store.add_experiment(p["hypothesis"], p["variable"], variants,
                                             report_date=report["report_date"]))
    return {"proposed": proposed, "skipped": skipped}


def check_idea(store: CampaignStore, track: str, fields: Dict[str, Any]) -> None:
    """create_idea's experiment rules: 'exp:<id>:<variant>' of an open experiment and one of
    its variants. The idea's own tag must match the variant (filled in when missing), and
    the strategy defaults to explore. ValueError otherwise."""
    if "experiment" not in fields:
        return
    parsed = parse_label(fields["experiment"])
    if parsed is None:
        raise ValueError("experiment must be 'exp:<id>:<variant>' of an open experiment"
                         " (the brief's explore_plan)")
    try:
        exp = store.get_experiment(parsed[0])
    except KeyError:
        raise ValueError(f"no experiment {parsed[0]}") from None
    variable, variant = exp["variable"], parsed[1]
    if exp["status"] != "open":
        raise ValueError(f"experiment {exp['id']} is {exp['status']}, not open")
    if variant not in exp["variants"]:
        raise ValueError(f"variant must be one of {', '.join(exp['variants'])}")
    if variable in IDEA_TAGS:
        fields.setdefault(variable, variant)
    if (track if variable == "track" else fields.get(variable, variant)) != variant:
        raise ValueError(f"an idea of {fields['experiment']} needs {variable}={variant}")
    fields.setdefault("strategy", "explore")


def explore_plan(store: CampaignStore, explore_count: int) -> List[Dict[str, Any]]:
    """[{experiment_id, variant, experiment}] for up to `explore_count` explore ideas: each
    goes to the open variant with the most ideas still missing to its target (ideas on
    their way count), ties in experiment then variant order, so variants fill round-robin.
    Shorter when every variant has enough: the other explore ideas are free picks."""
    with store._tx() as c:
        planned = {r["experiment"]: r["n"] for r in c.execute(_PLANNED)}
    gaps = {(e["id"], v): e["target_per_variant"] - planned.get(label(e["id"], v), 0)
            for e in sorted(store.list_experiments("open"), key=lambda e: e["id"])
            for v in e["variants"]}
    plan = []
    for _ in range(max(0, explore_count)):
        key = max(gaps, key=gaps.__getitem__, default=None)  # the first of equal gaps
        if key is None or gaps[key] <= 0:
            break
        gaps[key] -= 1
        plan.append({"experiment_id": key[0], "variant": key[1], "experiment": label(*key)})
    return plan


def evaluate(store: CampaignStore, settings: InstagramMCPSettings, experiment: Dict[str, Any],
             *, now: datetime) -> Dict[str, Any]:
    """{per_variant: {variant: {n, index}}, group, done, why} (see the module docstring)."""
    with store._tx() as c:
        variant_of = {r[0]: parse_label(r[1])[1] for r in c.execute(
            "SELECT a.id, i.experiment FROM assets a JOIN ideas i ON i.id = a.idea_id"
            " WHERE i.experiment LIKE ?", (label(experiment["id"], "%"),))}
    cfg = scoring_config(settings)
    by_group = {g: {v: [] for v in experiment["variants"]} for g in REEL_GROUPS}
    for snap, s in scored_posts(store, settings):
        v = variant_of.get((s["label"] or {}).get("asset_id"))
        if s["group"] in by_group and v in by_group[s["group"]] and _is_matured(snap, cfg):
            by_group[s["group"]][v].append(s["engagement_index"])
    group = max(REEL_GROUPS, key=lambda g: (min(map(len, by_group[g].values())),
                                            sum(map(len, by_group[g].values()))))
    per = {}
    for v, xs in by_group[group].items():  # xs: the engagement indexes, None when unknown
        eng = [x for x in xs if x is not None]
        per[v] = {"n": len(xs), "index": round(median(eng), 2) if eng else None}
    reached = all(p["n"] >= experiment["target_per_variant"] for p in per.values())
    ended = (experiment["ends_on"] is not None
             and local_today(settings.timezone, now) > date.fromisoformat(experiment["ends_on"]))
    why = "target reached" if reached else f"ended {experiment['ends_on']}" if ended else None
    return {"per_variant": per, "group": group, "done": why is not None, "why": why}


def finish(store: CampaignStore, settings: InstagramMCPSettings, experiment: Dict[str, Any],
           evaluation: Dict[str, Any]) -> Dict[str, Any]:
    """Store the result and its learning (see the module docstring); returns the row."""
    per, var = evaluation["per_variant"], experiment["variable"]
    ranked = sorted((v for v in per if per[v]["index"] is not None), key=lambda v: -per[v]["index"])
    kind, value, confidence = "hypothesis", (ranked or experiment["variants"])[0], "low"
    if len(ranked) >= 2:
        best, worst = per[ranked[0]], per[ranked[-1]]
        level = _level(min(best["n"], worst["n"]), settings)
        if best["index"] - worst["index"] > settings.evidence_min_effect and level != "low":
            confidence = level
            kind, value = (("do", ranked[0]) if best["index"] - 1 >= 1 - worst["index"]
                           else ("dont", ranked[-1]))
    numbers = ", ".join(f"{v}: index {p['index']}, n {p['n']}" for v, p in per.items())
    claim = {"do": f"{var} = {value} works best", "dont": f"avoid {var} = {value}",
             "hypothesis": f"no clear difference between the {var} variants"}[kind]
    learning = store.add_learning(
        f"{claim} (experiment {experiment['id']}: {numbers})", kind, "audience",
        scope={"tag": var, "value": value}, confidence=confidence,
        evidence=[{"kind": "experiment", "id": experiment["id"], "per_variant": per}])
    return store.update_experiment(experiment["id"], status="finished",
                                   result={**evaluation, "kind": kind, "value": value},
                                   learning_id=learning["id"])


def run_daily(store: CampaignStore, settings: InstagramMCPSettings,
              now: datetime) -> Dict[str, Any]:
    """The worker's daily job: evaluate every open experiment, finish the done ones."""
    open_ = store.list_experiments("open")
    finished = []
    for e in open_:
        ev = evaluate(store, settings, e, now=now)
        if ev["done"]:
            finished.append(finish(store, settings, e, ev)["id"])
    return {"evaluated": len(open_), "finished": finished}


def report_section(store: CampaignStore, settings: InstagramMCPSettings, day: date, *,
                   now: datetime) -> Dict[str, Any]:
    """The daily facts' experiments: open ones with their progress, and `warnings` for an
    open experiment, open through the last QUIET_BATCH_DAYS batch days up to `day`, whose
    ideas of those days got no approved video."""
    with store._tx() as c:
        days = [r[0] for r in c.execute(
            "SELECT DISTINCT batch_date FROM ideas WHERE batch_date <= ?"
            " ORDER BY batch_date DESC LIMIT ?", (day.isoformat(), QUIET_BATCH_DAYS))]
    rows, warnings = [], []
    for e in sorted(store.list_experiments("open"), key=lambda e: e["id"]):
        rows.append({k: e[k] for k in ("id", "hypothesis", "variable", "variants",
                                       "target_per_variant", "ends_on")}
                    | {"progress": evaluate(store, settings, e, now=now)["per_variant"]})
        opened = parse_dt(e["opened_at"]).astimezone(ZoneInfo(settings.timezone)).date().isoformat()
        if len(days) < QUIET_BATCH_DAYS or opened > days[-1]:
            continue
        with store._tx() as c:
            approved = c.execute(
                "SELECT COUNT(*) FROM assets a JOIN ideas i ON i.id = a.idea_id"
                " WHERE i.experiment LIKE ? AND a.approved_at IS NOT NULL"
                f" AND i.batch_date IN ({','.join('?' * len(days))})",
                (label(e["id"], "%"), *days)).fetchone()[0]
        if not approved:
            warnings.append({"experiment_id": e["id"],
                             "warning": f"no approved video in the last {QUIET_BATCH_DAYS}"
                                        f" batch days ({days[-1]} to {days[0]})"})
    return {"open": rows, "warnings": warnings}
