"""Step 082: daily facts (src/learning/facts.py), the worker job, CLI and MCP tool."""

from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
import respx

import src.instagram_mcp_server as srv
from src import scheduler, worker
from src.config import InstagramMCPSettings
from src.instagram_client import InstagramClient
from src.learning.facts import build_and_store, daily_facts, facts_for
from src.learning.funnel import funnel, taste
from src.store import to_iso

from .conftest import API
from .test_worker_data_jobs import FakeClient

TZ = "America/New_York"
NOW = datetime(2026, 11, 17, 3, tzinfo=timezone.utc)  # 22:00 on 2026-11-16 in New York
YESTERDAY = "2026-11-15"  # owner-local; in UTC it would be 2026-11-16
H = timedelta(hours=1)
NOON_Y = datetime(2026, 11, 15, 17, tzinfo=timezone.utc)  # noon of YESTERDAY in New York


def _settings(**kw):
    kw.setdefault("database_path", ":memory:")
    return InstagramMCPSettings(_env_file=None, timezone=TZ,
                                instagram_access_token=kw.pop("token", None),
                                instagram_business_account_id="1789", **kw)


@pytest.fixture
def settings():
    return _settings()


def _utc(day, hour):
    return datetime(2026, 11, day, hour, tzinfo=timezone.utc)


def _post(store, mid, posted, *, saved=10, reach=1000, shares=5, follows=1, age=50.0,
          views=(None, None), tags=None):
    """Snapshots at 24 h (views[0], if any) and at `age` h (views[1]); tags=(track, hook)."""
    m = {"reach": reach, "saved": saved, "shares": shares, "follows": follows,
         "likes": reach // 20}
    if views[0] is not None:
        store.add_snapshot(mid, {**m, "views": views[0]}, "REELS", "VIDEO", to_iso(posted),
                           permalink=f"https://ig/{mid}", captured_at=posted + 24 * H)
    store.add_snapshot(mid, {**m, "views": views[1]} if views[1] else m, "REELS", "VIDEO",
                       to_iso(posted), permalink=f"https://ig/{mid}",
                       captured_at=posted + age * H)
    if tags:
        idea = store.add_idea(tags[0], hook_type=tags[1])
        asset = store.add_asset(idea["id"], recipe={"kind": "motion", "template": "FactQuest"})
        store.label_post(mid, asset_id=asset["id"])


def _asset(store, day, *, status="ready", verdict="none", experiment=None):
    idea = store.add_idea("motion", batch_date=day, experiment=experiment)
    a = store.add_asset(idea["id"], batch_date=day, qc={"passed": True},
                        recipe={"kind": "motion", "template": "FactQuest"})
    with store._tx() as c:
        c.execute("UPDATE assets SET status=?, verdict=? WHERE id=?", (status, verdict, a["id"]))


@pytest.fixture
def seeded(store):
    for i in range(6):  # baseline, matured long ago
        _post(store, f"b{i}", _utc(1, 12))
    # Matured yesterday (posted_at + 48 h on 2026-11-15 in New York).
    _post(store, "win", _utc(13, 8), saved=60, reach=1200, shares=30, follows=12,
          views=(1000, 5000), tags=("motion", "question"))                    # 03:00 NY
    _post(store, "lose", _utc(13, 14), saved=1, shares=0, follows=0,
          views=(500, 600), tags=("remix", "pov"))                             # 09:00 NY
    _post(store, "edge", _utc(14, 3), age=48)  # 22:00 NY on the 13th: matures 22:00 the 15th
    # Matured earlier in the last 7 days, also at 09:00 NY.
    _post(store, "mid", _utc(10, 14), saved=8, views=(100, 3000))
    _post(store, "mid2", _utc(11, 14), saved=8)
    # Published yesterday (young), and today in New York (yesterday in UTC).
    _post(store, "y1", _utc(15, 23), age=3, tags=("motion", "question"))
    _post(store, "today", _utc(16, 6), age=2)
    # Funnel: batch days in each window; experiments (old batches, not in the funnel).
    _asset(store, YESTERDAY, verdict="liked")
    _asset(store, "2026-11-12", verdict="disliked")
    for _ in range(5):
        _asset(store, "2026-10-01", status="published", experiment="hooks")
    for _ in range(2):
        _asset(store, "2026-10-01", status="published", experiment="length")
    _asset(store, "2026-10-01", experiment="length")  # not published: not counted
    return store


def _ids(posts):
    return [p["media_id"] for p in posts]


async def test_published_matured_winners_losers_in_owner_local_days(seeded, settings):
    f = await daily_facts(seeded, settings, now=NOW)
    y, w = f["yesterday"], f["last_7_days"]
    assert f["report_date"] == YESTERDAY
    assert (y["since"], y["until"], w["since"]) == (YESTERDAY, YESTERDAY, "2026-11-09")
    assert _ids(y["published"]["posts"]) == ["y1"] and y["published"]["count"] == 1
    assert y["published"]["posts"][0]["tags"]["hook_type"] == "question"
    assert set(_ids(w["published"]["posts"])) == {"y1", "edge", "win", "lose", "mid2", "mid"}
    assert set(_ids(y["matured"]["posts"])) == {"win", "lose", "edge"}
    assert set(_ids(w["matured"]["posts"])) == {"win", "lose", "edge", "mid", "mid2"}
    for window in (y, w):
        (winner,), (loser,) = window["winners"], window["losers"]
        assert winner["media_id"] == "win" and winner["tags"]["track"] == "motion"
        assert winner["drivers"] and winner["verdict"] == "winner"
        assert loser["media_id"] == "lose" and loser["tags"]["hook_type"] == "pov"


async def test_slots_flag_small_samples_and_movers(seeded, settings):
    f = await daily_facts(seeded, settings, now=NOW)
    y, w = f["yesterday"]["slots"], f["last_7_days"]["slots"]
    assert (y["best"]["hour"], y["worst"]["hour"]) == (3, 9)
    assert y["best"]["n"] == 1 and y["best"]["small_sample"] and y["worst"]["small_sample"]
    assert (w["best"]["hour"], w["worst"]["hour"]) == (3, 9)
    assert w["worst"]["n"] == 3 and not w["worst"]["small_sample"]

    assert [(m["media_id"], m["gained"]) for m in f["yesterday"]["movers"]] == [
        ("win", 4000), ("lose", 100)]
    assert [m["media_id"] for m in f["last_7_days"]["movers"]] == ["win", "mid", "lose"]


async def test_funnel_equals_077_and_experiments(seeded, settings):
    f = await daily_facts(seeded, settings, now=NOW)
    for name, days in (("yesterday", 1), ("last_7_days", 7)):
        got = dict(f[name]["funnel"])
        assert got.pop("calibration") == taste(seeded, settings, days=days, now=NOON_Y)[
            "calibration"]
        assert got == funnel(seeded, settings, days=days, now=NOON_Y)["totals"]
    assert f["yesterday"]["funnel"]["produced"] == 1
    assert f["last_7_days"]["funnel"]["produced"] == 2
    assert f["experiments"] == {"min_sample": 5,
                                "reached": [{"experiment": "hooks", "published": 5}],
                                "under": [{"experiment": "length", "published": 2}]}
    settings.experiment_min_sample = 2
    assert len((await daily_facts(seeded, settings, now=NOW))["experiments"]["reached"]) == 2


def _with_client(per_hour=100):
    settings = _settings(token="t", rate_limit_requests_per_hour=per_hour)
    return settings, InstagramClient(settings, http_client=httpx.AsyncClient())


async def test_comments_top_three_untrusted(seeded):
    settings, client = _with_client()
    comments = [{"id": str(i), "text": f"c{i}", "like_count": i} for i in range(4)]
    comments.append({"id": "h", "text": "hidden", "like_count": 99, "hidden": True})
    try:
        with respx.mock:
            respx.get(f"{API}/y1/comments").mock(
                return_value=httpx.Response(200, json={"data": comments}))
            respx.get(url__regex=r".*/comments").mock(
                return_value=httpx.Response(200, json={"data": []}))
            f = await daily_facts(seeded, settings, client=client, now=NOW)
    finally:
        await client.close()
    section = f["audience_comments"]
    assert section["untrusted"] is True and section["note"] is None
    y1 = next(p for p in section["posts"] if p["media_id"] == "y1")
    assert y1["comments"] == [{"quote": "c3", "likes": 3}, {"quote": "c2", "likes": 2},
                              {"quote": "c1", "likes": 1}]
    assert len(section["posts"]) == 6


async def test_comments_fall_back_without_client_over_budget_or_on_error(seeded, settings):
    unconfigured = (await daily_facts(seeded, settings, now=NOW))["audience_comments"]
    assert unconfigured["posts"] == [] and "not configured" in unconfigured["note"]

    s, client = _with_client(per_hour=10)
    try:
        with respx.mock:
            route = respx.get(url__regex=r".*/comments").mock(
                return_value=httpx.Response(400, json={"error": {"message": "nope"}}))
            failed = (await daily_facts(seeded, s, client=client, now=NOW))["audience_comments"]
            assert failed["posts"] == [] and "nope" in failed["note"]
            for _ in range(8):  # 80 % of the hour used elsewhere
                await client.budget.acquire()
            calls = route.call_count
            over = (await daily_facts(seeded, s, client=client, now=NOW))["audience_comments"]
            assert route.call_count == calls  # no Graph call at all
    finally:
        await client.close()
    assert over["posts"] == [] and "budget" in over["note"]


async def test_store_keeps_summary_and_facts_for(seeded, settings):
    seeded.save_daily_report(date(2026, 11, 15), "agent summary", {})
    facts = await build_and_store(seeded, settings, None, NOW)
    report = seeded.get_daily_report(YESTERDAY)
    assert report["summary"] == "agent summary" and report["facts"] == facts
    assert await facts_for(seeded, settings, now=NOW) == facts  # stored, not recomputed
    older = await facts_for(seeded, settings, day=date(2026, 11, 12), now=NOW)
    assert older["report_date"] == "2026-11-12" and seeded.get_daily_report("2026-11-12")
    with pytest.raises(ValueError):
        await facts_for(seeded, settings, day=date(2026, 11, 16), now=NOW)


async def test_worker_builds_facts_once_a_day(store):
    cfg = InstagramMCPSettings(_env_file=None, database_path=":memory:", timezone="UTC")
    t = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)
    runs = [await worker.data_jobs(FakeClient(), store, cfg, now=lambda t=t: t)
            for t in (t, t + H, t + 24 * H)]
    assert runs[0]["facts_day"] == {"report_date": "2026-11-16"}
    assert "facts_day" not in runs[1]
    assert runs[2]["facts_day"] == {"report_date": "2026-11-17"}
    assert store.get_daily_report("2026-11-16")["facts"]["yesterday"]["published"]["count"] == 0


def test_cli_prints_facts(tmp_path, monkeypatch, capsys):
    cfg = _settings(database_path=str(tmp_path / "f.db"))
    monkeypatch.setattr(scheduler, "get_settings", lambda: cfg)
    monkeypatch.setattr(scheduler, "configure_logging", lambda *a: None)
    with pytest.raises(SystemExit) as e:
        scheduler.main(["facts", "--date", "2026-11-01"])
    assert e.value.code == 0
    assert '"report_date": "2026-11-01"' in capsys.readouterr().out
    with pytest.raises(SystemExit) as e:
        scheduler.main(["facts", "--date", "2999-01-01"])
    assert e.value.code == 1 and "past days" in capsys.readouterr().err


async def test_mcp_tool(seeded, settings, monkeypatch):
    monkeypatch.setattr(srv, "store", lambda: seeded)
    monkeypatch.setattr(srv, "get_settings", lambda: settings)
    f = await srv.get_daily_facts()
    assert f["audience_comments"]["untrusted"] is True
    assert (await srv.get_daily_facts(f["report_date"])) == f
    with pytest.raises(srv.ToolError):
        await srv.get_daily_facts("2999-01-01")
    with pytest.raises(srv.ToolError):
        await srv.get_daily_facts("yesterday")
