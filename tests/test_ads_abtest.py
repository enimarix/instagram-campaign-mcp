"""Step 093: A/B test maths (pure, no network)."""

from __future__ import annotations

import pytest

from src.ads.abtest import (
    TestSpec,
    budget_needed,
    evaluate,
    holm,
    sample_size,
    should_stop,
    underpowered,
    z_test,
)


def _v(clicks, impressions=10_000, days=7, spend=50.0, results=0):
    return {"impressions": impressions, "clicks": clicks, "results": results,
            "spend": spend, "days": days}


def test_sample_size_matches_textbook_values():
    # R's power.prop.test(p1=.50, p2=.75, power=.90) help example: n = 76.7 per group
    assert sample_size(0.5, 0.5, power=0.9) == 77
    # Fleiss, Levin & Paik (2003) eq. 4.14 (no continuity correction): 10% vs 15% = 685.6
    assert sample_size(0.10, 0.5) == 686
    # Bonferroni for 3 variants (2 comparisons) needs more
    assert sample_size(0.02, 0.2, comparisons=2) > sample_size(0.02, 0.2)
    with pytest.raises(ValueError):
        sample_size(0.0, 0.2)


def test_budget_arithmetic():
    spec = TestSpec("creative", variants=2, min_days=4)
    b = budget_needed(spec, 0.02, 0.2, cpm=5.0)
    assert b["sample_per_variant"] == sample_size(0.02, 0.2) == 21109
    assert b["per_variant"] == 105.55  # 21109 impressions at 5 per 1000
    assert b["total"] == 211.10
    assert b["daily_per_variant"] == 26.39
    # min_sample above the need wins; per-click metric takes cpc
    big = TestSpec("audience", primary_metric="conversion_rate", min_sample=50_000)
    assert budget_needed(big, 0.05, 0.3, cpc=0.4)["per_variant"] == 20_000.0
    with pytest.raises(ValueError, match="cpc"):
        budget_needed(big, 0.05, 0.3, cpm=5.0)


def test_underpowered_flagged():
    n = sample_size(0.02, 0.2)
    spec = TestSpec("creative", min_sample=n)
    assert underpowered(spec, 100.0, 0.02, 0.2, cpm=5.0).startswith("budget 100.00")
    assert underpowered(spec, 250.0, 0.02, 0.2, cpm=5.0) is None
    small = TestSpec("creative", min_sample=1000)
    assert "min_sample 1000" in underpowered(small, 10_000.0, 0.02, 0.2, cpm=5.0)


def test_too_early_before_min_days_or_sample():
    spec = TestSpec("creative", min_days=4, min_sample=5000)
    clear = {"a": _v(400, days=3), "b": _v(200, days=3)}
    assert evaluate(spec, clear)["status"] == "too_early"  # no peeking at day 3
    thin = {"a": _v(400, days=5), "b": _v(10, impressions=1000, days=5)}
    verdict = evaluate(spec, thin)
    assert verdict["status"] == "too_early" and verdict["winner"] is None


def test_clear_winner_with_lift_and_interval():
    spec = TestSpec("creative", min_sample=5000)
    v = evaluate(spec, {"a": _v(250, results=10), "b": _v(300, results=20)})
    assert v["status"] == "winner" and v["winner"] == "b"
    assert v["p_values"]["a"] == pytest.approx(0.0306, abs=1e-4)
    lift = v["lift"]
    assert lift["vs"] == "a" and lift["value"] == 0.2
    assert lift["ci_low"] > 0 and lift["ci_high"] > lift["value"]
    assert v["variants"]["b"]["cost_per_result"] == 2.5


def test_z_test_known_value():
    # 20% vs 25% of 1000 each: z = 2.677, p = 0.0074
    assert z_test(250, 1000, 200, 1000) == pytest.approx(0.00742, abs=1e-5)


def test_no_difference_after_max_days_running_before():
    spec = TestSpec("creative", min_sample=5000, max_days=14)
    close = {"a": _v(300, days=7), "b": _v(295, days=7)}
    assert evaluate(spec, close)["status"] == "running"
    close = {k: {**r, "days": 14} for k, r in close.items()}
    v = evaluate(spec, close)
    assert v["status"] == "no_difference" and v["winner"] is None


def test_holm_correction_with_three_variants():
    assert holm([0.04, 0.01, 0.03]) == pytest.approx([0.06, 0.03, 0.06])
    # each raw p < 0.05, but after Holm neither comparison holds: no winner
    spec = TestSpec("placement", variants=3, min_sample=5000)
    three = {"a": _v(300), "b": _v(250), "c": _v(252)}
    v = evaluate(spec, three)
    assert z_test(300, 10_000, 252, 10_000) < 0.05
    assert v["status"] == "running" and v["p_values"]["b"] == pytest.approx(0.0612, abs=1e-4)
    # the same a-vs-b gap with only two variants is a winner
    two = TestSpec("placement", variants=2, min_sample=5000)
    assert evaluate(two, {"a": _v(300), "b": _v(250)})["winner"] == "a"


def test_stop_rules():
    spec = TestSpec("creative", min_sample=5000, max_days=14)
    win = {"a": _v(250), "b": _v(300)}
    tie = {"a": _v(300), "b": _v(300)}
    assert should_stop(spec, win, spent=10, cap=100) == "winner"
    assert should_stop(spec, tie, spent=100, cap=100) == "cap_reached"
    assert should_stop(spec, {k: {**r, "days": 14} for k, r in tie.items()}, 10, 100) == (
        "end_date"
    )
    assert should_stop(spec, tie, spent=10, cap=100) is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"variable": "creative+audience"},
        {"variable": "creative", "variants": 1},
        {"variable": "creative", "variants": 5},
        {"variable": "creative", "primary_metric": "likes"},
        {"variable": "creative", "min_days": 10, "max_days": 5},
        {"variable": "creative", "budgets": [10, 12]},
        {"variable": "creative", "budgets": [10]},
        {"variable": "creative", "alpha": 0},
    ],
)
def test_spec_validation(kwargs):
    with pytest.raises(ValueError):
        TestSpec(**kwargs)


def test_spec_valid_and_results_checked():
    spec = TestSpec("audience", variants=3, budgets=[20.0, 20.0, 20.0])
    assert spec.comparisons == 2
    with pytest.raises(ValueError, match="expected 3"):
        evaluate(spec, {"a": _v(1), "b": _v(1)})
    with pytest.raises(ValueError, match="clicks <= impressions"):
        evaluate(spec, {"a": _v(20, impressions=10), "b": _v(1), "c": _v(1)})
