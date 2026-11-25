"""Regression tests for the second audit's findings."""

import asyncio
from datetime import timedelta
from io import BytesIO

import httpx
import pytest
import respx
from PIL import Image

from src import campaign as camp
from src.config import _app_home
from src.instagram_client import (
    InstagramAPIError,
    InstagramClient,
    InvalidMedia,
    RateLimitExceeded,
    RequestBudget,
)
from src.scoring import ScoringConfig, score_posts
from src.store import parse_iso, to_iso, utcnow

from .conftest import API


def _image(w, h, fmt="JPEG"):
    buf = BytesIO()
    Image.new("RGB", (w, h), "white").save(buf, fmt)
    return buf.getvalue()


def _publish_ok(media_id="M1"):
    respx.post(f"{API}/1789/media").respond(json={"id": "C1"})
    respx.get(f"{API}/C1").respond(json={"status_code": "FINISHED"})
    respx.post(f"{API}/1789/media_publish").respond(json={"id": media_id})
    respx.get(f"{API}/{media_id}").respond(json={"id": media_id})


def _due(store, kind="image", payload=None):
    return store.schedule(kind, payload or {"image_url": "https://x/1.jpg"},
                          utcnow() - timedelta(seconds=5))


# ------------------------------------------------ 1. container ERROR subcode
@respx.mock
async def test_container_error_subcode_is_permanent(client, store):
    respx.post(f"{API}/1789/media").respond(json={"id": "C1"})
    respx.get(f"{API}/C1").respond(json={"status_code": "ERROR", "status": "Error: 2207026"})
    p = _due(store, "reel", {"video_url": "https://x/bad.mp4"})
    res = await camp.run_due(client, store)
    assert res["failed"] and not res["retrying"]
    assert store.get_scheduled(p["id"])["status"] == "failed"


# ------------------------------------------------ 2. request budget
async def test_budget_fails_fast_instead_of_blocking():
    budget = RequestBudget(per_hour=2, max_wait=1.0)
    await budget.acquire()
    await budget.acquire()
    with pytest.raises(RateLimitExceeded, match="next slot"):
        await asyncio.wait_for(budget.acquire(), timeout=1)


async def test_budget_waits_when_a_slot_frees_soon():
    budget = RequestBudget(per_hour=1, max_wait=1.0, period=0.05)
    await budget.acquire()
    await asyncio.wait_for(budget.acquire(), timeout=1)  # waits ~50ms, no error


# ------------------------------------------------ 3. Stories
def test_expired_story_without_late_snapshot_is_incomplete():
    old = to_iso(utcnow() - timedelta(hours=30))
    snap = {"media_id": "S1", "media_product_type": "STORY", "age_hours": 9,
            "posted_at": old, "metrics": {"reach": 500}}
    live = dict(snap, media_id="S2", posted_at=to_iso(utcnow() - timedelta(hours=9)))
    scored = {r["media_id"]: r for r in score_posts([snap, live])}
    assert scored["S1"]["verdict"] == "incomplete"
    assert scored["S2"]["verdict"] == "too_early"


@respx.mock
async def test_stories_only_collect_skips_feed(client, store):
    feed = respx.get(f"{API}/1789/media").respond(json={"data": []})
    respx.get(f"{API}/1789/stories").respond(json={"data": [
        {"id": "S1", "timestamp": to_iso(utcnow() - timedelta(hours=23))}]})
    respx.get(f"{API}/S1/insights").respond(json={"data": [
        {"name": "reach", "values": [{"value": 50}]}]})
    res = await camp.collect_insights(client, store, limit=0)
    assert res["captured"] == 1 and not feed.called


# ------------------------------------------------ 4 & 9. image checks
@pytest.fixture
async def checking_client(settings):
    c = InstagramClient(settings.model_copy(update={"validate_image_ratio": True}),
                        http_client=httpx.AsyncClient())
    yield c
    await c.close()


@pytest.mark.parametrize("w,h,ok", [
    (1080, 1350, True),    # 4:5
    (1080, 1080, True),    # 1:1
    (1080, 864, True),     # 5:4 - between the old fixed ratios
    (1920, 1080, True),    # 16:9
    (1080, 566, True),     # 1.91:1
    (1080, 1920, False),   # 9:16 is for Reels/Stories, not feed
    (2000, 1000, False),   # 2:1
])
@respx.mock
async def test_feed_ratio_range(checking_client, w, h, ok):
    respx.get("https://cdn/img.jpg").respond(content=_image(w, h))
    if ok:
        await checking_client._check_image("https://cdn/img.jpg")
    else:
        with pytest.raises(InvalidMedia, match="between 4:5"):
            await checking_client._check_image("https://cdn/img.jpg")


@respx.mock
async def test_png_is_rejected_before_calling_meta(checking_client):
    respx.get("https://cdn/img.png").respond(content=_image(1080, 1080, "PNG"))
    create = respx.post(f"{API}/1789/media").respond(json={"id": "C1"})
    with pytest.raises(InvalidMedia, match="JPEG"):
        await checking_client.publish_image("https://cdn/img.png")
    assert not create.called


@respx.mock
async def test_carousel_images_all_checked_before_any_container(checking_client):
    respx.get("https://cdn/1.jpg").respond(content=_image(1080, 1350))
    respx.get("https://cdn/2.png").respond(content=_image(1080, 1350, "PNG"))
    create = respx.post(f"{API}/1789/media").respond(json={"id": "K1"})
    with pytest.raises(InvalidMedia, match="JPEG"):
        await checking_client.publish_carousel(
            [{"image_url": "https://cdn/1.jpg"}, {"image_url": "https://cdn/2.png"}])
    assert not create.called


@respx.mock
async def test_invalid_media_is_not_retried(client, store):
    p = _due(store, "image", {"image_url": "https://x/1.jpg",
                              "caption": " ".join(f"#t{i}" for i in range(31))})
    res = await camp.run_due(client, store)
    assert res["failed"] and store.get_scheduled(p["id"])["status"] == "failed"


# ------------------------------------------------ 5. DM page
@respx.mock
async def test_dm_refuses_unlinked_page(client):
    respx.get(f"{API}/me/accounts").respond(json={"data": [
        {"id": "OTHER", "instagram_business_account": {"id": "someone-else"}}]})
    send = respx.post(f"{API}/OTHER/messages").respond(json={})
    with pytest.raises(InstagramAPIError, match="No Facebook Page linked"):
        await client.send_dm("IGSID", "hi")
    assert not send.called


# ------------------------------------------------ 6. ambiguous media_publish errors
@respx.mock
async def test_publish_error_but_container_published_is_not_retried(client, store):
    respx.post(f"{API}/1789/media").respond(json={"id": "C1"})
    respx.get(f"{API}/C1").mock(side_effect=[
        httpx.Response(200, json={"status_code": "FINISHED"}),     # before publish
        httpx.Response(200, json={"status_code": "PUBLISHED"}),    # after the error
    ])
    respx.post(f"{API}/1789/media_publish").respond(
        500, json={"error": {"message": "An unknown error occurred", "code": 1}})
    p = _due(store)
    res = await camp.run_due(client, store)
    post = store.get_scheduled(p["id"])
    assert res["failed"] and post["status"] == "failed"
    assert "reports the post as published" in post["error"]


@respx.mock
async def test_publish_error_with_unpublished_container_is_retried(client, store):
    respx.post(f"{API}/1789/media").respond(json={"id": "C1"})
    respx.get(f"{API}/C1").respond(json={"status_code": "FINISHED"})
    respx.post(f"{API}/1789/media_publish").respond(
        500, json={"error": {"message": "Service temporarily unavailable", "code": 2}})
    p = _due(store)
    res = await camp.run_due(client, store)
    assert res["retrying"] and store.get_scheduled(p["id"])["status"] == "pending"


# ------------------------------------------------ 7. age-matched baseline
def test_baseline_is_read_at_a_similar_age():
    def snap(mid, age, reach):
        return {"media_id": mid, "media_product_type": "FEED", "age_hours": age,
                "posted_at": "2026-11-01", "metrics": {"reach": reach, "saved": reach // 100}}

    target = snap("new", 48, 1000)
    latest = [target] + [snap(f"b{i}", 720, 3000) for i in range(5)]
    history = {f"b{i}": [snap(f"b{i}", 49, 1000), snap(f"b{i}", 720, 3000)] for i in range(5)}
    cfg = ScoringConfig(min_reach=100)
    without = {r["media_id"]: r for r in score_posts(latest, cfg)}["new"]
    with_hist = {r["media_id"]: r for r in score_posts(latest, cfg, history=history)}["new"]
    assert without["verdict"] == "no_baseline"  # 720 h baselines are > 2x its 48 h: left out
    assert with_hist["reach_index"] == pytest.approx(1.0)


def test_one_share_and_one_save_is_not_a_winner():
    def reel(mid, reach, shares, saved):
        return {"media_id": mid, "media_product_type": "REELS", "age_hours": 48,
                "metrics": {"reach": reach, "shares": shares, "saved": saved, "likes": 5}}

    base = [reel(f"b{i}", 300, 0, 0) for i in range(6)] + [reel("b9", 1000, 3, 3)]
    scored = {r["media_id"]: r for r in score_posts(
        [reel("one", 468, 1, 1), reel("ten", 1000, 10, 11)] + base)}
    assert scored["one"]["verdict"] == "average"  # was 3.35 "winner": one event hit the 5x cap
    assert scored["one"]["engagement_index"] < 1.2
    assert scored["ten"]["verdict"] == "winner"   # real differences still show


# ------------------------------------------------ 10. config home
def test_app_home_for_source_and_installed_layouts(tmp_path, monkeypatch):
    monkeypatch.delenv("IG_MCP_HOME", raising=False)
    (tmp_path / "pyproject.toml").write_text("")
    assert _app_home(tmp_path) == tmp_path
    site = tmp_path / "site-packages"
    site.mkdir()
    assert _app_home(site).name == ".instagram-campaign-mcp"
    monkeypatch.setenv("IG_MCP_HOME", str(tmp_path / "custom"))
    assert _app_home(site) == (tmp_path / "custom").resolve()


# ------------------------------------------------ 11. heartbeat
async def test_slow_publish_keeps_its_claim_alive(client, store, monkeypatch):
    monkeypatch.setattr(camp, "HEARTBEAT_SECONDS", 0.01)
    touched = []
    real_touch = store.touch
    monkeypatch.setattr(store, "touch", lambda pid: (touched.append(pid), real_touch(pid)))

    async def slow_publish(client, kind, payload):
        await asyncio.sleep(0.08)
        return {"media_id": "M9"}

    monkeypatch.setattr(camp, "publish", slow_publish)
    p = _due(store)
    res = await camp.run_due(client, store)
    assert res["published"] and len(touched) >= 3 and set(touched) == {p["id"]}


def test_recover_stuck_ignores_touched_posts(store):
    p = _due(store)
    store.claim_due()
    store._conn.execute("UPDATE scheduled_posts SET updated_at=? WHERE id=?",
                        (to_iso(utcnow() - timedelta(hours=1)), p["id"]))
    store.touch(p["id"])
    assert store.recover_stuck() == 0


# ------------------------------------------------ 12a. publishing quota
@respx.mock
async def test_publishing_quota_waits_without_burning_attempts(client, store):
    respx.post(f"{API}/1789/media").respond(400, json={"error": {
        "message": "Too many posts", "code": 9, "error_subcode": 2207042}})
    ids = [_due(store)["id"] for _ in range(2)]
    res = await camp.run_due(client, store)
    assert len(res["retrying"]) == 1 and not res["failed"]
    first = store.get_scheduled(ids[0])
    assert first["status"] == "pending" and first["attempts"] == 0
    assert store.get_scheduled(ids[1])["attempts"] == 0  # not even tried


# ------------------------------------------------ 12b. rank summary
def test_rank_summary_counts_before_only_filter(store, settings):
    for i in range(6):
        store.add_snapshot(f"b{i}", {"reach": 1000, "saved": 10}, "FEED", "IMAGE",
                           to_iso(utcnow() - timedelta(days=3)))
    store.add_snapshot("young", {"reach": 10}, "FEED", "IMAGE",
                       to_iso(utcnow() - timedelta(hours=2)))
    out = camp.rank(store, settings, only="too_early")
    assert [p["media_id"] for p in out["posts"]] == ["young"]
    assert out["summary"]["too_early"] == 1 and sum(out["summary"].values()) == 7


# ------------------------------------------------ 12c. date parsing
@pytest.mark.parametrize("value,expected", [
    ("2026-11-01T10:00:00+0000", "2026-11-01T10:00:00+00:00"),
    ("2026-11-01T10:00:00Z", "2026-11-01T10:00:00+00:00"),
    ("2026-11-01T10:00:00.5+01", "2026-11-01T10:00:00.500000+01:00"),
    ("2026-11-01T10:00:00.1234567-0530", "2026-11-01T10:00:00.123456-05:30"),
    ("2026-11-01 10:00", "2026-11-01T10:00:00"),
    ("2026-11-01", "2026-11-01T00:00:00"),
])
def test_parse_iso_formats(value, expected):
    assert parse_iso(value).isoformat() == expected
