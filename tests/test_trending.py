"""Step 134: the Trending page backend (refresh, feed, reactions, suggested topics) and the
owner's work orders through the agent's tools, brief and work packet."""

import json
import re
from datetime import datetime, timedelta, timezone

import pytest
import respx
from fastapi.testclient import TestClient

import src.instagram_mcp_server as srv
from src.agent import packet
from src.agent.runner import AGENT_DIR
from src.api.app import create_app
from src.learning import brief as B
from src.studio import production, research, work_orders
from src.studio.assets import transition

from .conftest import LOCAL
from .test_api_assets import _settings
from .test_research import _mock_graph, _post

NOW = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)
QC_OK = {"passed": True, "checks": [], "reasons": []}


def _ref(store, pid, *, likes=10, views=None, author=None, hashtag=None, path="reel",
         ts="2026-11-16T10:00:00+0000", **stats):
    stats = {"likes": likes, "views": views, "timestamp": ts, "caption": f"Hook {pid}\nmore",
             "media_type": "VIDEO", **stats}
    if hashtag:
        stats["hashtag"] = hashtag
    s, _ = store.upsert_reference_source(
        "instagram", pid, url=f"https://www.instagram.com/{path}/{pid}/", author=author,
        stats={k: v for k, v in stats.items() if v is not None})
    return s["id"]


# --- refresh ---------------------------------------------------------------------------
@respx.mock
def test_refresh_runs_research_and_returns_the_budget(store, settings):
    store.add_watch("hashtag", "mealprep")
    store.add_watch("account", "rival")
    _mock_graph(tags={"mealprep": [_post("T1", media_url="https://cdn/t1.mp4")]},
                accounts={"rival": [_post("A1", view_count=500,
                                          thumbnail_url="https://cdn/a1.jpg")]})
    with TestClient(create_app(settings, store=store), base_url=LOCAL) as tc:
        r = tc.post("/api/research/refresh")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["hashtags_searched"] == ["mealprep"] and out["accounts"] == ["rival"]
    assert out["stored"] == 2 and out["stopped"] is None
    assert out["hashtag_budget"] == {"limit": 30, "used": 1, "left": 29}
    feed = {i["permalink"]: i for i in research.trending_feed(store)}
    t1 = feed["https://www.instagram.com/reel/T1/"]
    assert t1["media_url"] == "https://cdn/t1.mp4" and t1["topic"] == "mealprep"
    a1 = feed["https://www.instagram.com/reel/A1/"]
    assert a1["thumbnail_url"] == "https://cdn/a1.jpg" and a1["topic_kind"] == "account"


def test_refresh_409_when_running_and_503_without_instagram(store, settings):
    with TestClient(create_app(settings, store=store), base_url=LOCAL) as tc:
        assert research._refreshing.acquire(blocking=False)
        try:
            r = tc.post("/api/research/refresh")
        finally:
            research._refreshing.release()
        assert r.status_code == 409 and r.json()["error"] == "already_running"
    with TestClient(create_app(_settings(), store=store), base_url=LOCAL) as tc:
        r = tc.post("/api/research/refresh")
        assert r.status_code == 503 and r.json()["error"] == "instagram_not_configured"


def test_expired_cdn_links_are_dropped_on_the_next_run(store):
    out = {"stored": 0, "updated": 0}
    research._store(store, _post("X", media_url="https://cdn/old"), None, out,
                    research.HASHTAG_URLS, hashtag="fit")
    research._store(store, _post("X", like_count=None), None, out, research.HASHTAG_URLS,
                    hashtag="fit")
    [item] = research.trending_feed(store)
    assert item["media_url"] is None and item["likes"] == 10  # hidden likes: kept


# --- feed --------------------------------------------------------------------------------
def test_feed_ranks_by_outlier_then_recency_filters_and_embeds(store):
    for k in range(5):  # a hashtag group of 5: outliers known (likes / median 10)
        _ref(store, f"H{k}", likes=10 * (k + 1) if k == 4 else 10, hashtag="fitfood")
    old = _ref(store, "P1", path="p", hashtag="lonely", ts="2026-11-01T10:00:00+0000")
    new = _ref(store, "R1", author="someone", ts="2026-11-16T11:00:00+0000")
    store.add_source("pexels", url="https://pexels/1", external_id="9")  # not a Trending Reel
    feed = research.trending_feed(store)
    assert feed[0]["permalink"].endswith("/H4/") and feed[0]["outlier"] == 5.0
    assert [i["id"] for i in feed[-2:]] == [new, old]  # unscored: newest first
    assert len(feed) == 7
    p1 = feed[-1]
    assert p1["embed_url"] == "https://www.instagram.com/p/P1/embed"
    assert feed[0]["embed_url"] == "https://www.instagram.com/reel/H4/embed"
    assert p1["caption_quote"] == "Hook P1\nmore" and p1["reaction"] is None
    assert p1["work_order"] is None
    assert [i["id"] for i in research.trending_feed(store, topic="#Lonely")] == [old]
    assert [i["id"] for i in research.trending_feed(store, topic="@someone")] == [new]
    assert len(research.trending_feed(store, limit=2)) == 2
    assert research.embed_url("https://www.instagram.com/reels/AbC_1-x/?igsh=2") == \
        "https://www.instagram.com/reel/AbC_1-x/embed"
    assert research.embed_url("https://example.com/reel/x/") is None


def test_feed_api_reaction_and_suggested_topics(store):
    sid = _ref(store, "R1", hashtag="mealprep")
    store.add_watch("hashtag", "mealprep")
    store.take_hashtag_search("mealprep", datetime.now(timezone.utc), 30, timedelta(days=7))
    with TestClient(create_app(_settings(), store=store), base_url=LOCAL) as tc:
        assert [i["id"] for i in tc.get("/api/research/feed?topic=mealprep").json()] == [sid]
        assert tc.get("/api/research/feed?limit=0").status_code == 422
        r = tc.post(f"/api/research/feed/{sid}/reaction", json={"reaction": "like"})
        assert r.json() == {"id": sid, "reaction": "like"}
        assert tc.get("/api/research/feed").json()[0]["reaction"] == "like"
        assert tc.post("/api/research/feed/999/reaction",
                       json={"reaction": "like"}).status_code == 404
        assert tc.post(f"/api/research/feed/{sid}/reaction",
                       json={"reaction": "love"}).status_code == 422
        topics = tc.get("/api/research/suggested-topics").json()
    watched = {t["tag"]: t["watched"] for t in topics["topics"]}
    assert watched["mealprep"] is True and watched["musculation"] is False
    assert all(re.fullmatch(r"\w+", t) for t in watched)  # valid hashtags only
    assert {"fr", "intl"} == {t["lang"] for t in topics["topics"]}
    assert topics["hashtag_budget"]["left"] == 29 and "30 unique hashtags" in topics["note"]
    assert store.list_watchlist("hashtag") == [store.add_watch("hashtag", "mealprep")]


def test_reactions_feed_the_brief(store, settings, tmp_path, monkeypatch):
    monkeypatch.setattr(B, "BIBLE_PATH", tmp_path / "BIBLE.md")
    liked = _ref(store, "L1", likes=99, hashtag="fitfood")
    disliked = _ref(store, "D1", author="rival")
    research.set_reaction(store, liked, "like")
    research.set_reaction(store, disliked, "dislike")
    taste = B.creative_brief(store, settings, NOW)["trend_taste"]
    assert taste == {"liked": [{"source_id": liked, "topic": "fitfood", "hook_quote": "Hook L1",
                                "likes": 99, "comments": None, "views": None}],
                     "disliked": [{"source_id": disliked, "topic": "rival",
                                   "hook_quote": "Hook D1", "likes": 10, "comments": None,
                                   "views": None}]}
    research.set_reaction(store, liked, "none")
    assert B.creative_brief(store, settings, NOW)["trend_taste"]["liked"] == []
    with pytest.raises(ValueError):
        research.set_reaction(store, liked, "meh")


# --- work orders -------------------------------------------------------------------------
def test_work_order_validation_api(store):
    a, b = _ref(store, "A"), _ref(store, "B")
    clip = store.add_source("local", url="https://x/clip")["id"]
    with TestClient(create_app(_settings(), store=store), base_url=LOCAL) as tc:
        def post(items):
            return tc.post("/api/research/work-orders", json={"items": items})

        assert post([]).status_code == 422
        assert post([{"source_id": a, "mode": "copy"}]).status_code == 422
        r = post([{"source_id": 999, "mode": "react"}])
        assert r.status_code == 422 and "no Reel with id 999" in r.json()["message"]
        assert "not a Reel from the Trending feed" in post(
            [{"source_id": clip, "mode": "react"}]).json()["message"]
        assert "twice" in post([{"source_id": a, "mode": "react"},
                                {"source_id": a, "mode": "inspired"}]).json()["message"]
        assert post([{"source_id": a, "mode": "react",
                      "instruction": "x" * 501}]).status_code == 422
        r = post([{"source_id": a, "mode": "react", "instruction": "  React to the end  "},
                  {"source_id": b, "mode": "inspired"}])
        assert r.status_code == 200, r.text
        made = r.json()
        assert [(o["mode"], o["instruction"], o["status"]) for o in made] == [
            ("react", "React to the end", "new"), ("inspired", None, "new")]
        assert made[0]["permalink"] == "https://www.instagram.com/reel/A/"
        # all or none: one open order already -> nothing stored
        r = post([{"source_id": b, "mode": "react"}])
        assert "already has an open work order" in r.json()["message"]
        assert len(tc.get("/api/research/work-orders").json()) == 2
        assert tc.get("/api/research/feed").json()[0]["work_order"]["status"] == "new"
        assert tc.get("/api/research/work-orders?status=bad").status_code == 422
        assert tc.delete(f"/api/research/work-orders/{made[1]['id']}").status_code == 204
        assert tc.delete(f"/api/research/work-orders/{made[1]['id']}").status_code == 404
        assert [o["id"] for o in tc.get("/api/research/work-orders?status=new").json()] == \
            [made[0]["id"]]


def _finish(store, asset_id):
    store.update_asset(asset_id, qc=QC_OK, file_path=f"x/{asset_id}/video.mp4")
    transition(store, asset_id, "ready", actor="worker")


def test_inspired_order_lifecycle_to_the_feed(store, settings):
    sid = _ref(store, "A")
    [order] = work_orders.create_orders(store, [{"source_id": sid, "mode": "inspired",
                                                 "instruction": "Same joke, our macros"}])
    with pytest.raises(ValueError, match="inspired: an original video"):
        production.create_idea(store, settings, "remix", hook="h", source_id=sid,
                               work_order_id=order["id"])
    with pytest.raises(KeyError):
        production.create_idea(store, settings, "motion", hook="h", work_order_id=999)
    idea = production.create_idea(store, settings, "motion", hook="Macro joke",
                                  pillar="everyday_humor", work_order_id=order["id"])
    got = work_orders.get_order(store, order["id"])
    assert (got["status"], got["idea_id"]) == ("in_production", idea["id"])
    with pytest.raises(ValueError, match="only a new one gets an idea"):
        production.create_idea(store, settings, "motion", hook="Other", work_order_id=order["id"])
    with pytest.raises(ValueError, match="only a new one can be cancelled"):
        work_orders.delete_order(store, order["id"])
    asset = store.add_asset(idea["id"], batch_date=idea["batch_date"])["id"]
    _finish(store, asset)
    production.submit_asset(store, settings, asset, self_score=7,
                            self_score_reason="Work order #1: as asked", caption="c")
    got = work_orders.get_order(store, order["id"])
    assert (got["status"], got["asset_id"]) == ("in_feed", asset)
    [row] = store.list_assets()
    assert row["work_order"] == {"id": order["id"], "mode": "inspired",
                                 "instruction": "Same joke, our macros",
                                 "permalink": "https://www.instagram.com/reel/A/"}
    with pytest.raises(ValueError, match="only an open one"):
        work_orders.skip_order(store, order["id"], "late")
    other = store.add_asset(store.add_idea("motion", hook="x")["id"])
    assert [r["work_order"] for r in store.list_assets() if r["id"] == other["id"]] == [None]


def test_react_order_needs_its_remix_and_can_be_skipped(store, settings):
    sid = _ref(store, "A", author="creator")
    [order] = work_orders.create_orders(store, [{"source_id": sid, "mode": "react"}])
    with pytest.raises(ValueError, match="is a react"):
        production.create_idea(store, settings, "motion", hook="h", work_order_id=order["id"])
    with store._tx() as c:  # as download_reel leaves it
        c.execute("UPDATE sources SET role='clip', rights_basis='commentary', rights_note="
                  "'commentary', local_path='sources/1/clip.mp4' WHERE id=?", (sid,))
    for k in range(10):  # a full batch: the owner's order still gets made
        store.add_idea("motion", hook=f"filler {k}",
                       batch_date=production.local_today(settings.timezone))
    idea = production.create_idea(store, settings, "remix", hook="Wait for it",
                                  pillar="everyday_humor", source_id=sid,
                                  work_order_id=order["id"])
    assert work_orders.get_order(store, order["id"])["idea_id"] == idea["id"]
    with pytest.raises(ValueError, match="say why"):
        work_orders.skip_order(store, order["id"], " ")
    got = work_orders.skip_order(store, order["id"], "downloader refused: private")
    assert (got["status"], got["skip_reason"]) == ("skipped", "downloader refused: private")
    # skipped: the Reel can be ordered again
    assert work_orders.create_orders(store, [{"source_id": sid, "mode": "inspired"}])


async def test_mcp_doors(store, settings, monkeypatch):
    monkeypatch.setattr(srv, "store", lambda: store)
    monkeypatch.setattr(srv, "get_settings", lambda: settings)
    sid = _ref(store, "A")
    [order] = work_orders.create_orders(store, [{"source_id": sid, "mode": "inspired"}])
    [seen] = (await srv.list_work_orders())["orders"]
    assert set(seen) == set(work_orders.AGENT_KEYS) and seen["caption_quote"] == "Hook A"
    idea = await srv.create_idea("motion", "Our version", pillar="everyday_humor",
                                 work_order_id=order["id"])
    assert (await srv.list_work_orders())["orders"] == []
    assert (await srv.list_work_orders("in_production"))["orders"][0]["idea_id"] == idea["id"]
    assert (await srv.skip_work_order(order["id"], "no angle"))["status"] == "skipped"
    with pytest.raises(srv.ToolError):
        await srv.skip_work_order(order["id"], "again")


# --- agent side ----------------------------------------------------------------------------
def test_packet_section_first_and_valid(store, settings, tmp_path, monkeypatch):
    monkeypatch.setattr(B, "BIBLE_PATH", tmp_path / "BIBLE.md")
    sid = _ref(store, "A")
    store.patch_source_stats(sid, {"caption": "x" * 600})
    work_orders.create_orders(store, [{"source_id": sid, "mode": "react",
                                       "instruction": "Point at the spoon"}])
    for playbook in ("daily-produce", "daily-revise"):
        out = packet.write_packet(store, settings, playbook, tmp_path / playbook, now=NOW)
        sections = out["manifest"]["sections"]
        assert list(sections)[0] == "work_orders" and sections["work_orders"]["count"] == 1
        data = json.loads((tmp_path / playbook / "work" / "work_orders.json").read_bytes())
        assert data["untrusted_captions"] is True
        assert data["orders"][0]["instruction"] == "Point at the spoon"
        assert len(data["orders"][0]["caption_quote"]) == work_orders.CAPTION_LINE
    brief = json.loads((tmp_path / "daily-produce" / "work" / "brief.json").read_bytes())
    assert list(brief)[0] == "work_orders" and brief["work_orders"][0]["mode"] == "react"
    with pytest.raises(packet.PacketError, match="work_orders is invalid"):
        packet.encode({"untrusted_captions": True, "orders": [{"id": 1, "mode": "copy"}]},
                      "work_orders")


@pytest.mark.parametrize("name", ["daily-produce", "daily-revise"])
def test_playbooks_make_work_orders_first(name):
    text = (AGENT_DIR / "playbooks" / f"{name}.md").read_text(encoding="utf-8")
    for rule in ("work_orders.json", "work_order_id", "skip_work_order", "literally",
                 "inspired", "react", "nothing of the Reel", "Work order #<id>: ",
                 "caption_quote"):
        assert rule.lower() in text.lower(), rule
    first = text.lower().index("work order")
    assert first < text.lower().index("feedback")  # before anything else
