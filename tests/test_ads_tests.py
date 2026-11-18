"""Step 094: propose, approve (the only ACTIVE write), cancel, the audit log and the API.
Every refusal path, a failure mid-creation and mid-activation, and "ACTIVE only via
approve" at source level."""

import ast
import itertools
import json
from pathlib import Path

import pytest
import respx
from fastapi.testclient import TestClient

from src.ads import budget, tests, writer
from src.ads.budget import BudgetRefused
from src.ads.tests import AdTestFailed, AdTestRefused
from src.api.app import create_app
from src.api.auth import Auth
from src.config import InstagramMCPSettings
from src.store import CampaignStore

from .conftest import API

ACT = f"{API}/act_42"
SRC = Path(tests.__file__).parents[1]
PASSWORD = "correct horse"
CREATIVE = [{"media_id": "111", "preset": "fr_reels"}, {"media_id": "222", "preset": "fr_reels"}]


def _settings(**kw):
    kw = {"instagram_access_token": "test_token", "instagram_business_account_id": "1789",
          "meta_ad_account_id": "42", "meta_page_id": "55", "ads_dsa_beneficiary": "Macrobody",
          "ads_dsa_payor": "Owner Name", "ads_daily_cap": "100", "ads_test_cap": "1000",
          "ads_lifetime_cap": "1000", "timezone": "Europe/Paris", "cache_enabled": False, **kw}
    return InstagramMCPSettings(_env_file=None, database_path=":memory:", **kw)


def _post(store, media_id, **source):
    idea = (store.add_idea("remix", source_id=store.add_source("x", **source)["id"])
            if source else store.add_idea("motion"))
    asset = store.add_asset(idea["id"])
    store.label_post(media_id, asset_id=asset["id"])
    return asset


@pytest.fixture
def meta():
    """Meta: creates answer new ids (router.new_id), activate/pause answer success
    (`fail`: object ids that answer an error), no insights, every post boostable unless
    in `unboostable`. Tests override routes as needed."""
    ids = itertools.count(900)
    with respx.mock(assert_all_called=False) as router:
        router.new_id = lambda req=None: respx.MockResponse(json={"id": str(next(ids))})
        router.fail, router.unboostable = set(), {}
        for edge in ("campaigns", "adsets", "adcreatives", "ads"):
            router.post(f"{ACT}/{edge}").mock(side_effect=router.new_id)
        router.get(f"{ACT}/insights").respond(json={"data": []})

        def boost(req):
            info = router.unboostable.get(req.url.path.rsplit("/", 1)[-1])
            return respx.MockResponse(json={"boost_eligibility_info": info or {
                "eligible_to_boost": True}})

        def status(req):
            if req.url.path.rsplit("/", 1)[-1] in router.fail:
                return respx.MockResponse(400, json={"error": {"message": "Ad rejected",
                                                               "code": 1}})
            return respx.MockResponse(json={"success": True})

        router.get(path__regex=r"^/v25\.0/\d+$").mock(side_effect=boost)
        router.post(path__regex=r"^/v25\.0/\d+$").mock(side_effect=status)
        yield router


def _status_calls(router):
    """(object id, status) of every activate / pause request, in order."""
    return [(c.request.url.path.rsplit("/", 1)[-1], json.loads(c.request.content)["status"])
            for c in router.calls if c.request.method == "POST"
            and not c.request.url.path.endswith(("campaigns", "adsets", "adcreatives", "ads"))]


def _posts(router):
    return [c for c in router.calls if c.request.method == "POST"]


def _audit(store):
    return [r["action"] for r in reversed(budget.audit_log(store, limit=200)["rows"])]


async def _propose(store, s, variants=CREATIVE, variable="creative", **kw):
    for v in variants:
        if not store.get_label(v["media_id"]):
            _post(store, v["media_id"])
    return await tests.propose(store, s, hypothesis="hook A beats hook B", variable=variable,
                               variants=variants, **kw)


# --- propose ---------------------------------------------------------------------------
async def test_propose_default_rates(store, meta):
    s = _settings()
    t = await _propose(store, s)
    assert t["status"] == "proposed" and t["proposed_by"] == "owner"
    assert t["variants"] == CREATIVE and t["currency"] == "EUR"
    assert t["spec"]["min_days"] == 7 and t["spec"]["min_sample"] == 42693
    assert t["needed"]["source"] == "default" and t["needed"]["cpm"] == 5.0
    assert t["needed"]["total"] == 426.94 and t["baseline_rate"] == 0.01
    assert t["summary"] == "To see a 20% lift you need about 426.94 EUR over 7 days"
    assert t["underpowered"] is None  # caps: test 1000, daily 100 x 7
    assert _audit(store) == ["propose"]


async def test_propose_uses_the_account_insights_and_flags_caps_too_low(store, meta):
    meta.get(f"{ACT}/insights").respond(json={"data": [
        {"impressions": "100000", "clicks": "2000", "spend": "300"}]})
    t = await _propose(store, _settings(ads_test_cap="50"))
    assert t["needed"]["source"] == "insights" and t["needed"]["cpm"] == 3.0
    assert t["baseline_rate"] == 0.02 and t["needed"]["cpc"] == 0.15
    assert t["underpowered"].startswith("the caps allow less than the test needs")


async def test_propose_audience_and_placement(store, meta):
    s = _settings()
    t = await _propose(store, s, variable="audience", variants=[
        {"media_id": "111", "preset": "fr_reels"},
        {"media_id": "111", "preset": "francophone_reels"}])
    assert t["variable"] == "audience"
    t = await _propose(store, s, variable="placement", variants=[
        {"media_id": "111", "preset": "fr_reels"}, {"media_id": "111", "preset": "fr_feed_reels"}])
    assert t["spec"]["variable"] == "placement"


@pytest.mark.parametrize("variable,variants", [
    ("creative", [{"media_id": "111", "preset": "fr_reels"},
                  {"media_id": "222", "preset": "fr_feed_reels"}]),  # two variables
    ("creative", [{"media_id": "111", "preset": "fr_reels"}] * 2),  # same post twice
    ("audience", [{"media_id": "111", "preset": "fr_reels"},
                  {"media_id": "111", "preset": "fr_feed_reels"}]),  # that is placement
    ("placement", [{"media_id": "111", "preset": "fr_reels"},
                   {"media_id": "111", "preset": "francophone_reels"}]),  # that is audience
    ("audience", [{"media_id": "111", "preset": "fr_feed_reels"},
                  {"media_id": "111", "preset": "francophone_reels"}]),  # both differ
    ("audience", [{"media_id": "111", "preset": "fr_reels"},
                  {"media_id": "222", "preset": "francophone_reels"}]),
    ("creative", CREATIVE[:1]),
    ("creative", [{"media_id": str(i), "preset": "fr_reels"} for i in range(1, 6)]),
    ("creative", [{"media_id": "111", "preset": "nope"}, CREATIVE[1]]),
    ("budget", CREATIVE),
])
async def test_propose_one_variable_only(store, meta, variable, variants):
    with pytest.raises(AdTestRefused) as e:
        await _propose(store, _settings(), variants=variants, variable=variable)
    assert e.value.code == "invalid", e.value.message
    assert not meta.calls


@pytest.mark.parametrize("source,code", [
    ({"rights_basis": "commentary", "author": "a"}, "rights"),
    ({"rights_basis": "unknown"}, "rights"),
    ({"rights_basis": "licensed"}, "rights"),
])
async def test_propose_refuses_assets_that_may_not_be_advertised(store, meta, source, code):
    _post(store, "111", **source)
    with pytest.raises(AdTestRefused) as e:
        await _propose(store, _settings())
    assert e.value.code == code and not meta.calls


async def test_propose_refuses_other_posts_and_unboostable(store, meta):
    with pytest.raises(AdTestRefused) as e:
        await tests.propose(store, _settings(), hypothesis="h", variable="creative",
                            variants=CREATIVE)
    assert e.value.code == "not_ours"
    meta.unboostable["222"] = {"eligible_to_boost": False,
                               "ineligible_reason": "copyrighted music"}
    with pytest.raises(AdTestRefused) as e:
        await _propose(store, _settings())
    assert e.value.code == "not_boostable" and "copyrighted music" in e.value.message
    assert tests.list_tests(store, _settings()) == []


def test_eligible_winners(store, monkeypatch):
    _post(store, "111")
    _post(store, "222", rights_basis="commentary", author="a")
    rows = [({"media_id": m, "permalink": f"p/{m}", "posted_at": "t", "caption": "c"},
             {"verdict": v, "group": g, "engagement_index": 2.0})
            for m, v, g in [("111", "winner", "REELS"), ("222", "winner", "REELS"),
                            ("333", "winner", "REELS"), ("111", "average", "REELS"),
                            ("111", "winner", "FEED")]]
    monkeypatch.setattr(tests, "scored_posts", lambda store, settings: rows)
    out = tests.eligible_winners(store, _settings())
    assert [w["media_id"] for w in out] == ["111"] and out[0]["engagement_index"] == 2.0


# --- approve ---------------------------------------------------------------------------
async def test_approve_creates_paused_then_activates(store, meta):
    s = _settings()
    t = await _propose(store, s)
    out = await tests.approve(store, s, t["id"], "427")
    assert out["status"] == "running" and out["budget_total"] == "427.00"
    assert out["approved_at"] and out["end_date"] and out["underpowered_ok"] == 0
    posts = _posts(meta)
    creates = [c for c in posts if c.request.url.path.startswith("/v25.0/act_42/")]
    assert len(creates) == 8 and posts[:8] == creates  # every create before any activation
    assert all(json.loads(c.request.content).get("status", "PAUSED") == "PAUSED"
               for c in creates)
    assert json.loads(creates[1].request.content)["lifetime_budget"] == 21350  # 427 / 2
    # ad -> ad set -> campaign, per variant
    assert _status_calls(meta) == [("903", "ACTIVE"), ("901", "ACTIVE"), ("900", "ACTIVE"),
                                   ("907", "ACTIVE"), ("905", "ACTIVE"), ("904", "ACTIVE")]
    ents = out["entities"]
    assert {e["status"] for e in ents} == {"ACTIVE"} and {e["test_id"] for e in ents} == {t["id"]}
    assert len(budget.open_authorizations(store, t["id"])) == 2
    assert budget.status(store, s)["tests"][0]["used"] == "427.00"
    assert _audit(store) == ["propose", "approve", "activate", "activate"]


async def test_approve_refuses_unless_proposed(store, meta):
    s = _settings()
    t = await _propose(store, s)
    await tests.cancel(store, s, t["id"])
    with pytest.raises(AdTestRefused) as e:
        await tests.approve(store, s, t["id"], "427")
    assert e.value.code == "status" and not _posts(meta)
    with pytest.raises(KeyError):
        await tests.approve(store, s, 999, "427")


async def test_approve_underpowered_needs_the_tick(store, meta):
    s = _settings()
    t = await _propose(store, s)
    with pytest.raises(AdTestRefused) as e:
        await tests.approve(store, s, t["id"], "100")
    assert e.value.code == "underpowered" and "426.94" in e.value.message
    assert not _posts(meta) and store._get("ad_tests", t["id"])["status"] == "proposed"
    out = await tests.approve(store, s, t["id"], "100", underpowered_ok=True)
    assert out["status"] == "running" and out["underpowered_ok"] == 1
    row = budget.audit_log(store)["rows"][-2]  # oldest first: propose, approve
    assert row["action"] == "approve" and "426.94" in row["detail"]["underpowered"]


@pytest.mark.parametrize("settings_kw,code", [
    ({"ads_test_cap": "400"}, "test_cap"),
    ({"ads_daily_cap": "60"}, "daily_cap"),  # 2 x 30.50 a day
    ({"ads_lifetime_cap": "400", "ads_daily_cap": "100"}, "lifetime_cap"),
])
async def test_approve_over_a_cap_refused_before_any_request(store, meta, settings_kw, code):
    t = await _propose(store, _settings())
    with pytest.raises(BudgetRefused) as e:
        await tests.approve(store, _settings(**settings_kw), t["id"], "427",
                            underpowered_ok=True)
    assert e.value.code == code, e.value.message
    assert not _posts(meta) and store._get("ad_tests", t["id"])["status"] == "proposed"


async def test_approve_killed_or_not_configured_refused_before_any_request(store, meta):
    s = _settings()
    t = await _propose(store, s)
    with pytest.raises(AdTestRefused) as e:
        await tests.approve(store, _settings(meta_page_id=None), t["id"], "427")
    assert e.value.code == "not_configured"
    budget.kill(store, "stop")
    with pytest.raises(BudgetRefused) as e:
        await tests.approve(store, s, t["id"], "427")
    assert e.value.code == "killed" and not _posts(meta)
    with pytest.raises(BudgetRefused):
        await tests.approve(store, s, t["id"], "abc")


async def test_failure_mid_creation_leaves_all_paused_and_cancels(store, meta):
    s = _settings()
    t = await _propose(store, s)
    calls = itertools.count()
    meta.post(f"{ACT}/adsets").mock(side_effect=lambda req: meta.new_id() if next(calls) == 0
                                    else respx.MockResponse(400, json={"error": {
                                        "message": "Invalid parameter", "code": 100}}))
    with pytest.raises(AdTestFailed, match="everything is paused"):
        await tests.approve(store, s, t["id"], "427")
    assert _status_calls(meta) == []  # nothing activated, nothing to pause
    row = store._get("ad_tests", t["id"])
    assert row["status"] == "cancelled" and "Invalid parameter" in row["reason"]
    assert budget.open_authorizations(store, t["id"]) == []
    assert budget.status(store, s)["lifetime"]["used"] == "0"
    assert {e["status"] for e in tests._entities(store, t["id"])} == {"PAUSED"}
    assert _audit(store) == ["propose", "approve", "cancel"]


async def test_failure_mid_activation_pauses_what_was_activated(store, meta):
    s = _settings()
    t = await _propose(store, s)
    meta.fail.add("907")
    with pytest.raises(AdTestFailed, match="Ad rejected"):
        await tests.approve(store, s, t["id"], "427")
    assert _status_calls(meta) == [
        ("903", "ACTIVE"), ("901", "ACTIVE"), ("900", "ACTIVE"),  # variant 1 went live
        ("907", "ACTIVE"),  # variant 2's ad: refused
        ("900", "PAUSED"), ("901", "PAUSED"), ("903", "PAUSED")]  # campaign first
    assert {e["status"] for e in tests._entities(store, t["id"])} == {"PAUSED"}
    assert store._get("ad_tests", t["id"])["status"] == "cancelled"
    # variant 1 ran for a moment: its reservation stays for 095; variant 2's is released
    assert len(budget.open_authorizations(store, t["id"])) == 1
    assert _audit(store) == ["propose", "approve", "activate", "cancel"]


async def test_kill_mid_activation(store, meta, monkeypatch):
    s = _settings()
    t = await _propose(store, s)
    real = writer.AdsWriter.activate

    async def then_kill(self, meta_id, **kw):
        await real(self, meta_id, **kw)
        budget.kill(store, "owner pressed stop")

    monkeypatch.setattr(writer.AdsWriter, "activate", then_kill)
    with pytest.raises(AdTestFailed, match="kill switch"):
        await tests.approve(store, s, t["id"], "427")
    assert _status_calls(meta) == [("903", "ACTIVE"), ("903", "PAUSED")]  # pause while killed


async def test_activate_refuses_a_released_authorization(store, meta):
    s = _settings()
    auth = budget.authorize_spend(store, s, 10, test_id=5, reason="ad set")
    budget.release(store, auth["id"])
    async with writer.AdsWriter(s, store=store) as w:
        with pytest.raises(BudgetRefused) as e:
            await w.activate("900", test_id=5, authorization_id=auth["id"])
        assert e.value.code == "released"
        with pytest.raises(BudgetRefused):  # another test's authorization
            await w.activate("900", test_id=6, authorization_id=auth["id"])
    assert not meta.calls


def test_active_only_via_approve():
    """writer.ACTIVE is read only by AdsWriter.activate (and tests.approve marking rows),
    and .activate() is called only inside tests.approve: every other src/ path pauses."""
    readers, callers = set(), set()
    for f in sorted(SRC.rglob("*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for n in ast.walk(fn):
                if isinstance(n, ast.Name) and n.id == "ACTIVE":
                    readers.add((f.name, fn.name))
                if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                        and n.func.attr == "activate"):
                    callers.add((f.name, fn.name))
        consts = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant)]
        assert consts.count("ACTIVE") == (1 if f.name == "writer.py" else 0), f.name
    assert readers == {("writer.py", "activate"), ("tests.py", "approve")}
    assert callers == {("tests.py", "approve")}


# --- cancel ----------------------------------------------------------------------------
async def test_cancel_running_pauses_and_keeps_reservations(store, meta):
    s = _settings()
    t = await _propose(store, s)
    await tests.approve(store, s, t["id"], "427")
    meta.reset()
    budget.kill(store)  # pausing works while killed
    out = await tests.cancel(store, s, t["id"], reason="changed my mind")
    assert out["status"] == "cancelled" and out["reason"] == "changed my mind"
    assert {st for _, st in _status_calls(meta)} == {"PAUSED"} and len(_status_calls(meta)) == 6
    assert [i for i, _ in _status_calls(meta)][:2] == ["900", "904"]  # campaigns first
    assert len(budget.open_authorizations(store, t["id"])) == 2
    with pytest.raises(AdTestRefused):
        await tests.cancel(store, s, t["id"])


async def test_cancel_pause_failure_keeps_the_test(store, meta):
    s = _settings()
    t = await _propose(store, s)
    await tests.approve(store, s, t["id"], "427")
    meta.fail.add("904")
    with pytest.raises(AdTestFailed, match="904"):
        await tests.cancel(store, s, t["id"])
    assert store._get("ad_tests", t["id"])["status"] == "running"
    assert _audit(store)[-1] == "cancel_failed"


async def test_cancel_proposed_sends_nothing(store, meta):
    s = _settings()
    t = await _propose(store, s)
    meta.reset()
    assert (await tests.cancel(store, s, t["id"]))["status"] == "cancelled"
    assert not meta.calls


# --- audit -----------------------------------------------------------------------------
def test_audit_rows_for_kill_unkill_and_append_only(store):
    budget.kill(store, "stop")
    budget.unkill(store)
    log = budget.audit_log(store, limit=1)
    assert log["total"] == 2 and [r["action"] for r in log["rows"]] == ["unkill"]
    assert budget.audit_log(store, offset=1)["rows"][0]["detail"] == {"reason": "stop"}
    with pytest.raises(Exception, match="append-only"):
        with store.immediate() as c:
            c.execute("UPDATE ads_audit SET action='x'")
    with pytest.raises(Exception, match="append-only"):
        with store.immediate() as c:
            c.execute("DELETE FROM ads_audit")


# --- API -------------------------------------------------------------------------------
@pytest.fixture
def api(meta):
    s = _settings(ui_password=PASSWORD)
    store = CampaignStore(":memory:")
    with TestClient(create_app(s, auth=Auth(s), store=store),
                    base_url="http://127.0.0.1") as tc:
        assert tc.post("/api/login", json={"password": PASSWORD},
                       headers={"Origin": "http://127.0.0.1"}).status_code == 200
        yield tc, store
    store.close()


def _send(tc, path, body=None):
    return tc.post(path, json=body, headers={"Origin": "http://127.0.0.1"})


def test_api_propose_approve_cancel(api, meta):
    tc, store = api
    for v in CREATIVE:
        _post(store, v["media_id"])
    r = _send(tc, "/api/ads/tests", {"hypothesis": "h", "variable": "creative",
                                     "variants": CREATIVE})
    assert r.status_code == 200 and r.json()["needed"]["total"] == 426.94
    tid = r.json()["id"]
    assert _send(tc, "/api/ads/tests", {"hypothesis": "h", "variable": "creative",
                                        "variants": CREATIVE[:1]}).json()["error"] == "invalid"
    url = f"/api/ads/tests/{tid}/approve"
    assert _send(tc, url, {"budget": "427"}).status_code == 422  # no password
    assert _send(tc, url, {"budget": "427", "password": ""}).json() == {
        "error": "password_required"}
    r = _send(tc, url, {"budget": "427", "password": "wrong"})
    assert r.status_code == 403 and r.json() == {"error": "bad_password"}
    r = _send(tc, url, {"budget": "100", "password": PASSWORD})
    assert r.status_code == 409 and r.json()["error"] == "underpowered"
    assert not _status_calls(meta)
    r = _send(tc, url, {"budget": "427", "password": PASSWORD})
    assert r.status_code == 200 and r.json()["status"] == "running"
    assert tc.get("/api/ads/tests").json()["tests"][0]["status"] == "running"
    assert tc.get("/api/ads/tests?status=proposed").json()["tests"] == []
    assert _send(tc, f"/api/ads/tests/{tid}/cancel").json()["status"] == "cancelled"
    assert _send(tc, "/api/ads/tests/999/cancel").status_code == 404
    log = tc.get("/api/ads/audit?limit=2").json()
    assert log["total"] == 5 and [r["action"] for r in log["rows"]] == ["cancel", "activate"]
    assert "password" not in json.dumps(log)
    assert tc.get("/api/ads/audit?limit=0").status_code == 422


def test_api_approve_without_ui_password_refused(meta):
    s = _settings()
    store = CampaignStore(":memory:")
    with TestClient(create_app(s, auth=Auth(s), store=store),
                    base_url="http://127.0.0.1") as tc:
        r = _send(tc, "/api/ads/tests/1/approve", {"budget": "1", "password": "x"})
        assert r.status_code == 403 and r.json() == {"error": "password_not_set"}
    store.close()
    assert not meta.calls


def test_api_winners_and_kill_audit(api, monkeypatch):
    tc, store = api
    monkeypatch.setattr(tests, "scored_posts", lambda store, settings: [])
    assert tc.get("/api/ads/winners").json() == {"winners": []}
    _send(tc, "/api/ads/kill", {"reason": "panic"})
    assert tc.get("/api/ads/audit").json()["rows"][0]["detail"] == {"reason": "panic"}
