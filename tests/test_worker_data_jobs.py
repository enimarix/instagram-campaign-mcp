"""Step 026: worker data jobs (age schedule, shared budget, daily jobs, deleted posts)."""

from datetime import datetime, timedelta, timezone

import httpx
import pytest
import respx

from src import worker
from src.campaign import collect_due_insights, due_snapshot_points
from src.config import InstagramMCPSettings
from src.instagram_client import (
    InstagramAPIError,
    InstagramClient,
    RateLimitExceeded,
    RequestBudget,
)
from src.store import CampaignStore, to_iso

from .conftest import API

T = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)
H = timedelta(hours=1)


@pytest.mark.parametrize("age, taken, due", [
    (0.5 * H, [], []),                         # too young
    (1.5 * H, [], [H]),                        # 1 h crossed
    (1.5 * H, [1.2 * H], []),                  # ...and taken
    (10 * H, [1.2 * H], [3 * H, 6 * H]),       # backlog: one snapshot settles both
    (49 * H, [47 * H], [48 * H]),
    (24 * 31 * H, [24 * 8 * H], [24 * 30 * H]),  # the 30 d point within the grace
    (24 * 32 * H, [], []),                     # none after 30 d (+ grace)
])
def test_due_snapshot_points(age, taken, due):
    posted = T - age
    assert due_snapshot_points(posted, [posted + t for t in taken], T) == due


async def test_two_clients_on_one_db_share_one_budget(settings, tmp_path):
    settings.rate_limit_requests_per_hour = 3
    stores = [CampaignStore(str(tmp_path / "c.db")) for _ in range(2)]
    a, b = (InstagramClient(settings, http_client=httpx.AsyncClient(), store=s) for s in stores)
    try:
        with respx.mock:
            respx.get(f"{API}/me").mock(return_value=httpx.Response(200, json={"id": "1"}))
            await a._make_request("GET", "me")
            await b._make_request("GET", "me")
            await a._make_request("GET", "me")
            assert a.budget.used() == b.budget.used() == 3
            with pytest.raises(RateLimitExceeded):
                await b._make_request("GET", "me")
    finally:
        for c in (a, b):
            await c.close()
        for s in stores:
            s.close()


class FakeClient:
    def __init__(self, posts=(), missing=()):
        self.posts, self.missing = list(posts), set(missing)
        self.insights, self.account_calls = [], 0
        self.budget = RequestBudget(10)

    async def get_media_posts(self, limit=25, after=None):
        return {"posts": self.posts, "next_cursor": None}

    async def get_media_insights(self, media_id, media_product_type=None):
        self.insights.append(media_id)
        if media_id in self.missing:
            raise InstagramAPIError("Object does not exist", 100, 33)
        return {"metrics": {"reach": 10}}

    async def get_profile_info(self):
        self.account_calls += 1
        return {"followers_count": 120}

    async def get_account_insights(self, metrics=None, breakdown=None):
        if breakdown == "follow_type":
            results = [{"dimension_values": ["FOLLOWER"], "value": 30},
                       {"dimension_values": ["NON_FOLLOWER"], "value": 70}]
            return [{"name": "reach", "total_value": {"value": 100, "breakdowns": [
                {"dimension_keys": ["follow_type"], "results": results}]}}]
        return [{"name": "reach", "total_value": {"value": 100}},
                {"name": "views", "total_value": {"value": 400}}]

    async def get_online_followers(self):
        return None


def _post(media_id, age):
    return {"id": media_id, "timestamp": to_iso(T - age), "media_product_type": "REELS"}


def _snap(store, media_id, age, taken_at_age):
    store.add_snapshot(media_id, {"reach": 1}, "REELS", "VIDEO", to_iso(T - age),
                       captured_at=T - age + taken_at_age)


async def test_only_due_posts_are_fetched_and_deleted_posts_keep_snapshots(store):
    _snap(store, "B", 2 * H, 1.5 * H)    # 1 h point taken, 3 h not crossed yet
    _snap(store, "C", 72 * H, 24 * H)    # known, gone from the account, 48 h due
    fake = FakeClient([_post("A", 2 * H), _post("B", 2 * H)], missing={"C"})
    res = await collect_due_insights(fake, store, T)
    assert sorted(fake.insights) == ["A", "C"]
    assert res["captured"] == 1 and res["deleted"] == ["C"]
    assert store.get_label("C")["deleted_at"] == to_iso(T)
    assert "C" in {s["media_id"] for s in store.latest_snapshots()}  # analytics keep it
    fake.insights.clear()
    await collect_due_insights(fake, store, T + 2 * H)  # A, B cross 3 h; C is never asked again
    assert sorted(fake.insights) == ["A", "B"]


async def test_daily_jobs_once_per_local_day_and_account_row(store):
    cfg = InstagramMCPSettings(_env_file=None, database_path=":memory:", timezone="UTC")
    fake = FakeClient()
    for t in (T, T + H, T + 24 * H):
        await worker.data_jobs(fake, store, cfg, now=lambda t=t: t)
    assert fake.account_calls == 2
    rows = store.account_snapshots()
    assert [r["date"] for r in rows] == ["2026-11-17", "2026-11-18"]
    assert (rows[0]["followers"], rows[0]["reach"], rows[0]["views"],
            rows[0]["reach_followers"], rows[0]["reach_non_followers"]) == (120, 100, 400, 30, 70)


async def test_data_jobs_stop_when_their_budget_share_is_spent(store):
    cfg = InstagramMCPSettings(_env_file=None, database_path=":memory:")
    fake = FakeClient([_post("A", 2 * H)])
    for _ in range(8):  # 80 % of 10 used, e.g. by publishing
        await fake.budget.acquire()
    res = await worker.data_jobs(fake, store, cfg, now=lambda: T)
    assert set(res.values()) == {"skipped: request budget"}
    assert fake.insights == [] and fake.account_calls == 0
    assert store.get_state("account_day") is None  # retried on a later tick
