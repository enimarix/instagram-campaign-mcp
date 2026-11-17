"""Followers online per hour (022): Graph client, store, collection service."""

import sqlite3
from datetime import date, timedelta

import httpx
import pytest
import respx

from src.campaign import collect_online_followers
from src.instagram_client import InstagramAPIError
from src.store import MIGRATIONS, CampaignStore, utcnow

from .conftest import API

URL = f"{API}/1789/insights"


def _payload(value, end_time="2026-06-10T07:00:00+0000"):
    return {"data": [{"name": "online_followers", "period": "lifetime",
                      "values": [{"value": value, "end_time": end_time}]}]}


@respx.mock
async def test_online_followers_pacific_hours_to_utc(client):
    route = respx.get(URL).respond(json=_payload({"0": 5, "17": 40, "23": 9}))
    # June: Pacific is UTC-7.
    assert await client.get_online_followers() == {7: 5, 0: 40, 6: 9}
    params = route.calls.last.request.url.params
    assert params["metric"] == "online_followers" and params["period"] == "lifetime"

    respx.get(URL).respond(json=_payload({"0": 5}, "2026-01-10T08:00:00+0000"))
    assert await client.get_online_followers() == {8: 5}  # January: UTC-8


@respx.mock
@pytest.mark.parametrize("response", [
    {"json": {"data": []}},  # fewer than 100 followers: empty data set
    {"json": _payload({})},
    {"status_code": 400, "json": {"error": {"message": "(#100) metric must be one of ...",
                                            "code": 100}}},
])
async def test_online_followers_not_available_is_none(client, response):
    respx.get(URL).respond(**response)
    assert await client.get_online_followers() is None


@respx.mock
async def test_online_followers_other_errors_raise(client):
    respx.get(URL).respond(status_code=400, json={"error": {"message": "bad token", "code": 190}})
    with pytest.raises(InstagramAPIError):
        await client.get_online_followers()
    respx.get(URL).mock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(InstagramAPIError):
        await client.get_online_followers()


def test_upgrade_from_v3_keeps_data(tmp_path):
    db = str(tmp_path / "v3.db")
    conn = sqlite3.connect(db)
    for script in MIGRATIONS[:3]:
        conn.executescript(script)
    conn.execute("PRAGMA user_version=3")
    conn.execute("INSERT INTO daily_reports (report_date, facts, created_at)"
                 " VALUES ('2026-06-01', '{}', '2026-06-01T00:00:00+00:00')")
    conn.commit()
    conn.close()
    s = CampaignStore(db)
    try:
        assert s.get_daily_report("2026-06-01") is not None
        assert s.save_online_followers(date(2026, 6, 1), {7: 3}) == 1
    finally:
        s.close()
    conn = sqlite3.connect(db)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS) >= 4
    conn.close()


def test_save_upserts_and_profile_averages_recent_days(store):
    today = utcnow().date()
    store.save_online_followers(today, {18: 10, 19: 20})
    store.save_online_followers(today, {18: 30})  # same date+hour: replaced
    store.save_online_followers(today - timedelta(days=1), {18: 10})
    store.save_online_followers(today - timedelta(days=28), {18: 1000})  # too old
    assert store.online_followers_profile() == {18: 20, 19: 20}
    assert store.online_followers_profile(days=40) == {18: pytest.approx(1040 / 3), 19: 20}
    with pytest.raises(sqlite3.IntegrityError):
        store.save_online_followers(today, {24: 1})


@respx.mock
async def test_collect_online_followers(client, store):
    respx.get(URL).respond(json=_payload({"0": 5, "1": 6}))
    day = date(2026, 6, 10)
    assert await collect_online_followers(client, store, day) == {"available": True, "saved": 2}
    respx.get(URL).respond(json={"data": []})
    assert await collect_online_followers(client, store, day) == {"available": False, "saved": 0}
