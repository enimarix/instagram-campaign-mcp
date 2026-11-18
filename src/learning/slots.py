"""
Slot planner v1 (rules): propose publish times for one day. Pure, no I/O.

Rules (GOAL.md §3.2, §3.3):
- Posting windows are local times in the owner's time zone; results are aware UTC.
- Never more than `max_per_day` posts on that local day, counting `taken` slots.
- Every result is at least `min_gap` (real time) from every other result and every
  `taken` slot, inside a window, on a whole minute, and not before `now`.
- When the day is full, fewer than `count` slots come back (not an error).

How slots are placed (deliberately simple):
1. Each new post goes to the window with the highest `weight / (posts + 1)`, where
   `posts` already counts the `taken` slots inside it (weighted round-robin). Ties go
   to the longer (still open) window, then the earlier one.
2. A window's k new posts aim at evenly spread points (centres of k equal parts),
   each moved by up to `jitter_minutes` either way.
3. Each aim (earliest first) snaps to the nearest free minute: inside a window, at or
   after `now`, at least `min_gap` from everything placed or taken. If its own window
   is full it lands in the nearest window that still has room.

Weights (default: all equal) are one number per window. `window_weights` derives them
from audience data (followers online per UTC hour, 022); `plan_slots_from_settings`
multiplies them by our own results (087): a window's median engagement index over its
matured posts (at least `slot_min_posts`, else 1.0), clamped to [FACTOR_MIN, FACTOR_MAX];
the floor applies after. Exploration: on a share `slot_explore_share` of days (an rng
seeded by the date) the day's first slot goes to the least-tried window, so the planner
keeps testing hours; only while some window has fewer posts than another.

Daylight saving: a window boundary that does not exist (spring gap) or exists twice
(autumn overlap) is resolved to the reading that keeps every slot inside the local
window, so a window touching the change hour can be a little shorter that day.
"""

from __future__ import annotations

import random
import re
from datetime import date, datetime, time, timedelta, timezone
from statistics import median
from typing import List, Mapping, Optional, Sequence, Tuple, Union
from zoneinfo import ZoneInfo

Window = Tuple[time, time]
Result = Tuple[time, float]  # (owner-local time of day posted, engagement index)
WindowStats = Tuple[int, Optional[float]]  # (posts, median engagement index)

_WINDOW_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)-([01]\d|2[0-3]):([0-5]\d)$")
_MINUTE = timedelta(minutes=1)
_HOUR = timedelta(hours=1)
# window_weights: a quiet window still gets this share of the busiest one's weight.
WEIGHT_FLOOR = 0.1
# Our results move a window's weight at most this far (1.0 = the account's typical post).
FACTOR_MIN, FACTOR_MAX = 0.5, 2.0


def parse_windows(spec: str) -> List[Window]:
    """Parse "11:00-13:00,17:00-21:00" into sorted (start, end) local times.

    Raises ValueError on a bad format, an empty or midnight-crossing window, or overlap.
    """
    windows: List[Window] = []
    for part in (p.strip() for p in spec.split(",")):
        m = _WINDOW_RE.match(part)
        if not m:
            raise ValueError(f"Posting window {part!r} must look like HH:MM-HH:MM (24 h)")
        start = time(int(m.group(1)), int(m.group(2)))
        end = time(int(m.group(3)), int(m.group(4)))
        if start > end:
            raise ValueError(
                f"Posting window {part!r} crosses midnight; split it into "
                f"{part[:5]}-23:59 and 00:00-{part[6:]}"
            )
        if start == end:
            raise ValueError(f"Posting window {part!r} is empty")
        windows.append((start, end))
    windows.sort()
    for (_, prev_end), (start, _) in zip(windows, windows[1:]):
        if start < prev_end:
            raise ValueError(f"Posting windows overlap in {spec!r}")
    return windows


def _aware(dt: datetime) -> datetime:
    # Same convention as store.parse_dt: naive means UTC.
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _utc(day: date, t: time, tz: ZoneInfo, *, latest: bool) -> datetime:
    """Local day+time → UTC; for a missing/doubled time, the latest (start) or earliest (end)."""
    a, b = (datetime.combine(day, t, tzinfo=tz).replace(fold=f).astimezone(timezone.utc)
            for f in (0, 1))
    return max(a, b) if latest else min(a, b)


def _ceil_minute(dt: datetime) -> datetime:
    floor = dt.replace(second=0, microsecond=0)
    return floor if floor == dt else floor + _MINUTE


def _free(intervals, blocked: Sequence[datetime], gap: timedelta):
    """Intervals minus the open span (t - gap, t + gap) around each blocked time,
    trimmed to whole minutes."""
    for t in blocked:
        out = []
        for a, b in intervals:
            if t + gap <= a or t - gap >= b:
                out.append((a, b))
                continue
            if a <= t - gap:
                out.append((a, t - gap))
            if t + gap <= b:
                out.append((t + gap, b))
        intervals = out
    trimmed = [(_ceil_minute(a), b.replace(second=0, microsecond=0)) for a, b in intervals]
    return [(a, b) for a, b in trimmed if a <= b]


def plan_slots(
    day: date,
    count: int,
    taken: Sequence[datetime],
    *,
    windows: Sequence[Window],
    tz: Union[str, ZoneInfo],
    max_per_day: int,
    min_gap: timedelta,
    jitter_minutes: float,
    rng: random.Random,
    now: Optional[datetime] = None,
    weights: Optional[Sequence[float]] = None,
    explore: Optional[int] = None,
) -> List[datetime]:
    """Propose up to `count` publish times on local `day` (aware UTC, sorted).

    `explore`: index of a window that gets the first new post when it has none on `day`
    yet and is still open. See the module docstring for the rules. Deterministic for a
    seeded `rng`.
    """
    tz = ZoneInfo(tz) if isinstance(tz, str) else tz
    weights = [1.0] * len(windows) if weights is None else list(weights)
    if len(weights) != len(windows) or any(w <= 0 for w in weights):
        raise ValueError("weights needs one positive number per window")
    taken = [_aware(t) for t in taken]
    now = _aware(now) if now is not None else None

    on_day = sum(1 for t in taken if t.astimezone(tz).date() == day)
    n = max(0, min(count, max_per_day - on_day))

    # Window spans in UTC, cut at `now`; closed ones drop out.
    spans, forced = [], None
    for i, ((start, end), weight) in enumerate(zip(windows, weights)):
        a, b = _utc(day, start, tz, latest=True), _utc(day, end, tz, latest=False)
        tried = any(a <= t <= b for t in taken)
        if now is not None:
            a = max(a, now)
        if a <= b:
            spans.append([a, b, weight, sum(1 for t in taken if a <= t <= b), 0])
            if i == explore and not tried:
                forced = spans[-1]
    if not spans or n == 0:
        return []

    # 1. Weighted round-robin: span[4] counts new posts per window.
    if forced is not None:
        forced[4] = 1
    for _ in range(n - (forced is not None)):
        best = max(spans, key=lambda s: (s[2] / (s[3] + s[4] + 1), s[1] - s[0], -s[0].timestamp()))
        best[4] += 1

    # 2. Evenly spread aims with jitter.
    aims = []
    for a, b, _, _, k in spans:
        for i in range(k):
            jitter = timedelta(minutes=rng.uniform(-jitter_minutes, jitter_minutes))
            aims.append(a + (b - a) * (2 * i + 1) / (2 * k) + jitter)

    # 3. Snap each aim to the nearest free minute.
    placed: List[datetime] = []
    for aim in sorted(aims):
        aim = _ceil_minute(aim - _MINUTE / 2)  # nearest minute
        free = _free([(s[0], s[1]) for s in spans], taken + placed, min_gap)
        if not free:
            break
        placed.append(min((min(max(aim, a), b) for a, b in free), key=lambda t: abs(t - aim)))
    return sorted(placed)


def window_weights(
    windows: Sequence[Window],
    tz: Union[str, ZoneInfo],
    day: date,
    hourly_profile: Optional[Mapping[int, float]],
) -> List[float]:
    """One weight per window: the average followers online over the window's real time on
    local `day` (UTC hours, minute-weighted; a missing hour counts as 0).

    A window never weighs less than WEIGHT_FLOOR x the busiest one. No profile or no audience
    in any window → all 1.0 (v1 behaviour).
    """
    tz = ZoneInfo(tz) if isinstance(tz, str) else tz
    profile = hourly_profile or {}
    averages = []
    for start, end in windows:
        a, b = _utc(day, start, tz, latest=True), _utc(day, end, tz, latest=False)
        total = weighted = 0.0
        t = a
        while t < b:
            step = min(t.replace(minute=0, second=0, microsecond=0) + _HOUR, b)
            minutes = (step - t).total_seconds() / 60
            total += minutes
            weighted += minutes * profile.get(t.hour, 0)
            t = step
        # A window shrunk to nothing by DST takes the hour it starts in.
        averages.append(weighted / total if total else profile.get(a.hour, 0))
    top = max(averages, default=0)
    if top <= 0:
        return [1.0] * len(windows)
    return [max(avg, WEIGHT_FLOOR * top) for avg in averages]


def window_results(windows: Sequence[Window], results: Sequence[Result]) -> List[WindowStats]:
    """(posts, median engagement index or None) per window, from the posts whose
    owner-local time of day falls inside it."""
    out = []
    for start, end in windows:
        idx = [i for t, i in results if start <= t <= end]
        out.append((len(idx), median(idx) if idx else None))
    return out


def result_factors(stats: Sequence[WindowStats], min_posts: int) -> List[float]:
    """Per window: its median index clamped to [FACTOR_MIN, FACTOR_MAX], or 1.0 (neutral)
    with fewer than `min_posts` posts."""
    return [1.0 if n < min_posts or med is None else min(max(med, FACTOR_MIN), FACTOR_MAX)
            for n, med in stats]


def explore_window(day: date, stats: Sequence[WindowStats], share: float) -> Optional[int]:
    """The least-tried window (fewest posts, earliest on a tie) on a `share` of days, else
    None. Same day, same answer (rng seeded by the date). None while every window has as many
    posts as the others: nothing to catch up on (no results at all → v1)."""
    counts = [n for n, _ in stats]
    if not counts or min(counts) == max(counts):
        return None
    if random.Random(f"slot-explore:{day.isoformat()}").random() >= share:
        return None
    return counts.index(min(counts))


def _learned(settings, windows: Sequence[Window], day: date,
             hourly_profile: Optional[Mapping[int, float]],
             results: Optional[Sequence[Result]]):
    """(weights, explore index, stats) for one day: audience x results, floored."""
    weights = window_weights(windows, settings.timezone, day, hourly_profile)
    if not results:
        return weights, None, None
    stats = window_results(windows, results)
    weights = [w * f for w, f in zip(weights, result_factors(stats, settings.slot_min_posts))]
    top = max(weights)
    weights = [max(w, WEIGHT_FLOOR * top) for w in weights]
    return weights, explore_window(day, stats, settings.slot_explore_share), stats


def plan_slots_from_settings(
    settings,
    day: date,
    count: int,
    taken: Sequence[datetime],
    rng: Optional[random.Random] = None,
    now: Optional[datetime] = None,
    hourly_profile: Optional[Mapping[int, float]] = None,
    results: Optional[Sequence[Result]] = None,
) -> List[datetime]:
    """`plan_slots` with the posting settings; `now` defaults to the current time.

    `hourly_profile` (UTC hour → followers online, e.g. store.online_followers_profile())
    and `results` ((owner-local time posted, engagement index) per matured post) weight the
    windows and pick the exploration window (module docstring); None keeps them equal.
    """
    windows = parse_windows(settings.posting_windows)
    weights, explore, _ = _learned(settings, windows, day, hourly_profile, results)
    return plan_slots(
        day,
        count,
        taken,
        windows=windows,
        tz=settings.timezone,
        max_per_day=settings.max_posts_per_day,
        min_gap=timedelta(minutes=settings.min_slot_gap_minutes),
        jitter_minutes=settings.slot_jitter_minutes,
        rng=rng or random.Random(),
        now=now or datetime.now(timezone.utc),
        weights=weights,
        explore=explore,
    )


def explain_slot(settings, at: datetime,
                 results: Optional[Sequence[Result]]) -> Optional[str]:
    """One line on why the planner chose `at`, from our results; None without results or
    outside every window."""
    windows = parse_windows(settings.posting_windows)
    local = _aware(at).astimezone(ZoneInfo(settings.timezone))
    i = next((k for k, (a, b) in enumerate(windows) if a <= local.time() <= b), None)
    if i is None or not results:
        return None
    _, explore, stats = _learned(settings, windows, local.date(), None, results)
    a, b = windows[i]
    n, med = stats[i]
    label = f"{a:%H:%M}–{b:%H:%M}"
    if explore == i:
        return f"{label}: testing a window with fewer of your posts (n = {n})"
    if n < settings.slot_min_posts or med is None:
        return f"{label}: too few of your posts there to judge yet (n = {n})"
    return f"{label}: your posts there do {med:.1f}× typical (n = {n})"
