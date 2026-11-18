"""Step 095: the ads sync. Kill enforcement reaches Meta (ledger and outside objects, while
killed), the ledger never under-counts (deltas, no double count, guard usage after a
sync), over-spend alerts and kills, review issues, stop rules, near-cap alerts, the
results API and the worker cadence. Meta is respx (test_ads_tests' fixture)."""

import ast
import json
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
import respx
from fastapi.testclient import TestClient

from src import worker
from src.ads import budget, sync, tests
from src.api.app import create_app
from src.api.auth import Auth
from src.store import CampaignStore, utcnow
from src.studio import alerts

from .test_ads_budget import spend_violations
from .test_ads_tests import (
    ACT,
    _audit,
    _propose,
    _settings,
    _status_calls,
    meta,  # noqa: F401 - the Meta fixture
)
from .test_worker_data_jobs import FakeClient

DAY = timedelta(days=1)
# launch() below: variant A = campaign 900, ad set 901, ad 903; B = 904, 905, 907.
ENTITIES = {"900", "901", "903", "904", "905", "907"}


@pytest.fixture
def ads(meta):  # noqa: F811
    """+ per-ad-set insights (`ads.insights[adset id] = row`) and the account's lists
    (`ads.objects[edge]`, `ads.list_fail`: edges that answer an error)."""
    meta.insights, meta.list_fail = {}, set()
    meta.objects = {"campaigns": [], "adsets": [], "ads": []}

    def insights(req):
        row = meta.insights.get(req.url.path.split("/")[2])
        return respx.MockResponse(json={"data": [row] if row else []})

    def lister(req):
        edge = req.url.path.rsplit("/", 1)[-1]
        if edge in meta.list_fail:
            return respx.MockResponse(400, json={"error": {"message": "nope", "code": 1}})
        return respx.MockResponse(json={"data": meta.objects[edge]})

    meta.get(path__regex=r"^/v25\.0/\d+/insights$").mock(side_effect=insights)
    for edge in meta.objects:
        meta.get(f"{ACT}/{edge}").mock(side_effect=lister)
    return meta


async def _running(store, s):
    t = await _propose(store, s)
    await tests.launch(store, s, t["id"], "427", actor="owner")
    return t["id"]


def _spend(a, b, **kw):
    return {"901": {"impressions": "1000", "clicks": "20", "spend": a, "reach": "800", **kw},
            "905": {"impressions": "900", "clicks": "9", "spend": b, "reach": "700"}}


def _reported(store):
    with store.immediate() as c:
        return [(r[0], r[1]) for r in c.execute(
            "SELECT authorization_id, amount FROM ad_spend_ledger WHERE kind='reported'"
            " ORDER BY id")]


def _alerts(store, now):
    return {a["id"]: a for a in alerts._raised(store, now)}


# --- kill enforcement -------------------------------------------------------------------
async def test_kill_pauses_the_ledger_and_every_outside_active_object(store, ads):
    s = _settings()
    tid = await _running(store, s)
    budget.kill(store, "panic")
    ads.objects.update(
        campaigns=[{"id": "900", "status": "ACTIVE"}, {"id": "904", "status": "PAUSED"},
                   {"id": "777", "status": "ACTIVE"}],
        adsets=[{"id": "901", "status": "ACTIVE"}, {"id": "778", "status": "PAUSED"}],
        ads=[{"id": "779", "status": "ACTIVE"}])
    ads.reset()
    out = await sync.sync(store, s)
    assert out["kill"] == {"paused": ["900", "777", "901", "779"], "failed": [],
                           "list_error": None}
    assert _status_calls(ads) == [(i, "PAUSED") for i in ("900", "777", "901", "779")]
    paused = {e["meta_id"] for e in tests._entities(store, tid) if e["status"] == "PAUSED"}
    assert {"900", "901"} <= paused
    assert _audit(store)[-1] == "kill_enforced" and not out["errors"]
    assert not _alerts(store, utcnow())


async def test_kill_still_pauses_the_ledger_when_listing_or_a_pause_fails(store, ads):
    s = _settings()
    await _running(store, s)
    budget.kill(store)
    ads.list_fail.add("campaigns")
    ads.fail.add("900")
    ads.reset()
    out = await sync.sync(store, s)
    assert out["kill"]["paused"] == ["904"] and out["kill"]["failed"] == ["900"]
    assert "nope" in out["kill"]["list_error"]
    assert [i for i, _ in _status_calls(ads)] == ["900", "904"]
    a = _alerts(store, utcnow())["ads_pause_failed:kill"]
    assert a["severity"] == "error" and "900" in a["detail"]
    shown = await alerts.alerts(store, s, utcnow())
    assert "ads_pause_failed:kill" in {x["id"] for x in shown}


def test_sync_writes_only_pauses():
    """The @pauses source check covers sync.py (no unguarded write), and the sync never
    calls a writer method that creates or activates."""
    src = Path(sync.__file__).read_text(encoding="utf-8")
    assert spend_violations(src) == []
    calls = {n.func.attr for n in ast.walk(ast.parse(src))
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert "pause" in calls
    assert not calls & {"activate", "create_campaign", "create_ad_set", "create_creative",
                        "create_ad", "authorize_spend"}


# --- insights and reconcile -------------------------------------------------------------
async def test_snapshot_and_reconcile_deltas_without_double_count(store, ads):
    s = _settings()
    tid = await _running(store, s)
    auths = budget.open_authorizations(store, tid)
    before = budget.status(store, s)
    ads.insights.update(_spend("10.50", "9.00"))
    out = await sync.sync(store, s)
    assert out["tests"][tid] == {"spent": "19.50", "status": "too_early", "stop": None}
    assert _reported(store) == [(auths[0], "10.50"), (auths[1], "9.00")]
    res = store._get("ad_tests", tid)["result"]
    a = res["variants"]["A"]
    assert (a["impressions"], a["clicks"], a["results"], a["spend"], a["days"]) == (
        1000, 20, 800, "10.50", 1)
    assert a["adset_id"] == "901" and a["media_id"] == "111" and res["spent"] == "19.50"
    assert res["evaluation"]["variants"]["B"]["rate"] == 0.01
    # the guard counts max(authorized, reported): nothing more than before the sync
    after = budget.status(store, s)
    assert after["daily"] == before["daily"] and after["lifetime"] == before["lifetime"]
    assert after["tests"] == before["tests"] and after["lifetime"]["used"] == "427.00"
    ads.insights.update(_spend("12.00", "9.00"))
    await sync.sync(store, s)
    assert _reported(store)[2:] == [(auths[0], "1.50")]  # the increase only
    ads.insights.update(_spend("11.00", "9.00"))  # Meta revised down: the ledger keeps 12
    await sync.sync(store, s)
    assert len(_reported(store)) == 3
    query = [c.request for c in ads.calls if c.request.url.path == "/v25.0/901/insights"][0]
    since = json.loads(query.url.params["time_range"])
    assert since["since"] == since["until"]  # from the start to today


def test_reported_spend_counts_max_of_authorized_and_reported(store):
    s = _settings()
    a = budget.authorize_spend(store, s, "100", test_id=1, reason="ad set")
    used = lambda: budget.status(store, s)["lifetime"]["used"]  # noqa: E731
    budget.report_spend(store, s, a["id"], Decimal("30"))
    assert used() == "100"
    assert budget.report_spend(store, s, a["id"], Decimal("30"))["delta"] == "0"
    out = budget.report_spend(store, s, a["id"], Decimal("120"))
    assert out == {"reported": "120", "delta": "90", "authorized": "100", "over": True}
    assert used() == "120"
    budget.release(store, a["id"])  # released: what Meta spent still counts
    assert used() == "120"
    with pytest.raises(KeyError):
        budget.report_spend(store, s, 999, Decimal(1))


async def test_over_spend_alerts_kills_and_pauses(store, ads):
    s = _settings()
    tid = await _running(store, s)
    ads.insights.update(_spend("250.00", "9.00"))
    ads.reset()
    out = await sync.sync(store, s)
    assert budget.is_killed(store)
    assert out["kill"]["paused"] == ["900", "904"]  # the ledger's campaigns
    assert ("900", "PAUSED") in _status_calls(ads)
    auth = budget.open_authorizations(store, tid)[0]
    a = _alerts(store, utcnow())[f"ads_overspend:{auth}"]
    assert "250.00" in a["detail"] and a["severity"] == "error"
    assert budget.status(store, s)["lifetime"]["used"] == "463.50"  # 250 + 213.50
    log = budget.audit_log(store)["rows"]
    kill = next(r for r in log if r["action"] == "kill")
    assert kill["actor"] == "system" and "250.00" in kill["detail"]["reason"]


# --- review status ----------------------------------------------------------------------
async def test_review_issues_stored_and_alerted_once(store, ads):
    s = _settings()
    tid = await _running(store, s)
    ads.objects["ads"] = [
        {"id": "903", "status": "ACTIVE", "effective_status": "DISAPPROVED",
         "ad_review_feedback": {"global": {"Unacceptable business practices": "Rejected"}}},
        {"id": "907", "status": "ACTIVE", "effective_status": "WITH_ISSUES",
         "issues_info": [{"error_summary": "Video too long", "level": "AD"}]},
        {"id": "999", "status": "ACTIVE", "effective_status": "DISAPPROVED"},  # not ours
        {"id": "998", "status": "ACTIVE", "effective_status": "ACTIVE"}]
    now = utcnow()
    await sync.sync(store, s, now)
    review = store._get("ad_tests", tid)["result"]["review"]
    assert review == [
        {"ad_id": "903", "media_id": "111", "effective_status": "DISAPPROVED",
         "reason": "Unacceptable business practices: Rejected"},
        {"ad_id": "907", "media_id": "222", "effective_status": "WITH_ISSUES",
         "reason": "Video too long"}]
    found = _alerts(store, now)
    assert set(found) == {"ads_review:903", "ads_review:907"}
    assert found["ads_review:903"]["severity"] == "error"
    assert found["ads_review:907"]["title"] == f"Meta limits an ad of test {tid}"
    await sync.sync(store, s, now + timedelta(hours=1))
    assert _alerts(store, now)["ads_review:903"]["since"] == found["ads_review:903"]["since"]


# --- stop rules -------------------------------------------------------------------------
@pytest.mark.parametrize("stop, days, rows", [
    ("winner", 7, {"901": {"impressions": "50000", "clicks": "1000", "spend": "100"},
                   "905": {"impressions": "50000", "clicks": "500", "spend": "100"}}),
    ("cap_reached", 1, _spend("213.50", "213.50")),
    ("end_date", 7, _spend("50", "40")),
])
async def test_stop_rules_pause_finish_and_release(store, ads, stop, days, rows):
    s = _settings()
    tid = await _running(store, s)
    ads.insights.update(rows)
    ads.reset()
    out = await sync.sync(store, s, utcnow() + days * DAY)
    assert out["tests"][tid]["stop"] == stop
    t = store._get("ad_tests", tid)
    assert t["status"] == "finished" and t["reason"] == stop and t["finished_at"]
    assert t["result"]["evaluation"]["winner"] == ("A" if stop == "winner" else None)
    assert {i for i, st in _status_calls(ads) if st == "PAUSED"} == ENTITIES
    assert {e["status"] for e in tests._entities(store, tid)} == {"PAUSED"}
    assert budget.open_authorizations(store, tid) == []
    spent = sum(Decimal(r["spend"]) for r in rows.values())
    assert Decimal(budget.status(store, s)["lifetime"]["used"]) == spent
    finish = budget.audit_log(store)["rows"][0]
    assert finish["action"] == "finish" and finish["detail"]["stop"] == stop


async def test_stop_pause_failure_keeps_the_test_running_and_reserved(store, ads):
    s = _settings()
    tid = await _running(store, s)
    ads.insights.update(_spend("50", "40"))
    ads.fail.add("904")
    out = await sync.sync(store, s, utcnow() + 7 * DAY)
    assert out["tests"][tid]["pause_failed"] == ["904"]
    assert store._get("ad_tests", tid)["status"] == "running"
    assert len(budget.open_authorizations(store, tid)) == 2
    assert f"ads_pause_failed:{tid}" in _alerts(store, utcnow() + 7 * DAY)


async def test_finished_test_reconciles_late_spend_then_is_left_alone(store, ads):
    s = _settings()
    await _running(store, s)
    ads.insights.update(_spend("50", "40"))
    t0 = utcnow() + 7 * DAY
    await sync.sync(store, s, t0)
    ads.insights.update(_spend("55", "40"))  # Meta reports late
    await sync.sync(store, s, t0 + DAY)
    assert budget.status(store, s)["lifetime"]["used"] == "95"
    ads.reset()
    out = await sync.sync(store, s, t0 + sync.LATE_SPEND + DAY)
    assert out["tests"] == {} and not [c for c in ads.calls if "insights" in str(c.request.url)]


async def test_cancelled_running_test_reconciles_then_releases(store, ads):
    s = _settings()
    tid = await _running(store, s)
    await tests.cancel(store, s, tid)
    ads.insights.update(_spend("30", "20"))
    await sync.sync(store, s)
    assert budget.open_authorizations(store, tid) == []
    assert budget.status(store, s)["lifetime"]["used"] == "50"
    assert _audit(store)[-1] == "release"


# --- near a cap -------------------------------------------------------------------------
async def test_near_cap_alert_once_per_scope_per_day(store, ads):
    s = _settings(ads_daily_cap="70")  # the test's spread: 61 a day
    await _running(store, s)
    now = utcnow()
    assert (await sync.sync(store, s, now))["near_cap"] == ["daily"]
    day = budget.status(store, s, now)["day"]
    found = _alerts(store, now)
    assert list(found) == [f"ads_near_cap:daily:{day}"]
    assert "61.00 of 70" in found[f"ads_near_cap:daily:{day}"]["detail"]
    alerts.dismiss(store, f"ads_near_cap:daily:{day}", now)
    await sync.sync(store, s, now + timedelta(minutes=5))
    assert len(_alerts(store, now)) == 1  # same day: no second alert, the dismissal holds
    assert f"ads_near_cap:daily:{day}" not in {a["id"] for a in await alerts.alerts(store, s, now)}
    await sync.sync(store, s, now + DAY)
    assert len(_alerts(store, now + DAY)) == 2  # a new day: a new alert


# --- API --------------------------------------------------------------------------------
async def test_api_results(ads):
    s = _settings()
    store = CampaignStore(":memory:")
    tid = await _running(store, s)
    ads.insights.update(_spend("10.50", "9.00"))
    ads.objects["ads"] = [{"id": "903", "effective_status": "DISAPPROVED"}]
    await sync.sync(store, s)
    with TestClient(create_app(s, auth=Auth(s), store=store),
                    base_url="http://127.0.0.1") as tc:
        r = tc.get(f"/api/ads/tests/{tid}").json()
        assert tc.get("/api/ads/tests/999").json() == {"error": "not_found"}
    store.close()
    res = r["result"]
    assert set(res["variants"]) == {"A", "B"} and res["days"] == 1
    ev = res["evaluation"]
    assert ev["status"] == "too_early" and {"winner", "p_values", "lift"} <= set(ev)
    assert ev["variants"]["A"]["rate"] == 0.02
    assert res["review"][0]["reason"] == "DISAPPROVED"
    assert (r["min_days"], r["max_days"]) == (7, 30)
    assert r["spend"] == {"reported": "19.50", "counted": "427.00", "budget": "427.00",
                          "currency": "EUR"}
    assert r["near_cap"] == {"daily": False, "lifetime": False, "test": False}
    assert len(r["entities"]) == 6 and r["status"] == "running"


# --- worker -----------------------------------------------------------------------------
async def test_worker_runs_ads_sync_daily_or_hourly_when_busy(store, monkeypatch):
    calls = []

    async def fake_sync(store, settings, now):
        calls.append(now)
        return {}

    monkeypatch.setattr(sync, "sync", fake_sync)
    t0, hour = utcnow(), timedelta(hours=1)
    assert sync.period(store) == sync.DAILY
    off = _settings(meta_ad_account_id=None)
    await worker.data_jobs(FakeClient(), store, off, now=lambda: t0)
    assert calls == []  # ads not set up
    s = _settings()
    for t in (t0, t0 + hour):
        await worker.data_jobs(FakeClient(), store, s, now=lambda t=t: t)
    assert calls == [t0]  # idle: daily
    budget.kill(store)
    assert sync.period(store) == sync.HOURLY
    await worker.data_jobs(FakeClient(), store, s, now=lambda: t0 + 2 * hour)
    assert calls == [t0, t0 + 2 * hour]
