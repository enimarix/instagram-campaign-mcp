"""Step 167: a Meta block trips the Graph breaker; posts wait, data jobs skip, one alert."""

from datetime import timedelta

import httpx
import pytest
import respx

from src import campaign as camp
from src import worker
from src.instagram_client import (
    BREAKER_KEY,
    BREAKER_MAX_PAUSE_S,
    BREAKER_PAUSE_S,
    BREAKER_PROBE_S,
    AccessBlocked,
    InstagramAPIError,
    InstagramClient,
)
from src.store import parse_dt, to_iso, utcnow
from src.studio import alerts
from src.studio import token as token_mod

from .conftest import API

T = 1_800_000_000.0
BLOCKED = {"error": {"code": 200, "error_subcode": 5258005, "message": "API access blocked."}}


class Clock:
    def __init__(self, t=T):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
async def bc(settings, store, clock):
    """A client sharing the breaker through the store, on a fake clock."""
    c = InstagramClient(settings, http_client=httpx.AsyncClient(), store=store)
    c.breaker.clock = clock
    yield c
    await c.close()


def _me(*responses):
    return respx.get(f"{API}/me").mock(side_effect=[
        httpx.Response(400, json=r) if "error" in r else httpx.Response(200, json=r)
        for r in responses])


@respx.mock
async def test_trip_then_no_network_and_no_budget_slot(bc, store):
    route = _me(BLOCKED)
    with pytest.raises(AccessBlocked, match="Meta paused API access: API access blocked"):
        await bc._make_request("GET", "me")
    used = bc.budget.used()
    for _ in range(3):
        with pytest.raises(AccessBlocked) as e:
            await bc._make_request("GET", "me")
    assert route.call_count == 1 and bc.budget.used() == used
    assert e.value.error_subcode == 5258005 and e.value.until == T + BREAKER_PAUSE_S
    assert store.get_state(BREAKER_KEY)["pause_s"] == BREAKER_PAUSE_S


@respx.mock
async def test_one_probe_after_the_pause_doubling_cap_and_reset(bc, clock):
    route = _me(BLOCKED, BLOCKED, BLOCKED, {"id": "1"})
    with pytest.raises(AccessBlocked):
        await bc._make_request("GET", "me")
    pause = BREAKER_PAUSE_S
    for _ in range(2):  # each failed probe doubles the pause
        clock.t += pause
        with pytest.raises(AccessBlocked):
            await bc._make_request("GET", "me")
        pause *= 2
        assert bc.breaker.state()["pause_s"] == pause
    clock.t += pause
    assert (await bc._make_request("GET", "me"))["id"] == "1"  # the probe succeeds
    assert bc.breaker.state() is None and route.call_count == 4


@respx.mock
async def test_while_the_probe_is_out_other_calls_wait(bc, store, clock):
    _me(BLOCKED)
    with pytest.raises(AccessBlocked):
        await bc._make_request("GET", "me")
    clock.t += BREAKER_PAUSE_S
    bc.breaker.check()  # another call took the probe
    with pytest.raises(AccessBlocked):
        await bc._make_request("GET", "me")
    assert bc.breaker.blocked_until() == clock.t + BREAKER_PROBE_S


async def test_pause_is_capped(bc, clock):
    for _ in range(10):
        bc.breaker.trip(368, None, "Temporarily blocked")
        clock.t = bc.breaker.state()["until"]
    assert bc.breaker.state()["pause_s"] == BREAKER_MAX_PAUSE_S


@respx.mock
async def test_any_other_answer_resets_and_other_errors_never_trip(bc, clock):
    _me(BLOCKED, {"error": {"code": 100, "error_subcode": 33, "message": "gone"}})
    with pytest.raises(AccessBlocked):
        await bc._make_request("GET", "me")
    clock.t += BREAKER_PAUSE_S
    with pytest.raises(InstagramAPIError) as e:
        await bc._make_request("GET", "me")
    assert not isinstance(e.value, AccessBlocked) and bc.breaker.state() is None
    # a 190 on another token (app token: bad app credentials) does not trip
    respx.get(f"{API}/debug_token").respond(400, json={"error": {
        "code": 190, "error_subcode": 463, "message": "expired"}})
    with pytest.raises(InstagramAPIError):
        await bc._make_request("GET", "debug_token", token="app|secret")
    assert bc.breaker.state() is None


@respx.mock
async def test_shared_through_the_store_and_a_new_token_starts_clean(bc, settings, store):
    _me({"error": {"code": 190, "error_subcode": 463, "message": "Session has expired"}})
    with pytest.raises(AccessBlocked):
        await bc._make_request("GET", "me")
    async with InstagramClient(settings, http_client=httpx.AsyncClient(), store=store) as other:
        with pytest.raises(AccessBlocked):
            await other._make_request("GET", "me")
    fresh = settings.model_copy(update={"instagram_access_token": "new_token"})
    async with InstagramClient(fresh, http_client=httpx.AsyncClient(), store=store) as new:
        assert new.breaker.blocked_until() is None


@respx.mock
async def test_blocked_post_stays_pending_with_its_attempts(settings, store):
    async with InstagramClient(settings, http_client=httpx.AsyncClient(), store=store) as c:
        route = respx.post(f"{API}/1789/media").respond(400, json=BLOCKED)
        p = store.schedule("image", {"image_url": "https://x/1.jpg", "caption": "hi"},
                           utcnow() - timedelta(seconds=5))
        q = store.schedule("image", {"image_url": "https://x/2.jpg", "caption": "hi"},
                           utcnow() - timedelta(seconds=1))
        res = await camp.run_due(c, store)
        assert len(res["retrying"]) == 1 and not res["failed"]
        row = store.get_scheduled(p["id"])
        assert row["status"] == "pending" and row["attempts"] == 0
        assert "Meta paused API access" in row["error"]
        wait = (parse_dt(row["publish_at"]) - utcnow()).total_seconds()
        assert BREAKER_PAUSE_S - 120 < wait <= BREAKER_PAUSE_S + 60  # the breaker's next try
        assert store.get_scheduled(q["id"])["attempts"] == 0  # the round stopped at the first
        for _ in range(camp.MAX_ATTEMPTS + 1):  # due again while tripped: refused locally
            with store._tx() as conn:
                conn.execute("UPDATE scheduled_posts SET publish_at=? WHERE id=?",
                             (to_iso(utcnow() - timedelta(seconds=5)), p["id"]))
            await camp.run_due(c, store)
    assert route.call_count == 1
    row = store.get_scheduled(p["id"])
    assert row["status"] == "pending" and row["attempts"] == 0


async def test_data_jobs_skip_while_tripped(settings, store):
    async with InstagramClient(settings, http_client=httpx.AsyncClient(), store=store) as c:
        c.breaker.trip(200, 5258005, "API access blocked.")
        res = await worker.data_jobs(c, store, settings)
    assert res and all(str(v).startswith("skipped: Meta blocked API access until ")
                       for v in res.values())


@respx.mock
async def test_token_status_caches_a_failed_check(bc, settings, clock, monkeypatch):
    monkeypatch.setattr(token_mod, "_status", {})
    route = respx.get(f"{API}/debug_token").respond(400, json=BLOCKED)
    out = await token_mod.token_status(bc, settings, clock=clock)
    assert out["valid"] is None and "API access blocked" in out["error"]
    await token_mod.token_status(bc, settings, clock=lambda: T + 599)
    assert route.call_count == 1
    clock.t += BREAKER_PAUSE_S  # the breaker would let a probe through, the cache holds
    await token_mod.token_status(bc, settings, clock=lambda: T + 601)
    assert route.call_count == 2


async def test_alert_shown_then_cleared(bc, settings, store, monkeypatch):
    monkeypatch.setattr(token_mod, "_status", {})

    async def ids():
        return [a for a in await alerts.alerts(store, settings, utcnow())
                if a["kind"] == "graph_blocked"]

    assert await ids() == []
    bc.breaker.trip(200, 5258005, "API access blocked.")
    [a] = await ids()
    assert a["severity"] == "error" and a["title"] == "Meta blocked the studio's API access"
    assert "Confirm Account" in a["detail"] and "Next try" in a["detail"]
    assert a["link"] == "https://developers.facebook.com/apps/"
    bc.breaker.reset()
    assert await ids() == []
