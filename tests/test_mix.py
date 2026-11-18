"""Batch-mix allocator (step 086a): fixed seeds, synthetic histories."""

import random
from datetime import datetime, timezone

import pytest

from src.learning import brief as B
from src.learning.mix import allocate, batch_mix, largest_remainder
from src.learning.quotas import todays_quotas
from src.studio.assets import set_verdict, transition

DAY = "2026-11-17"
NOW = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)
ABC = ["a", "b", "c"]


def _alloc(options=ABC, likes=None, dislikes=None, index=None, rules=(), seed=1, **kw):
    return allocate(options, likes or {}, dislikes or {}, index or {}, rules,
                    rng=random.Random(seed), **kw)


def test_a_clearly_better_option_gains_share():
    s = _alloc(likes={"a": 20, "b": 5, "c": 5}, dislikes={"a": 2, "b": 10, "c": 10})
    assert s["a"] > 0.6 and s["a"] == max(s.values())
    assert sum(s.values()) == pytest.approx(1)


def test_a_disliked_option_shrinks_to_the_floor_not_below():
    s = _alloc(likes={"a": 15, "b": 15}, dislikes={"a": 15, "b": 15, "c": 30})
    assert s["c"] == pytest.approx(0.10) and s["c"] >= 0.10 - 1e-12
    assert sum(s.values()) == pytest.approx(1)


def test_an_owner_rule_is_zero_and_outside_the_floor():
    s = _alloc(likes={"b": 50}, rules={"b"})
    assert s["b"] == 0 and s["a"] == pytest.approx(0.5, abs=0.03)
    assert sum(s.values()) == pytest.approx(1)
    assert _alloc(rules=set(ABC)) == dict.fromkeys(ABC, 0.0)


def test_floors_that_would_sum_past_one_give_equal_shares():
    options = [f"o{k}" for k in range(12)]  # 12 x 0.10 > 1
    s = _alloc(options, likes={"o0": 40})
    assert all(v == pytest.approx(1 / 12) for v in s.values())


def test_no_data_gives_near_equal_shares():
    s = _alloc(list("abcde"))
    assert max(s.values()) - min(s.values()) < 0.03


def test_same_seed_same_result():
    kw = {"likes": {"a": 3, "b": 2}, "dislikes": {"c": 1}}
    assert _alloc(seed="2026-11-17:template", **kw) == _alloc(seed="2026-11-17:template", **kw)
    assert _alloc(seed=1, **kw) != _alloc(seed=2, **kw)


@pytest.mark.parametrize("posts, blended", [(4, False), (5, True)])
def test_the_index_blend_kicks_in_only_past_min_posts(posts, blended):
    kw = {"likes": {"a": 5, "b": 5}, "dislikes": {"a": 5, "b": 5}, "min_posts": 5}
    plain = _alloc(["a", "b"], **kw)
    s = _alloc(["a", "b"], index={"a": (posts, 2.0), "b": (posts, 0.5)}, **kw)
    assert (s != plain) is blended
    if blended:  # half the score re-split 2.0 : 0.5
        assert s["a"] > 0.6 > 0.4 > s["b"] >= 0.1


def test_counts_round_to_the_batch_size():
    assert largest_remainder({"a": 0.5, "b": 0.3, "c": 0.2, "d": 0.0}, 7) == {
        "a": 4, "b": 2, "c": 1, "d": 0}
    assert sum(largest_remainder({"a": 0.333, "b": 0.333, "c": 0.334}, 25).values()) == 25
    assert largest_remainder({"a": 0.0}, 5) == {"a": 0}
    assert largest_remainder({"a": 1.0}, 0) == {"a": 0}


# The service

@pytest.fixture(autouse=True)
def utc(settings, tmp_path, monkeypatch):
    settings.timezone = "UTC"
    monkeypatch.setattr(B, "BIBLE_PATH", tmp_path / "BIBLE.md")


def _judged(store, verdict, template="FactQuest", pillar="stories", n=1):
    for _ in range(n):
        i = store.add_idea("motion", pillar=pillar, hook_type="question", batch_date=DAY)
        a = store.add_asset(i["id"], batch_date=DAY,
                            recipe={"kind": "motion", "template": template, "props": {}})
        transition(store, a["id"], "ready", actor="worker")
        set_verdict(store, a["id"], verdict)


def _rows(mix, dim):
    return {r["option"]: r for r in mix[dim]}


def test_batch_mix_learns_from_verdicts_and_obeys_owner_rules(store, settings):
    _judged(store, "liked", "PixelSkit", "everyday_humor", n=12)
    _judged(store, "disliked", "BossBattle", "myths", n=12)
    store.add_learning("never quizzes", "dont", "taste", confidence="owner",
                       scope={"tag": "template", "value": "QuizChest"})
    store.add_learning("agent dislikes stories", "dont", "taste", confidence="low",
                       scope={"tag": "template", "value": "DialogStory"})
    mix = batch_mix(store, settings, DAY, now=NOW)
    t = _rows(mix, "template")
    assert t["PixelSkit"]["share"] == max(r["share"] for r in mix["template"])
    assert t["PixelSkit"]["likes"] == 12 and t["BossBattle"]["dislikes"] == 12
    assert t["BossBattle"]["share"] == pytest.approx(0.10, abs=0.002)
    assert t["QuizChest"]["share"] == 0 and t["QuizChest"]["why"] == "owner rule: never"
    assert t["DialogStory"]["share"] > 0  # only owner rules are hard zeros
    h = _rows(mix, "humour")
    assert h["humour"]["share"] > 0.8 and h["humour"]["likes"] == 12
    # pillars split inside their group: the two dimensions agree
    p = _rows(mix, "pillar")
    assert p["everyday_humor"]["share"] == pytest.approx(h["humour"]["share"], abs=0.002)
    assert sum(r["share"] for r in mix["pillar"]) == pytest.approx(1, abs=0.005)
    assert mix == batch_mix(store, settings, DAY, now=NOW)  # same night, same mix
    # the quotas' humour target follows the stored mix, not HUMOUR_SHARE 0.5
    q = todays_quotas(store, settings, DAY, NOW)
    assert q["humour_target"] == round(q["effective_batch_size"] * h["humour"]["share"])
    assert q["humour_target"] > round(q["effective_batch_size"] * 0.5)


def test_moved_compares_with_yesterday(store, settings):
    assert batch_mix(store, settings, "2026-11-16", now=NOW)["moved"] == []
    _judged(store, "liked", "PixelSkit", n=10)
    moved = {(m["dimension"], m["option"]): m for m in batch_mix(store, settings, DAY,
                                                                   now=NOW)["moved"]}
    up = moved[("template", "PixelSkit")]
    assert up["to"] > up["from"] + 0.05 and up["why"].startswith("10 liked")
    assert all(abs(m["to"] - m["from"]) >= 0.05 for m in moved.values())


def test_brief_mix_counts_exploit_ideas(store, settings):
    _judged(store, "liked", "PixelSkit", "everyday_humor", n=8)
    b = B.creative_brief(store, settings, NOW)
    for dim in ("template", "hook_type", "pillar", "humour"):
        assert sum(r["count"] for r in b["mix"][dim]) == 7  # 10 ideas - 3 explore
    # the liked template leads (however many templates share the rest)
    counts = {r["option"]: r["count"] for r in b["mix"]["template"]}
    assert counts["PixelSkit"] >= 2 and all(n < counts["PixelSkit"] for k, n in counts.items() if k != "PixelSkit")


def test_the_owners_humour_share_is_where_the_split_starts():
    from src.learning.mix import _owner_humour

    learned = {"humour": 0.8, "informative": 0.2}
    assert _owner_humour(learned, 0.5) == learned  # 50/50: the likes alone
    assert _owner_humour({"humour": 0.5, "informative": 0.5}, 0.7)["humour"] == pytest.approx(0.7)
    assert _owner_humour({"humour": 0.0, "informative": 1.0}, 0.9)["humour"] == 0  # owner rule
    assert _owner_humour({"humour": 1.0, "informative": 0.0}, 0.0) == {"humour": 1.0,
                                                                     "informative": 0.0}
