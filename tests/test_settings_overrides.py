"""Step 124: owner-editable settings stored over .env, seen by every process, guarded."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from src import instagram_mcp_server as srv
from src import settings_overrides as ov
from src.ads import budget
from src.ads.budget import BudgetRefused, authorize_spend
from src.api.app import create_app
from src.api.auth import Auth
from src.config import InstagramMCPSettings
from src.store import CampaignStore

PASSWORD = "correct horse"


def _settings(**kw):
    kw = {"ads_daily_cap": "10", "ads_test_cap": "50", "ads_lifetime_cap": "100", **kw}
    return InstagramMCPSettings(_env_file=None, database_path=":memory:", **kw)


def _field(view, name):
    return next(f for f in view["fields"] if f["name"] == name)


def test_secrets_are_never_editable():
    fields = InstagramMCPSettings.model_fields
    for name in ov.EDITABLE:
        assert SecretStr not in (fields[name].annotation, *getattr(fields[name].annotation,
                                                                   "__args__", ()))
        assert not any(w in name for w in ("token", "password", "secret", "key", "auth"))
    for secret in ("instagram_access_token", "ui_password", "facebook_app_secret"):
        with pytest.raises(ov.SettingsInvalid, match="not editable"):
            ov.update(CampaignStore(":memory:"), _settings(), {secret: "x"})


def test_override_applied_and_validated(store):
    s = _settings()
    out = ov.update(store, s, {"ads_daily_cap": "5", "ads_currency": " usd ",
                               "meta_ad_account_id": "act_123"}, confirmed=True)
    assert (s.ads_daily_cap, s.ads_currency, s.meta_ad_account_id) == (Decimal(5), "USD", "123")
    daily = _field(out, "ads_daily_cap")
    assert daily | {"description": None} == {
        "name": "ads_daily_cap", "section": "ads", "value": "5", "default": "10",
        "overridden": True, "type": "money", "ge": 0, "description": None}
    assert _field(out, "ads_objective")["choices"] == ["OUTCOME_AWARENESS", "OUTCOME_ENGAGEMENT"]
    assert _field(out, "ads_test_days") | {"description": None} == {
        "name": "ads_test_days", "section": "ads", "value": 7, "default": 7,
        "overridden": False, "type": "int", "ge": 1, "le": 30, "description": None}
    version = store.get_state(ov.KEY)
    for bad, message in (({"ads_currency": "euro"}, "ISO 4217"),
                         ({"meta_page_id": "abc"}, "must be digits"),
                         ({"ads_daily_cap": "-1"}, "greater than or equal to 0"),
                         ({"ads_daily_cap": "500"}, "must not be above ADS_LIFETIME_CAP"),
                         ({"ads_objective": "SALES"}, "OUTCOME_AWARENESS")):
        with pytest.raises(ov.SettingsInvalid, match=message):
            ov.update(store, s, bad)
    assert store.get_state(ov.KEY) == version  # nothing stored
    assert s.ads_daily_cap == Decimal(5)


def test_reset_to_default(store):
    s = _settings()
    ov.update(store, s, {"ads_daily_cap": "5", "ads_objective": "OUTCOME_ENGAGEMENT"})
    out = ov.update(store, s, {}, reset=["ads_daily_cap"], confirmed=True)
    assert s.ads_daily_cap == Decimal(10) and s.ads_objective == "OUTCOME_ENGAGEMENT"
    assert not _field(out, "ads_daily_cap")["overridden"]
    assert set(store.get_state(ov.KEY)["values"]) == {"ads_objective"}


def test_another_process_sees_the_change(tmp_path):
    db = str(tmp_path / "studio.db")
    api_store, worker_store = CampaignStore(db), CampaignStore(db)
    try:
        api, worker = _settings(), _settings()
        ov.update(api_store, api, {"ads_lifetime_cap": "80", "ads_test_days": 9})
        assert worker.ads_lifetime_cap == Decimal(100)  # nothing read yet
        assert ov.refresh(worker_store, worker) is worker
        assert (worker.ads_lifetime_cap, worker.ads_test_days) == (Decimal(80), 9)
        ov.update(api_store, api, {}, reset=["ads_lifetime_cap"], confirmed=True)
        ov.refresh(worker_store, worker)
        assert worker.ads_lifetime_cap == Decimal(100)
    finally:
        api_store.close()
        worker_store.close()


async def test_worker_loop_and_mcp_refresh(store, monkeypatch):
    import asyncio

    worker, mcp, api = _settings(), _settings(), _settings()
    ov.update(store, api, {"ads_test_days": 12})
    task = asyncio.create_task(ov.refresh_loop(store, worker, every=0.01))
    await asyncio.sleep(0.05)
    task.cancel()
    assert worker.ads_test_days == 12
    monkeypatch.setattr(srv, "store", lambda: store)
    monkeypatch.setattr(srv.config, "get_settings", lambda: mcp)
    assert srv.get_settings().ads_test_days == 12


def test_authorize_spend_uses_new_caps_at_once(store):
    stale, api = _settings(), _settings()
    ov.update(store, api, {"ads_daily_cap": "2"})
    with pytest.raises(BudgetRefused) as e:
        authorize_spend(store, stale, "3", reason="t")
    assert e.value.code == "daily_cap"
    ov.update(store, api, {"ads_daily_cap": "20"}, confirmed=True)
    assert authorize_spend(store, stale, "15", reason="t")["amount"] == "15"


def test_raising_a_cap_needs_confirmation(store):
    s = _settings()
    with pytest.raises(ov.PasswordNeeded):
        ov.update(store, s, {"ads_test_cap": "60"})
    with pytest.raises(ov.PasswordNeeded):  # same caps, other money: they mean more
        ov.update(store, s, {"ads_currency": "USD"})
    ov.update(store, s, {"ads_test_cap": "30", "ads_dsa_payor": "Macrobody"})  # lower: fine
    with pytest.raises(ov.PasswordNeeded):  # reset to the higher .env value
        ov.update(store, s, {}, reset=["ads_test_cap"])
    assert s.ads_test_cap == Decimal(30)
    ov.update(store, s, {}, reset=["ads_test_cap"], confirmed=True)
    assert s.ads_test_cap == Decimal(50)


def test_money_changes_are_audited(store):
    s = _settings()
    ov.update(store, s, {"ads_daily_cap": "4", "ads_dsa_payor": "Macrobody"})
    ov.update(store, s, {"ads_daily_cap": "4"})  # no change: no row
    rows = budget.audit_log(store)["rows"]
    assert [(r["actor"], r["action"], r["detail"]) for r in rows] == [
        ("owner", "settings", {"changes": {"ads_daily_cap": ["10", "4"],
                                           "ads_dsa_payor": [None, "Macrobody"]}})]


# --- Ad presets (127) -----------------------------------------------------------------
def _presets(n=1, **kw):
    return [{"id": f"p{i}", "label": "France", "countries": ["FR"], "placements": ["reels"],
             **kw} for i in range(n)]


def test_ad_presets_validated(store):
    s = _settings()
    for bad, message in ((_presets(countries=["FRA"]), "ads_presets.0.countries.*'FRA'"),
                         (_presets(countries=[]), "at least 1 item"),
                         (_presets(age_min=40, age_max=30), "oldest age"),
                         (_presets(age_min=17), "greater than or equal to 18"),
                         (_presets(placements=[]), "ads_presets.0.placements"),
                         (_presets(placements=["feed"]), "'reels'"),
                         (_presets(2, id="same"), "two presets have the id 'same'"),
                         (_presets(id="Not a slug"), "ads_presets.0.id"),
                         (_presets(11), "at most 10"),
                         ([], "at least 1 item")):
        with pytest.raises(ov.SettingsInvalid, match=message) as e:
            ov.update(store, s, {"ads_presets": bad})
        assert e.value.field == "ads_presets"
    assert store.get_state(ov.KEY) is None  # nothing stored
    assert [p.id for p in s.ads_presets] == ["fr_reels", "fr_feed_reels", "francophone_reels"]


def test_ad_presets_edit_reset_and_audit(store):
    s = _settings()
    out = ov.update(store, s, {"ads_presets": _presets(countries="be, fr, BE")})  # no password
    field = _field(out, "ads_presets")
    assert field["type"] == "presets" and field["overridden"] and len(field["default"]) == 3
    assert field["value"] == [{"id": "p0", "label": "France", "countries": ["BE", "FR"],
                               "age_min": 18, "age_max": None, "placements": ["reels"]}]
    (row,) = budget.audit_log(store)["rows"]
    assert row["action"] == "settings" and row["actor"] == "owner"
    old, new = row["detail"]["changes"]["ads_presets"]
    assert [p["id"] for p in old] == ["fr_reels", "fr_feed_reels", "francophone_reels"]
    assert new == field["value"]
    out = ov.update(store, s, {}, reset=["ads_presets"])
    assert not _field(out, "ads_presets")["overridden"] and len(s.ads_presets) == 3


# --- Studio (125) ----------------------------------------------------------------------
STUDIO = {"batch_size": 25, "max_posts_per_day": 2, "explore_share": 0.2, "humour_share": 0.7}


def test_studio_fields_editable_validated_no_password(store):
    s = _settings()
    out = ov.update(store, s, STUDIO)  # never PasswordNeeded, never audited
    assert {k: _field(out, k)["value"] for k in STUDIO} == STUDIO
    assert {_field(out, k)["section"] for k in STUDIO} == {"studio"}
    assert _field(out, "humour_share") | {"description": None} == {
        "name": "humour_share", "section": "studio", "value": 0.7, "default": 0.5,
        "overridden": True, "type": "float", "ge": 0, "le": 1, "description": None}
    assert budget.audit_log(store)["rows"] == []
    assert (_field(out, "batch_size")["le"], _field(out, "max_posts_per_day")["le"]) == (50, 25)
    for bad in ({"batch_size": -1}, {"batch_size": 51}, {"max_posts_per_day": 0},
                {"max_posts_per_day": 26}, {"explore_share": 1.5}, {"humour_share": -0.1}):
        with pytest.raises(ov.SettingsInvalid, match=next(iter(bad))):
            ov.update(store, s, bad)
    assert s.batch_size == 25


def test_studio_readers_see_the_change(store):
    from datetime import date, datetime, timezone

    from src.learning import brief, slots

    stale, api = _settings(), _settings()  # e.g. the MCP server and the website
    now = datetime(2026, 11, 18, 6, tzinfo=timezone.utc)
    day = date(2026, 11, 19)
    ov.update(store, api, STUDIO)
    ov.refresh(store, stale)
    quotas = brief.creative_brief(store, stale, now)["quotas"]
    assert (quotas["batch_size"], quotas["limits"]["explore"]) == (25, 5)
    # no verdicts yet: the owner's share (the learned split is ~50/50, Thompson draws)
    assert abs(quotas["humour_target"] - 25 * 0.7) <= 1
    planned = slots.plan_slots_from_settings(stale, day, 5, [], now=now)
    assert len(planned) == 2


# --- API -------------------------------------------------------------------------------
@pytest.fixture
def tc():
    s = _settings(ui_password=PASSWORD, instagram_access_token=None)
    store = CampaignStore(":memory:")
    with TestClient(create_app(s, auth=Auth(s), store=store), base_url="http://127.0.0.1") as c:
        c.headers["Origin"] = "http://127.0.0.1"
        assert c.post("/api/login", json={"password": PASSWORD}).status_code == 200
        yield c
    store.close()


def test_api_get_patch_reset(tc):
    fields = tc.get("/api/settings").json()["fields"]
    assert {f["name"] for f in fields} == set(ov.EDITABLE)
    r = tc.patch("/api/settings", json={"values": {"ads_daily_cap": "3"}})
    assert r.status_code == 200 and _field(r.json(), "ads_daily_cap")["value"] == "3"
    assert tc.get("/api/ads/budget").json()["daily"]["cap"] == "3"
    r = tc.patch("/api/settings", json={"values": {"ads_currency": "euro"}})
    assert r.status_code == 422 and r.json()["field"] == "ads_currency"
    assert "ISO 4217" in r.json()["message"]
    r = tc.patch("/api/settings", json={"values": {"ui_password": "x"}})
    assert r.status_code == 422
    tc.patch("/api/settings", json={"values": {"ads_objective": "OUTCOME_ENGAGEMENT"}})
    r = tc.patch("/api/settings", json={"reset": ["ads_objective"]})
    assert _field(r.json(), "ads_objective")["value"] == "OUTCOME_AWARENESS"
    assert not _field(r.json(), "ads_objective")["overridden"]
    r = tc.patch("/api/settings", json={"reset": ["ads_daily_cap"]})  # 3 -> 10 rises
    assert r.json() == {"error": "password_required"}


def test_api_raising_a_cap_asks_the_password(tc):
    body = {"values": {"ads_lifetime_cap": "200"}}
    assert tc.patch("/api/settings", json=body).json() == {"error": "password_required"}
    r = tc.patch("/api/settings", json={**body, "password": "wrong"})
    assert (r.status_code, r.json()) == (403, {"error": "bad_password"})
    assert _field(tc.get("/api/settings").json(), "ads_lifetime_cap")["value"] == "100"
    r = tc.patch("/api/settings", json={**body, "password": PASSWORD})
    assert _field(r.json(), "ads_lifetime_cap")["value"] == "200"
    r = tc.patch("/api/settings", json={"values": {"ads_lifetime_cap": "150"}})  # lower
    assert r.status_code == 200


def test_api_studio_settings_need_no_password(tc):
    r = tc.patch("/api/settings", json={"values": {"batch_size": 25, "humour_share": 0.6}})
    assert r.status_code == 200 and _field(r.json(), "batch_size")["value"] == 25
    for name, bad in (("explore_share", 2), ("batch_size", 1000), ("max_posts_per_day", 26)):
        r = tc.patch("/api/settings", json={"values": {name: bad}})
        assert r.status_code == 422 and r.json()["field"] == name
    assert _field(tc.get("/api/settings").json(), "max_posts_per_day")["value"] == 3
    r = tc.patch("/api/settings", json={"reset": ["batch_size"]})
    assert _field(r.json(), "batch_size") | {"value": 10, "overridden": False} ==         _field(r.json(), "batch_size")
