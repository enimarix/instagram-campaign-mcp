"""Steps 051-052: watchlist, reference sources, the hashtag budget, research_trends and
the trend report."""

import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

import src.instagram_mcp_server as srv
from src.api.app import create_app
from src.learning.quotas import available_clips
from src.store import utcnow
from src.studio.research import (
    HASHTAG_LIMIT,
    HASHTAG_WINDOW,
    LOOKUPS_AT_ONCE,
    research_trends,
    trend_report,
)

from .conftest import API, LOCAL
from .test_api_assets import _settings

NOW = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)


def _post(pid, likes=10, **kw):
    return {"id": pid, "like_count": likes, "comments_count": 2, "media_type": "VIDEO",
            "permalink": f"https://www.instagram.com/reel/{pid}/",
            "timestamp": "2026-11-16T10:00:00+0000", **kw}


def _mock_graph(tags=None, accounts=None):
    """tags: {tag: [posts]}, accounts: {username: [posts] | httpx.Response}."""
    tags, accounts = tags or {}, accounts or {}

    def search(request):
        return httpx.Response(200, json={"data": [{"id": f"h_{request.url.params['q']}"}]})

    def top(request):
        tag = request.url.path.split("/")[-2].removeprefix("h_")
        return httpx.Response(200, json={"data": tags[tag]})

    def discovery(request):
        user = request.url.params["fields"].split("username(")[1].split(")")[0]
        media = accounts[user]
        if isinstance(media, httpx.Response):
            return media
        return httpx.Response(200, json={"business_discovery": {
            "username": user, "media": {"data": media}}})

    respx.get(f"{API}/ig_hashtag_search").mock(side_effect=search)
    respx.get(url__regex=rf"{API}/h_\w+/top_media").mock(side_effect=top)
    return respx.get(f"{API}/1789").mock(side_effect=discovery)


# --- store -----------------------------------------------------------------------------
def test_watchlist_normalises_and_is_unique(store):
    a = store.add_watch("hashtag", " #Fitness ")
    assert (a["kind"], a["value"], a["note"]) == ("hashtag", "fitness", None)
    again = store.add_watch("hashtag", "fitness", note="gym reels")
    assert again["id"] == a["id"] and again["note"] == "gym reels"
    assert store.add_watch("hashtag", "FITNESS")["note"] == "gym reels"  # no note: kept
    acc = store.add_watch("account", "@Some.User_1")
    assert acc["value"] == "some.user_1"
    assert store.add_watch("hashtag", "rival")["id"] != store.add_watch("account", "rival")["id"]
    assert [w["value"] for w in store.list_watchlist("hashtag")] == ["fitness", "rival"]
    for kind, value in (("account", "a b"), ("account", "x){id}"), ("hashtag", "#"),
                        ("hashtag", "a-b"), ("user", "x")):
        with pytest.raises(ValueError):
            store.add_watch(kind, value)
    assert store.remove_watch(acc["id"])["value"] == "some.user_1"
    assert len(store.list_watchlist()) == 3
    with pytest.raises(KeyError):
        store.remove_watch(acc["id"])


def test_reference_upsert_by_external_id(store):
    s, created = store.upsert_reference_source(
        "instagram", "M1", url="https://ig/1", author=None,
        stats={"likes": 5, "hashtag": "fitness"})
    assert created and s["role"] == "reference" and s["rights_basis"] == "unknown"
    s2, created = store.upsert_reference_source(
        "instagram", "M1", url="https://ig/1", author="rival", stats={"likes": 9, "views": 80})
    assert not created and s2["id"] == s["id"]
    assert s2["stats"] == {"likes": 9, "views": 80, "hashtag": "fitness"}  # merged
    s3, _ = store.upsert_reference_source("instagram", "M1", url=None, author=None,
                                          stats={"likes": 11})
    assert (s3["author"], s3["url"], s3["stats"]["views"]) == ("rival", "https://ig/1", 80)
    assert len(store.list_sources()) == 1


def test_sources_default_to_clip_and_only_clips_are_available(store):
    clip = store.add_source("local_inbox", local_path="c.mp4", rights_basis="own")
    assert clip["role"] == "clip" and clip["external_id"] is None
    store.add_source("instagram", local_path="r.mp4", rights_basis="commentary",
                     author="x", role="reference")
    assert available_clips(store) == 1


def test_hashtag_budget(store):
    take = store.take_hashtag_search
    assert all(take(f"t{i}", NOW, HASHTAG_LIMIT, HASHTAG_WINDOW) for i in range(30))
    assert not take("new", NOW, HASHTAG_LIMIT, HASHTAG_WINDOW)
    assert take("t3", NOW + timedelta(days=1), HASHTAG_LIMIT, HASHTAG_WINDOW)  # repeat: free
    later = NOW + HASHTAG_WINDOW + timedelta(seconds=1)  # all but t3 left the window
    assert take("new", later, HASHTAG_LIMIT, HASHTAG_WINDOW)


# --- research_trends ----------------------------------------------------------------------
@respx.mock
async def test_research_stores_references_and_second_run_updates(client, store):
    store.add_watch("hashtag", "fitness")
    store.add_watch("account", "rival")
    long_caption = "x" * 600
    tags = {"fitness": [_post("H1", caption="#fitness day"), _post("H2")]}
    accounts = {"rival": [_post("R1", view_count=1000, media_product_type="REELS",
                                caption=long_caption)]}
    _mock_graph(tags, accounts)

    out = await research_trends(client, store, now=NOW)
    assert out == {"hashtags_searched": ["fitness"], "hashtags_skipped_budget": [],
                   "accounts": ["rival"], "stored": 3, "updated": 0, "errors": {},
                   "stopped": None}
    by_id = {s["external_id"]: s for s in store.list_sources()}
    h1, r1 = by_id["H1"], by_id["R1"]
    assert h1["author"] is None and h1["role"] == "reference"
    assert h1["rights_basis"] == "unknown" and h1["url"].endswith("/H1/")
    assert h1["stats"]["hashtag"] == "fitness" and "views" not in h1["stats"]
    assert r1["author"] == "rival"
    assert (r1["stats"]["views"], r1["stats"]["product_type"]) == (1000, "REELS")
    assert len(r1["stats"]["caption"]) == 500 and "hashtag" not in r1["stats"]

    tags["fitness"] = [_post("H1", likes=99)]
    out = await research_trends(client, store, now=NOW + timedelta(days=1))
    assert (out["stored"], out["updated"]) == (0, 2)
    assert len(store.list_sources()) == 3
    assert store.get_source(h1["id"])["stats"]["likes"] == 99


@respx.mock
async def test_hashtag_budget_comes_from_the_database(client, store):
    for i in range(HASHTAG_LIMIT - 1):
        store.take_hashtag_search(f"other{i}", NOW - timedelta(days=1), 30, HASHTAG_WINDOW)
    store.take_hashtag_search("old", NOW - timedelta(days=6), 30, HASHTAG_WINDOW)
    for tag in ("new", "old"):
        store.add_watch("hashtag", tag)
    _mock_graph({"old": [_post("O1")], "new": [_post("N1")]})
    out = await research_trends(client, store, now=NOW)
    assert out["hashtags_searched"] == ["old"]  # a repeat within the week is free
    assert out["hashtags_skipped_budget"] == ["new"]
    assert [s["external_id"] for s in store.list_sources()] == ["O1"]


@respx.mock
async def test_account_errors_and_rate_limit_stop(client, store):
    for name in ("alpha", "beta", "gamma"):
        store.add_watch("account", name)
    route = _mock_graph(accounts={
        "alpha": httpx.Response(400, json={"error": {"message": "Invalid user", "code": 110}}),
        "beta": [_post("B1")],
        "gamma": httpx.Response(429, text="Too Many Requests")})
    out = await research_trends(client, store, now=NOW)
    assert out["errors"] == {"account:alpha": "Invalid user"}
    assert out["accounts"] == ["beta"] and out["stored"] == 1
    assert out["stopped"] == "rate_limited" and route.call_count == 3


@respx.mock
async def test_lookups_run_side_by_side(client, store):
    """« Actualiser » waited ~4 s per hashtag, one after another (~40 s of spinner)."""
    tags = [f"t{i}" for i in range(6)]
    for tag in tags:
        store.add_watch("hashtag", tag)
    _mock_graph({tag: [_post(tag.upper())] for tag in tags})
    flying = peak = 0

    async def slow_top(request):
        nonlocal flying, peak
        flying += 1
        peak = max(peak, flying)
        await asyncio.sleep(0.05)
        flying -= 1
        return httpx.Response(200, json={"data": [_post(request.url.path.split("_")[1][:2])]})

    respx.get(url__regex=rf"{API}/h_\w+/top_media").mock(side_effect=slow_top)
    out = await research_trends(client, store, now=NOW)
    assert out["hashtags_searched"] == tags and out["stored"] == 6
    assert peak == LOOKUPS_AT_ONCE


@respx.mock
async def test_stops_at_the_data_share_of_the_request_budget(client, store):
    store.add_watch("hashtag", "fitness")
    route = _mock_graph({"fitness": []})
    for _ in range(int(client.budget.per_hour * 0.8)):
        await client.budget.acquire()
    out = await research_trends(client, store, now=NOW)
    assert out["stopped"] == "request_budget" and out["hashtags_searched"] == []
    assert route.call_count == 0 and not respx.calls
    assert store.take_hashtag_search("x", NOW, 1, HASHTAG_WINDOW)  # budget untouched


# --- doors ------------------------------------------------------------------------------
@respx.mock
async def test_mcp_doors(client, store, monkeypatch):
    monkeypatch.setattr(srv, "store", lambda: store)
    monkeypatch.setattr(srv, "client", lambda: client)
    w = await srv.add_to_watchlist("account", "@Rival", note="same niche")
    assert (await srv.list_watchlist())["watchlist"] == [w]
    with pytest.raises(srv.ToolError, match="not a valid hashtag"):
        await srv.add_to_watchlist("hashtag", "two words")
    _mock_graph(accounts={"rival": [_post("R1", view_count=5)]})
    assert (await srv.research_trends())["stored"] == 1
    assert (await srv.remove_from_watchlist(w["id"]))["value"] == "rival"
    with pytest.raises(srv.ToolError):
        await srv.remove_from_watchlist(w["id"])


def test_api_watchlist(store):
    with TestClient(create_app(_settings(), store=store), base_url=LOCAL) as tc:
        r = tc.post("/api/watchlist", json={"kind": "hashtag", "value": "#Gym"})
        assert r.status_code == 200 and r.json()["value"] == "gym"
        assert [w["value"] for w in tc.get("/api/watchlist").json()] == ["gym"]
        assert tc.post("/api/watchlist", json={"kind": "account", "value": "a b"}
                       ).status_code == 422
        assert tc.post("/api/watchlist", json={"kind": "page", "value": "x"}).status_code == 422
        assert tc.delete(f"/api/watchlist/{r.json()['id']}").status_code == 204
        assert tc.delete(f"/api/watchlist/{r.json()['id']}").status_code == 404
        assert tc.get("/api/watchlist").json() == []


# --- trend report (052) ------------------------------------------------------------------
def _ref(store, pid, *, author=None, hashtag=None, ago=timedelta(days=1), base=NOW, **stats):
    ts = (base - ago).strftime("%Y-%m-%dT%H:%M:%S+0000")  # Meta's offset format
    extra = {"hashtag": hashtag} if hashtag else {}
    return store.upsert_reference_source("instagram", pid, url=f"https://ig/{pid}",
                                         author=author, stats={"timestamp": ts, **extra,
                                                               **stats})[0]


def test_trend_report_account_outliers(store, settings):
    for i, views in enumerate((100, 200, 300, 400)):
        _ref(store, f"A{i}", author="rival", views=views, likes=1)
    _ref(store, "HIT", author="rival", views=1500, likes=5,
         caption="\n  Stop doing this squat mistake  \nmore #Fitness #gym #fitness")
    old = _ref(store, "OLD", author="rival", views=50, ago=timedelta(days=20))
    out = trend_report(store, settings, now=NOW)
    hit = out["accounts"][0]
    assert (hit["account"], hit["ranked_within"], hit["metric"]) == ("rival", "account", "views")
    # OLD is out of the 14-day window but still counts towards the median (of 6 posts)
    assert hit["median"] == 250 and hit["outlier"] == 6.0 and hit["outlier_note"] is None
    assert hit["hook_quote"] == "Stop doing this squat mistake"
    assert hit["hashtags"] == ["fitness", "gym"] and hit["caption_quote"].startswith("\n")
    assert hit["duration_s"] is None and hit["url"] == "https://ig/HIT"
    assert [i["outlier"] for i in out["accounts"]] == [6.0, 1.6, 1.2, 0.8, 0.4]
    assert old["id"] not in [i["source_id"] for i in out["accounts"]]
    assert out["hashtags"] == {} and out["generated_at"] == "2026-11-17T12:00:00+00:00"
    assert len(trend_report(store, settings, days=30, limit=2, now=NOW)["accounts"]) == 2


def test_trend_report_likes_fallback_too_few_and_hour(store, settings):
    for i, likes in enumerate((10, 20, 30, 40, 50)):  # no views at all (e.g. photos)
        _ref(store, f"L{i}", author="likes_only", likes=likes, duration=21.5)
    for i in range(4):
        _ref(store, f"F{i}", author="few", views=10 * (i + 1))
    # 11:00 UTC in November is 12:00 in Paris
    _ref(store, "T", author="few", views=99, ago=timedelta(hours=1), caption="x" * 200)
    _ref(store, "N", author="few", ago=timedelta(hours=2))  # hidden counts
    by = {i["source_id"]: i for i in trend_report(store, settings, now=NOW)["accounts"]}
    lk = [i for i in by.values() if i["account"] == "likes_only"]
    assert {i["metric"] for i in lk} == {"likes"} and max(i["outlier"] for i in lk) == 1.67
    assert lk[0]["duration_s"] == 21.5
    t = next(i for i in by.values() if i["views"] == 99)
    assert (t["metric"], t["median"], t["outlier"]) == ("views", 30, 3.3)  # N has no views
    assert t["hour"] == 12 and len(t["hook_quote"]) == 120
    n = next(i for i in by.values() if i["views"] is None and i["account"] == "few")
    assert n["outlier"] is None and n["outlier_note"] == "no views or likes on this post"


def test_trend_report_too_few_posts(store, settings):
    for i in range(4):
        _ref(store, f"F{i}", author="few", views=10)
    item = trend_report(store, settings, now=NOW)["accounts"][0]
    assert item["outlier"] is None and item["metric"] == "views"
    assert item["outlier_note"] == "only 4 account posts with views (need 5)"


def test_trend_report_hashtags_ranked_within_their_tag(store, settings):
    for i, likes in enumerate((10, 20, 30, 40, 100)):
        _ref(store, f"H{i}", hashtag="fitness", likes=likes, views=999)  # views ignored
    _ref(store, "G1", hashtag="gym", likes=7)
    _ref(store, "R1", author="rival", hashtag="fitness", views=5)  # author wins
    _ref(store, "X1", likes=3)  # neither author nor hashtag: not reported
    out = trend_report(store, settings, now=NOW)
    fit = out["hashtags"]["fitness"]
    assert [i["outlier"] for i in fit] == [3.33, 1.33, 1.0, 0.67, 0.33]
    assert all(i["metric"] == "likes" and i["ranked_within"] == "hashtag" for i in fit)
    assert "account" not in fit[0] and fit[0]["hashtag"] == "fitness"
    assert out["hashtags"]["gym"][0]["outlier_note"] == "only 1 hashtag posts with likes (need 5)"
    assert [i["account"] for i in out["accounts"]] == ["rival"]
    only = trend_report(store, settings, kind="hashtag", now=NOW)
    assert only["accounts"] == [] and set(only["hashtags"]) == {"fitness", "gym"}
    with pytest.raises(ValueError):
        trend_report(store, settings, days=0, now=NOW)


async def test_mcp_trend_report(store, monkeypatch):
    monkeypatch.setattr(srv, "store", lambda: store)
    _ref(store, "R1", author="rival", views=5, ago=timedelta(hours=1), base=utcnow())
    out = await srv.get_trend_report(days=1)
    assert [i["account"] for i in out["accounts"]] == ["rival"]
    with pytest.raises(srv.ToolError, match="at least 1"):
        await srv.get_trend_report(limit=0)


def test_api_trends(store):
    _ref(store, "H1", hashtag="gym", likes=3, ago=timedelta(hours=1), base=utcnow())
    with TestClient(create_app(_settings(), store=store), base_url=LOCAL) as tc:
        out = tc.get("/api/trends?days=7").json()
        assert out["accounts"] == [] and out["hashtags"]["gym"][0]["url"] == "https://ig/H1"
        assert tc.get("/api/trends?kind=account").json()["hashtags"] == {}
        assert tc.get("/api/trends?days=0").status_code == 422
