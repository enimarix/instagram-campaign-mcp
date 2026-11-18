"""
A/B test maths for paid ads (step 093): pure functions, no database, no network.

A test changes ONE variable (creative, audience or placement) across 2-4 variants with
equal budgets, and judges them on one primary metric. Every metric is a proportion, so
the significance check is a two-proportion z-test (normal approximation):

- `ctr`: clicks / impressions;
- `result_rate`: results / impressions (with equal budgets and similar CPMs the variant
  with the highest result rate has the lowest cost per result);
- `conversion_rate`: results / clicks.

Cost per result itself is a ratio of money to counts, not a proportion: `evaluate`
reports it per variant but never tests it.

Design (fixed horizon, no peeking):
- `min_sample` is the planned sample per variant, from `sample_size`. Before `min_days`
  and `min_sample` are both reached the verdict is `too_early`, even if one variant
  looks far ahead.
- After that: `winner` when the best variant beats every other one; otherwise `running`
  until `max_days`, then `no_difference`. (ponytail: looking again every day between
  min and max raises the false-positive rate a little; a sequential test would fix it.)
- More than 2 variants: the best variant is compared with each other one (k-1 tests)
  and the p-values get the Holm correction (step-down, never weaker than Bonferroni).
  `sample_size` plans with Bonferroni (alpha / (k-1)), the conservative side.
- The lift is relative to the runner-up: (p_best - p_next) / p_next, with a Wald
  interval for the difference at 1 - alpha, divided by p_next.

Defaults: `min_days` 4 (the brief's default; Meta's Marketing API split-test guide gives
no minimum), `max_days` 30 (Ads Manager's A/B test limit), alpha 0.05, power 0.8.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

VARIABLES = ("creative", "audience", "placement")
# metric -> (successes field, trials field) in a variant's results
METRICS: Dict[str, Tuple[str, str]] = {
    "ctr": ("clicks", "impressions"),
    "result_rate": ("results", "impressions"),
    "conversion_rate": ("results", "clicks"),
}
_Z = NormalDist()


@dataclass(frozen=True)
class TestSpec:
    variable: str
    variants: int = 2
    primary_metric: str = "ctr"
    min_days: int = 4
    max_days: int = 30
    min_sample: int = 0  # trials (impressions or clicks) per variant
    alpha: float = 0.05
    power: float = 0.8
    budgets: Optional[Sequence[float]] = None  # per variant, must be equal

    __test__ = False  # not a pytest class

    def __post_init__(self) -> None:
        if self.variable not in VARIABLES:
            raise ValueError(f"variable must be one of {VARIABLES} (one variable per test)")
        if not 2 <= self.variants <= 4:
            raise ValueError("a test has 2 to 4 variants")
        if self.primary_metric not in METRICS:
            raise ValueError(f"primary_metric must be one of {tuple(METRICS)}")
        if not 1 <= self.min_days <= self.max_days:
            raise ValueError("need 1 <= min_days <= max_days")
        if self.min_sample < 0:
            raise ValueError("min_sample must be >= 0")
        if not (0 < self.alpha < 1 and 0 < self.power < 1):
            raise ValueError("alpha and power must be between 0 and 1")
        if self.budgets is not None:
            b = list(self.budgets)
            if len(b) != self.variants:
                raise ValueError("one budget per variant")
            if b[0] <= 0 or any(not math.isclose(x, b[0], rel_tol=1e-9) for x in b):
                raise ValueError("budgets must be equal and positive")

    @property
    def comparisons(self) -> int:
        return self.variants - 1


def sample_size(
    baseline_rate: float,
    min_lift: float,
    alpha: float = 0.05,
    power: float = 0.8,
    *,
    comparisons: int = 1,
) -> int:
    """Trials per variant to detect a relative lift `min_lift` over `baseline_rate`.

    Two-sided two-proportion z-test, pooled variance under the null, no continuity
    correction (Fleiss, Levin & Paik 2003, eq. 4.14; same as R's `power.prop.test`).
    `comparisons` > 1 splits alpha (Bonferroni)."""
    p1 = baseline_rate
    p2 = p1 * (1 + min_lift)
    if not (0 < p1 < 1 and 0 < p2 < 1) or min_lift == 0:
        raise ValueError("need 0 < baseline_rate and baseline*(1+min_lift) < 1, lift != 0")
    za = _Z.inv_cdf(1 - alpha / comparisons / 2)
    zb = _Z.inv_cdf(power)
    pbar = (p1 + p2) / 2
    n = (za * math.sqrt(2 * pbar * (1 - pbar)) + zb * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2)))
    return math.ceil(n**2 / (p2 - p1) ** 2)


def _unit_cost(spec: TestSpec, cpm: Optional[float], cpc: Optional[float]) -> float:
    if METRICS[spec.primary_metric][1] == "impressions":
        if not cpm or cpm <= 0:
            raise ValueError(f"{spec.primary_metric} is per impression: give cpm")
        return cpm / 1000
    if not cpc or cpc <= 0:
        raise ValueError(f"{spec.primary_metric} is per click: give cpc")
    return cpc


def budget_needed(
    spec: TestSpec,
    baseline_rate: float,
    min_lift: float,
    *,
    cpm: Optional[float] = None,
    cpc: Optional[float] = None,
) -> Dict[str, Any]:
    """Money the test needs: per variant, in total and per day over `min_days`.

    The sample is the larger of `sample_size` and `spec.min_sample`; it costs `cpm` per
    1000 impressions (ctr, result_rate) or `cpc` per click (conversion_rate)."""
    needed = sample_size(
        baseline_rate, min_lift, spec.alpha, spec.power, comparisons=spec.comparisons
    )
    sample = max(needed, spec.min_sample)
    per_variant = round(sample * _unit_cost(spec, cpm, cpc), 2)
    return {
        "sample_per_variant": sample,
        "per_variant": per_variant,
        "total": round(per_variant * spec.variants, 2),
        "daily_per_variant": round(per_variant / spec.min_days, 2),
    }


def underpowered(
    spec: TestSpec,
    budget: float,
    baseline_rate: float,
    min_lift: float,
    *,
    cpm: Optional[float] = None,
    cpc: Optional[float] = None,
) -> Optional[str]:
    """Why the test cannot detect `min_lift` with this total `budget`, or None."""
    need = budget_needed(spec, baseline_rate, min_lift, cpm=cpm, cpc=cpc)
    if spec.min_sample < need["sample_per_variant"]:
        return (
            f"min_sample {spec.min_sample} is below the {need['sample_per_variant']} per "
            f"variant needed to detect a {min_lift:.0%} lift"
        )
    if budget < need["total"]:
        return f"budget {budget:.2f} is below the {need['total']:.2f} the test needs"
    return None


def z_test(s1: int, n1: int, s2: int, n2: int) -> float:
    """Two-sided p-value of the pooled two-proportion z-test."""
    pooled = (s1 + s2) / (n1 + n2)
    se = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
    if se == 0:
        return 1.0
    z = (s1 / n1 - s2 / n2) / se
    return 2 * (1 - _Z.cdf(abs(z)))


def holm(p_values: Sequence[float]) -> list:
    """Holm-adjusted p-values, in the input order."""
    m = len(p_values)
    order = sorted(range(m), key=lambda i: p_values[i])
    adjusted = [0.0] * m
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * p_values[i]))
        adjusted[i] = running
    return adjusted


def evaluate(spec: TestSpec, results: Mapping[str, Mapping[str, float]]) -> Dict[str, Any]:
    """Verdict on per-variant results {name: {impressions, clicks, results, spend, days}}.

    status: too_early | running | winner | no_difference (see the module docstring)."""
    if len(results) != spec.variants:
        raise ValueError(f"expected {spec.variants} variants, got {len(results)}")
    s_key, n_key = METRICS[spec.primary_metric]
    rows = {}
    for name, r in results.items():
        s, n = int(r.get(s_key) or 0), int(r.get(n_key) or 0)
        if s < 0 or n < s:
            raise ValueError(f"variant {name}: need 0 <= {s_key} <= {n_key}")
        spend, res = float(r.get("spend") or 0), int(r.get("results") or 0)
        rows[name] = {
            "successes": s,
            "trials": n,
            "rate": s / n if n else None,
            "spend": spend,
            "cost_per_result": round(spend / res, 4) if res else None,
        }
    days = max(float(r.get("days") or 0) for r in results.values())
    out: Dict[str, Any] = {
        "status": "too_early",
        "metric": spec.primary_metric,
        "days": days,
        "variants": rows,
        "winner": None,
        "p_values": {},
        "lift": None,
    }
    if days < spec.min_days or any(v["trials"] < max(spec.min_sample, 1) for v in rows.values()):
        return out

    ranked = sorted(rows, key=lambda k: rows[k]["rate"], reverse=True)
    best, others = ranked[0], ranked[1:]
    b = rows[best]
    raw = [z_test(b["successes"], b["trials"], rows[o]["successes"], rows[o]["trials"])
           for o in others]
    adjusted = holm(raw)
    out["p_values"] = {o: round(p, 6) for o, p in zip(others, adjusted)}
    if all(p < spec.alpha for p in adjusted):
        nxt = rows[others[0]]
        p1, p2 = b["rate"], nxt["rate"]
        if p2 > 0:  # a zero runner-up has no relative lift
            half = _Z.inv_cdf(1 - spec.alpha / 2) * math.sqrt(
                p1 * (1 - p1) / b["trials"] + p2 * (1 - p2) / nxt["trials"]
            )
            out["lift"] = {
                "vs": others[0],
                "value": round((p1 - p2) / p2, 4),
                "ci_low": round((p1 - p2 - half) / p2, 4),
                "ci_high": round((p1 - p2 + half) / p2, 4),
                "confidence": 1 - spec.alpha,
            }
        out.update(status="winner", winner=best)
    else:
        out["status"] = "no_difference" if days >= spec.max_days else "running"
    return out


def should_stop(
    spec: TestSpec, results: Mapping[str, Mapping[str, float]], spent: float, cap: float
) -> Optional[str]:
    """Why the test must stop now: 'winner', 'cap_reached', 'end_date', or None."""
    verdict = evaluate(spec, results)
    if verdict["status"] == "winner":
        return "winner"
    if spent >= cap:
        return "cap_reached"
    if verdict["days"] >= spec.max_days:
        return "end_date"
    return None
