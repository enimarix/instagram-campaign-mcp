"""Step 092: paused promotions of an existing post. The full chain, every refusal path
(before any request), a mid-chain failure, "never ACTIVE" and the guard's new options."""

import ast
import inspect
import json
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest
import respx

from src.ads import budget, writer
from src.ads.budget import BudgetRefused, authorize_spend
from src.ads.promote import PromotionFailed, PromotionRefused, create_paused_promotion
from src.config import InstagramMCPSettings

from .conftest import API

ACT = f"{API}/act_42"
TZ = ZoneInfo("Europe/Paris")
EDGES = ("campaigns", "adsets", "adcreatives", "ads")


def _settings(**kw):
    kw = {"instagram_access_token": "test_token", "instagram_business_account_id": "1789",
          "meta_ad_account_id": "42", "meta_page_id": "55", "ads_dsa_beneficiary": "Macrobody",
          "ads_dsa_payor": "Owner Name", "ads_daily_cap": "10", "ads_test_cap": "100",
          "ads_lifetime_cap": "100", "timezone": "Europe/Paris", "cache_enabled": False, **kw}
    return InstagramMCPSettings(_env_file=None, database_path=":memory:", **kw)


def _today():
    return datetime.now(TZ).date()


def _post(store, media_id="m1", **source):
    """A published studio post; `source` fields make it a sourced (non-motion) idea."""
    if source:
        idea = store.add_idea("remix", source_id=store.add_source("x", **source)["id"])
    else:
        idea = store.add_idea("motion")  # sourceless motion = own
    asset = store.add_asset(idea["id"])
    store.label_post(media_id, asset_id=asset["id"])
    return asset


@pytest.fixture
def meta():
    """POST routes for the four edges, each answering a new id; the test asserts no GET."""
    with respx.mock(assert_all_called=False) as router:
        for i, edge in enumerate(EDGES):
            router.post(f"{ACT}/{edge}").respond(json={"id": str(900 + i)})
        yield router


def _bodies(router):
    return {c.request.url.path.rsplit("/", 1)[-1]: json.loads(c.request.content)
            for c in router.calls}


def _used(store, s):
    return budget.status(store, s)


async def test_full_paused_chain(store, meta):
    s = _settings()
    asset = _post(store)
    end = _today() + timedelta(days=6)  # 7 owner-local days
    out = await create_paused_promotion(store, s, "m1", preset="fr_reels", budget="70",
                                        end_date=end, http_client=httpx.AsyncClient())
    b = _bodies(meta)
    assert list(b) == list(EDGES)
    assert all(c.request.method == "POST" for c in meta.calls)
    assert all(c.request.headers["Authorization"] == "Bearer test_token" for c in meta.calls)
    camp, adset, creative, ad = (b[e] for e in EDGES)
    assert camp == {"name": f"studio m1 {_today()}", "objective": "OUTCOME_AWARENESS",
                    "special_ad_categories": [], "spend_cap": 10000,  # raised to Meta's 100
                    "is_adset_budget_sharing_enabled": False, "status": "PAUSED"}
    end_time = datetime(end.year, end.month, end.day, 23, 59, 59, tzinfo=TZ)
    assert adset == {
        "name": camp["name"], "campaign_id": "900", "lifetime_budget": 7000,
        "end_time": int(end_time.timestamp()), "billing_event": "IMPRESSIONS",
        "optimization_goal": "REACH", "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
        "targeting": {"publisher_platforms": ["instagram"], "age_min": 18,
                      "targeting_automation": {"advantage_audience": 0},
                      "geo_locations": {"countries": ["FR"]}, "instagram_positions": ["reels"]},
        "dsa_beneficiary": "Macrobody", "dsa_payor": "Owner Name", "status": "PAUSED"}
    assert creative == {"name": camp["name"], "object_id": "55", "instagram_user_id": "1789",
                        "source_instagram_media_id": "m1"}
    assert ad == {"name": camp["name"], "adset_id": "901", "creative": {"creative_id": "902"},
                  "status": "PAUSED"}

    rows = [out[k] for k in ("campaign", "adset", "creative", "ad")]
    assert [(r["kind"], r["meta_id"], r["status"]) for r in rows] == [
        ("campaign", "900", "PAUSED"), ("adset", "901", "PAUSED"),
        ("creative", "902", "PAUSED"), ("ad", "903", "PAUSED")]
    assert [r["parent_id"] for r in rows] == [None, rows[0]["id"], rows[1]["id"], rows[1]["id"]]
    assert all(r["asset_id"] == asset["id"] and r["media_id"] == "m1" for r in rows)
    assert rows[0]["spend_cap"] == "100" and rows[1]["lifetime_budget"] == "70"
    assert rows[1]["end_time"] == end_time.isoformat()
    # One reservation: 70 lifetime, 10 a day for 7 days (fits a daily cap of 10).
    st = _used(store, s)
    assert st["lifetime"]["used"] == "70" and st["daily"]["used"] == "10.00"
    with store.immediate() as c:
        led = dict(c.execute("SELECT * FROM ad_spend_ledger").fetchone())
    assert led["id"] == out["authorization_id"] and led["ad_entity_id"] == "900"
    assert (led["amount"], led["daily_amount"], led["daily_until"]) == ("70", "10.00",
                                                                        end.isoformat())


async def test_engagement_objective_and_big_budget_spend_cap(store, meta):
    s = _settings(ads_objective="OUTCOME_ENGAGEMENT", ads_daily_cap="200",
                  ads_lifetime_cap="500", ads_test_cap="500")
    _post(store)
    await create_paused_promotion(store, s, "m1", preset="fr_feed_reels", budget="150.50",
                                  end_date=_today() + timedelta(days=1),
                                  http_client=httpx.AsyncClient())
    b = _bodies(meta)
    assert b["campaigns"]["objective"] == "OUTCOME_ENGAGEMENT"
    assert b["campaigns"]["spend_cap"] == 15050 and b["adsets"]["lifetime_budget"] == 15050
    assert (b["adsets"]["optimization_goal"], b["adsets"]["destination_type"]) == (
        "THRUPLAY", "ON_VIDEO")


@pytest.mark.parametrize("source,why", [
    ({"rights_basis": "commentary", "author": "a"}, "commentary"),
    ({"rights_basis": "cc", "author": "a"}, "cc"),
    ({"rights_basis": "licensed"}, "ads not allowed"),
    ({"rights_basis": "unknown"}, "unknown"),
])
async def test_rights_refusal_before_any_request(store, meta, source, why):
    _post(store, **source)
    with pytest.raises(PromotionRefused) as e:
        await create_paused_promotion(store, _settings(), "m1", preset="fr_reels", budget=5,
                                      end_date=_today() + timedelta(days=2))
    assert e.value.code == "rights" and why in e.value.message
    assert not meta.calls


async def test_licensed_with_ads_allowed_passes(store, meta):
    asset = _post(store, rights_basis="licensed")
    with store.immediate() as c:  # set by the permission tracker / stock provider
        c.execute("UPDATE sources SET ads_allowed=1 WHERE id=(SELECT source_id FROM ideas"
                  " WHERE id=?)", (asset["idea_id"],))
    out = await create_paused_promotion(store, _settings(), "m1", preset="fr_reels", budget=5,
                                        end_date=_today() + timedelta(days=2),
                                        http_client=httpx.AsyncClient())
    assert out["ad"]["meta_id"] == "903"


@pytest.mark.parametrize("kw,code", [
    ({"media_id": "not-ours"}, "not_ours"),
    ({"preset": "nope"}, "invalid"),
    ({"budget": 5.0}, "invalid"),
    ({"budget": "0"}, "invalid"),
    ({"budget": "5.001"}, "invalid"),
    ({"end_date": "today"}, "invalid"),
    ({"days": 0}, "invalid"),
    ({"settings": {"ads_dsa_payor": None}}, "not_configured"),
    ({"settings": {"meta_page_id": None}}, "not_configured"),
    ({"settings": {"meta_ad_account_id": None}}, "not_configured"),
    ({"settings": {"instagram_access_token": "your_long_lived_access_token"}}, "not_configured"),
])
async def test_refusals_before_any_request(store, meta, kw, code):
    _post(store)
    args = {"media_id": "m1", "preset": "fr_reels", "budget": 5,
            "end_date": _today() + timedelta(days=kw.pop("days", 2))}
    s = _settings(**kw.pop("settings", {}))
    args.update(kw)
    with pytest.raises(PromotionRefused) as e:
        await create_paused_promotion(store, s, args.pop("media_id"), **args)
    assert e.value.code == code, e.value.message
    assert not meta.calls


@pytest.mark.parametrize("settings_kw,budget_,code", [
    ({}, "71", "daily_cap"),  # 71 over 7 days = 10.15 a day > 10
    ({"ads_lifetime_cap": "60"}, "70", "lifetime_cap"),
    ({"ads_test_cap": "50"}, "70", "test_cap"),
    ({"ads_daily_cap": "0", "ads_test_cap": "0", "ads_lifetime_cap": "0"}, "1", "daily_cap"),
])
async def test_cap_refusal_before_any_request(store, meta, settings_kw, budget_, code):
    _post(store)
    with pytest.raises(BudgetRefused) as e:
        await create_paused_promotion(store, _settings(**settings_kw), "m1", preset="fr_reels",
                                      budget=budget_, end_date=_today() + timedelta(days=6))
    assert e.value.code == code, e.value.message
    assert not meta.calls


async def test_killed_refuses_before_any_request(store, meta):
    _post(store)
    budget.kill(store, "stop")
    with pytest.raises(BudgetRefused) as e:
        await create_paused_promotion(store, _settings(), "m1", preset="fr_reels", budget=5,
                                      end_date=_today() + timedelta(days=2))
    assert e.value.code == "killed" and not meta.calls


@pytest.mark.parametrize("failing,created", [
    ("adsets", ["campaign 900"]),
    ("adcreatives", ["campaign 900", "adset 901"]),
    ("ads", ["campaign 900", "adset 901", "creative 902"]),
])
async def test_mid_chain_failure_releases_and_records(store, meta, failing, created):
    s = _settings()
    _post(store)
    meta.post(f"{ACT}/{failing}").respond(400, json={"error": {"message": "Invalid parameter",
                                                                "code": 100}})
    with pytest.raises(PromotionFailed) as e:
        await create_paused_promotion(store, s, "m1", preset="fr_reels", budget=20,
                                      end_date=_today() + timedelta(days=3),
                                      http_client=httpx.AsyncClient())
    assert [f"{r['kind']} {r['meta_id']}" for r in e.value.created] == created
    assert ", ".join(created) in str(e.value) and "Invalid parameter" in str(e.value)
    with store.immediate() as c:
        rows = [dict(r) for r in c.execute("SELECT kind, meta_id, status FROM ad_entities")]
    assert [f"{r['kind']} {r['meta_id']}" for r in rows] == created
    assert {r["status"] for r in rows} == {"PAUSED"}
    st = _used(store, s)  # the reservation is released
    assert st["lifetime"]["used"] == "0" and st["daily"]["used"] == "0"


async def test_killed_mid_chain(store, meta, monkeypatch):
    """The kill switch flips after the campaign: the ad set is refused, the campaign stays
    recorded and nothing is reserved."""
    s = _settings()
    _post(store)
    real = writer.AdsWriter.create_campaign

    async def then_kill(self, *a, **kw):
        out = await real(self, *a, **kw)
        budget.kill(store)
        return out

    monkeypatch.setattr(writer.AdsWriter, "create_campaign", then_kill)
    with pytest.raises(PromotionFailed) as e:
        await create_paused_promotion(store, s, "m1", preset="fr_reels", budget=5,
                                      end_date=_today() + timedelta(days=2),
                                      http_client=httpx.AsyncClient())
    assert [r["kind"] for r in e.value.created] == ["campaign"]
    assert "kill switch" in str(e.value)
    assert [c.request.url.path.rsplit("/", 1)[-1] for c in meta.calls] == ["campaigns"]
    assert _used(store, s)["lifetime"]["used"] == "0"


# --- never ACTIVE ------------------------------------------------------------------------
async def test_every_post_body_is_paused(store, meta):
    _post(store)
    await create_paused_promotion(store, _settings(), "m1", preset="francophone_reels",
                                  budget=5, end_date=_today() + timedelta(days=2),
                                  http_client=httpx.AsyncClient())
    for edge, body in _bodies(meta).items():
        if edge == "adcreatives":  # a creative has no delivery status
            assert "status" not in body
        else:
            assert body["status"] == "PAUSED"


def test_no_code_path_sends_another_status():
    """No src/ads string is another delivery status, ACTIVE only once as writer.ACTIVE
    (activate(), 094: tests/test_ads_tests.py checks who reaches it), no writer method
    takes a status, and _paused() wins over any status in the body it is given."""
    for f in Path(writer.__file__).parent.rglob("*.py"):
        consts = [n.value for n in ast.walk(ast.parse(f.read_text(encoding="utf-8")))
                  if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        found = [c for c in consts if c in {"ACTIVE", "ARCHIVED", "DELETED", "IN_PROCESS"}]
        assert found == (["ACTIVE"] if f.name == "writer.py" else []), f.name
    for name, fn in inspect.getmembers(writer.AdsWriter, inspect.iscoroutinefunction):
        if name.startswith("create_"):
            assert getattr(fn, "__spends__", False), name
            assert not any("status" in p for p in inspect.signature(fn).parameters), name
    assert writer._paused({"status": "ACTIVE", "x": 1}) == {"status": "PAUSED", "x": 1}


def test_minor_units():
    assert writer.minor_units(Decimal("12.34")) == 1234
    with pytest.raises(ValueError):
        writer.minor_units(Decimal("0.001"))


# --- guard options (091 + 092) -----------------------------------------------------------
def test_check_only_reserves_nothing(store):
    s = _settings()
    assert authorize_spend(store, s, 0, reason="ad", check_only=True) is None
    assert authorize_spend(store, s, 10, reason="campaign", check_only=True) is None
    assert _used(store, s)["lifetime"]["used"] == "0"
    with pytest.raises(BudgetRefused) as e:
        authorize_spend(store, s, 11, reason="x", check_only=True)
    assert e.value.code == "daily_cap"
    with pytest.raises(BudgetRefused) as e:
        authorize_spend(store, s, 0, reason="ad")  # 0 only for check_only
    assert e.value.code == "invalid"
    budget.kill(store)
    with pytest.raises(BudgetRefused) as e:
        authorize_spend(store, s, 0, reason="ad", check_only=True)
    assert e.value.code == "killed"


def test_daily_spread_counts_each_day_of_the_span(store):
    s = _settings()
    t0 = datetime(2026, 11, 18, 12, tzinfo=ZoneInfo("UTC"))
    until = t0.date() + timedelta(days=2)
    authorize_spend(store, s, 24, daily_amount=8, daily_until=until, reason="ad set", now=t0)
    for day in range(3):  # 18th, 19th, 20th: 8 of 10 used
        st = budget.status(store, s, now=t0 + timedelta(days=day))
        assert st["daily"]["used"] == "8", day
    assert budget.status(store, s, now=t0 + timedelta(days=3))["daily"]["used"] == "0"
    with pytest.raises(BudgetRefused):
        authorize_spend(store, s, 3, reason="x", now=t0 + timedelta(days=1))
    authorize_spend(store, s, 2, reason="x", now=t0 + timedelta(days=1))


@pytest.mark.parametrize("kw", [
    {"daily_amount": 5}, {"daily_until": datetime(2026, 1, 1).date()},
    {"daily_amount": 11, "daily_until": datetime(2026, 1, 1).date()},
    {"daily_amount": 0, "daily_until": datetime(2026, 1, 1).date()},
    {"daily_amount": 5, "daily_until": datetime(2026, 1, 1)},
    {"daily_amount": 5, "daily_until": "2026-01-01"},
])
def test_daily_spread_arguments_checked(store, kw):
    with pytest.raises(BudgetRefused) as e:
        authorize_spend(store, _settings(), 10, reason="x", **kw)
    assert e.value.code == "invalid"
