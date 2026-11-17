import random
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from src.config import InstagramMCPSettings
from src.learning.slots import (
    parse_windows,
    plan_slots,
    plan_slots_from_settings,
    window_weights,
)

PARIS = ZoneInfo("Europe/Paris")
WINDOWS = parse_windows("11:00-13:00,17:00-21:00")
GAP = timedelta(minutes=120)
DAY = date(2026, 6, 10)


def plan(day=DAY, count=3, taken=(), seed=1, windows=WINDOWS, **kw):
    args = dict(windows=windows, tz="Europe/Paris", max_per_day=3, min_gap=GAP,
                jitter_minutes=7, rng=random.Random(seed))
    args.update(kw)
    return plan_slots(day, count, list(taken), **args)


def local(day, hh, mm=0):
    return datetime.combine(day, time(hh, mm), tzinfo=PARIS).astimezone(timezone.utc)


def check(slots, day, windows=WINDOWS, taken=(), gap=GAP):
    assert slots == sorted(slots)
    for s in slots:
        assert s.tzinfo is not None and s.utcoffset() == timedelta(0)
        assert s.second == 0 and s.microsecond == 0
        loc = s.astimezone(PARIS)
        assert loc.date() == day
        assert any(a <= loc.time() <= b for a, b in windows), loc
    everything = sorted(list(slots) + list(taken))
    for x, y in zip(everything, everything[1:]):
        assert y - x >= gap, (x, y)


def test_normal_day_spreads_over_both_windows():
    slots = plan()
    assert len(slots) == 3
    check(slots, DAY)
    hours = [s.astimezone(PARIS).hour for s in slots]
    assert any(h < 13 for h in hours) and any(h >= 17 for h in hours)
    assert plan() == slots  # deterministic with a seed
    assert plan(seed=2) != slots  # jitter does something


@pytest.mark.parametrize("day", [date(2026, 3, 29), date(2026, 10, 25)])
@pytest.mark.parametrize("seed", range(5))
def test_dst_change_days(day, seed):
    slots = plan(day=day, seed=seed)
    assert len(slots) == 3
    check(slots, day)


@pytest.mark.parametrize("day", [date(2026, 3, 29), date(2026, 10, 25)])
@pytest.mark.parametrize("seed", range(5))
def test_window_across_the_change_hour(day, seed):
    # 01:30-04:00 holds the missing hour (March) or the doubled hour (October).
    windows = parse_windows("01:30-04:00")
    gap = timedelta(minutes=30)
    slots = plan(day=day, count=5, windows=windows, max_per_day=5, min_gap=gap, seed=seed)
    assert slots
    check(slots, day, windows=windows, gap=gap)


@pytest.mark.parametrize("spec", ["02:15-02:45", "02:30-05:00", "00:30-02:30"])
def test_window_boundary_in_the_spring_gap(spec):
    windows = parse_windows(spec)
    day = date(2026, 3, 29)
    slots = plan(day=day, count=3, windows=windows, min_gap=timedelta(minutes=20))
    check(slots, day, windows=windows, gap=timedelta(minutes=20))
    if spec == "02:15-02:45":  # does not exist that day
        assert slots == []


def test_max_per_day_counts_taken_on_that_local_day():
    taken = [local(DAY, 12), local(DAY, 22, 30)]  # 22:30 is outside the windows
    yesterday = [local(DAY - timedelta(days=1), 18)]
    slots = plan(taken=taken + yesterday)
    assert len(slots) == 1
    check(slots, DAY, taken=taken)
    assert plan(taken=taken + [local(DAY, 9)]) == []


def test_gap_against_taken():
    taken = [local(DAY, 18, 30)]
    for seed in range(10):
        slots = plan(count=2, taken=taken, seed=seed)
        assert len(slots) == 2
        check(slots, DAY, taken=taken)


def test_returns_fewer_when_windows_are_full():
    taken = [local(DAY, 12), local(DAY, 19, 30)]
    slots = plan(count=3, taken=taken, max_per_day=10)
    check(slots, DAY, taken=taken)
    assert len(slots) == 1 and slots[0] <= local(DAY, 17, 30)  # only 17:00-17:30 is free


def test_past_skipped_with_now():
    now = local(DAY, 18, 0) + timedelta(seconds=30)
    slots = plan(now=now)
    check(slots, DAY)
    assert slots and all(s >= now for s in slots)
    assert len(slots) == 2  # 18:01 .. 21:00 holds two at a 120 min gap
    assert plan(now=local(DAY, 21, 1)) == []


def test_jitter_bounds():
    one = parse_windows("10:00-14:00")
    centre = local(DAY, 12)
    seen = set()
    for seed in range(50):
        [slot] = plan(count=1, windows=one, seed=seed)
        assert abs(slot - centre) <= timedelta(minutes=7)
        seen.add(slot)
    assert len(seen) > 5
    for seed in range(20):  # jitter never leaves a tight window
        [slot] = plan(count=1, windows=parse_windows("10:00-10:04"), seed=seed)
        assert local(DAY, 10) <= slot <= local(DAY, 10, 4)


def test_weights_pick_the_window():
    slots = plan(count=1, weights=[3, 1])
    assert slots[0].astimezone(PARIS).hour < 13
    with pytest.raises(ValueError):
        plan(weights=[1])


@pytest.mark.parametrize(
    "spec, message",
    [
        ("11-13", "HH:MM-HH:MM"),
        ("11:00-13:00,", "HH:MM-HH:MM"),
        ("25:00-26:00", "HH:MM-HH:MM"),
        ("22:00-01:00", "crosses midnight"),
        ("12:00-12:00", "empty"),
        ("11:00-13:00,12:30-14:00", "overlap"),
    ],
)
def test_window_validation(spec, message):
    with pytest.raises(ValueError, match=message):
        parse_windows(spec)
    with pytest.raises(ValidationError, match=message):
        InstagramMCPSettings(_env_file=None, posting_windows=spec)


def test_parse_sorts_and_allows_touching():
    assert parse_windows("17:00-21:00, 11:00-17:00") == [
        (time(11), time(17)),
        (time(17), time(21)),
    ]


def test_from_settings(settings):
    now = local(DAY, 8)
    slots = plan_slots_from_settings(settings, DAY, 5, [], rng=random.Random(3), now=now)
    assert len(slots) == settings.max_posts_per_day == 3
    check(slots, DAY)
    other = settings.model_copy(update={"posting_windows": "09:00-10:00", "max_posts_per_day": 5})
    assert len(plan_slots_from_settings(other, DAY, 5, [], now=now)) == 1


def test_window_weights_follow_the_audience():
    evening = {h: 50 for h in range(15, 19)}  # 17:00-21:00 Paris summer = 15-19 UTC
    lunch, eve = window_weights(WINDOWS, "Europe/Paris", DAY, {**evening, 9: 5, 10: 5})
    assert eve == 50 and lunch == 5
    # Quiet window floored at 10 % of the busiest, never 0.
    assert window_weights(WINDOWS, "Europe/Paris", DAY, evening) == [5.0, 50]
    assert window_weights(WINDOWS, "Europe/Paris", DAY, {}) == [1.0, 1.0]
    assert window_weights(WINDOWS, "Europe/Paris", DAY, None) == [1.0, 1.0]
    assert window_weights(WINDOWS, "Europe/Paris", DAY, {3: 9}) == [1.0, 1.0]


def test_window_weights_dst_day():
    profile = {h: 10 for h in range(24)}
    profile[11] = 100
    # 11:00-13:00 Paris: 10-12 UTC the day before spring forward, 09-11 UTC on the day.
    assert window_weights(WINDOWS, "Europe/Paris", date(2026, 3, 28), profile) == [55, 10]
    assert window_weights(WINDOWS, "Europe/Paris", date(2026, 3, 29), profile) == [10, 10]
    # Partial hours count by minutes: 11:30-12:30 UTC+2 → half of 9 UTC, half of 10 UTC.
    half = window_weights(parse_windows("11:30-12:30"), "Europe/Paris", DAY, {9: 40})
    assert half == [20]


def test_from_settings_with_hourly_profile(settings):
    settings = settings.model_copy(update={"min_slot_gap_minutes": 30})
    lunch_heavy = {9: 100, 10: 100, 16: 5}  # 11:00-13:00 Paris summer = 9-11 UTC

    def lunch_posts(profile):
        slots = plan_slots_from_settings(settings, DAY, 3, [], rng=random.Random(3),
                                         now=local(DAY, 8), hourly_profile=profile)
        check(slots, DAY, gap=timedelta(minutes=30))
        assert len(slots) == 3
        return sum(1 for s in slots if s.astimezone(PARIS).hour < 14)

    assert lunch_posts(None) == 1  # v1: equal weights, the longer evening window gets two
    assert lunch_posts(lunch_heavy) == 3
