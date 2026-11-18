"""Step 091: the ad budget guard. Every refusal path, the ledger, the kill switch,
concurrency, the @spends enforcement and the API routes."""

import ast
import threading
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.ads import budget
from src.ads.budget import BudgetRefused, authorize_spend, release
from src.api.app import create_app
from src.api.auth import Auth
from src.config import InstagramMCPSettings
from src.store import CampaignStore

ADS_DIR = Path(budget.__file__).parent
PASSWORD = "correct horse"


def _settings(**kw):
    kw = {"ads_daily_cap": "10", "ads_test_cap": "100", "ads_lifetime_cap": "100",
          "timezone": "Europe/Paris", **kw}
    return InstagramMCPSettings(_env_file=None, database_path=":memory:", **kw)


def _at(s):
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def _refused(code, store, settings, amount, **kw):
    kw.setdefault("reason", "test")
    with pytest.raises(BudgetRefused) as e:
        authorize_spend(store, settings, amount, **kw)
    assert e.value.code == code, e.value.message


def _rows(store):
    with store.immediate() as c:
        return c.execute("SELECT COUNT(*) FROM ad_spend_ledger").fetchone()[0]


def test_default_caps_refuse_everything(store):
    s = InstagramMCPSettings(_env_file=None, database_path=":memory:")
    assert (s.ads_daily_cap, s.ads_test_cap, s.ads_lifetime_cap) == (0, 0, 0)
    assert s.ads_currency == "EUR"
    _refused("daily_cap", store, s, "0.01")
    _refused("daily_cap", store, s, 1, test_id=1)
    assert _rows(store) == 0


@pytest.mark.parametrize("amount", [0, -1, "0", "-0.01", "NaN", "Infinity", "abc", 1.0, True,
                                    None, Decimal("NaN")])
def test_invalid_amounts_refused(store, amount):
    _refused("invalid", store, _settings(), amount)
    assert _rows(store) == 0


@pytest.mark.parametrize("kw", [{"reason": ""}, {"reason": "  "}, {"reason": None},
                                {"test_id": "1"}, {"test_id": True}, {"ad_entity_id": 123}])
def test_invalid_arguments_refused(store, kw):
    _refused("invalid", store, _settings(), 1, **kw)


def test_daily_cap_uses_the_owner_local_day(store):
    s = _settings()  # daily 10, Europe/Paris (UTC+1 in November)
    row = authorize_spend(store, s, "10", reason="t", now=_at("2026-11-18T22:30:00"))
    assert row["kind"] == "authorized" and row["amount"] == "10" and row["currency"] == "EUR"
    _refused("daily_cap", store, s, "0.01", now=_at("2026-11-18T22:59:59"))  # 23:59 Paris
    # 00:00 Paris on the 19th, still the 18th in UTC: a new day.
    authorize_spend(store, s, "10", reason="t", now=_at("2026-11-18T23:00:00"))
    # 02:00 Paris on the 19th is a new UTC day but the same local day: still refused.
    _refused("daily_cap", store, s, 1, now=_at("2026-11-19T01:00:00"))


def test_test_cap(store):
    s = _settings(ads_test_cap="5", ads_daily_cap="50")
    authorize_spend(store, s, 3, test_id=1, reason="t")
    authorize_spend(store, s, 2, test_id=1, reason="t")
    _refused("test_cap", store, s, "0.01", test_id=1)
    authorize_spend(store, s, 5, test_id=2, reason="t")  # another test has its own cap
    _refused("test_cap", store, s, 6)  # no test: the amount alone must fit


def test_lifetime_cap_across_days(store):
    s = _settings(ads_lifetime_cap="15")
    authorize_spend(store, s, 10, reason="t", now=_at("2026-11-10T12:00:00"))
    _refused("lifetime_cap", store, s, 6, now=_at("2026-11-11T12:00:00"))
    authorize_spend(store, s, 5, reason="t", now=_at("2026-11-11T12:00:00"))
    assert _rows(store) == 2


def test_release_frees_money(store):
    s = _settings()
    first = authorize_spend(store, s, 10, test_id=7, reason="t")
    _refused("daily_cap", store, s, 1)
    out = release(store, first["id"], reason="test stopped")
    assert out["kind"] == "released" and out["authorization_id"] == first["id"]
    assert out["amount"] == "10" and out["test_id"] == 7
    authorize_spend(store, s, 10, reason="t")
    with pytest.raises(ValueError, match="already released"):
        release(store, first["id"])
    with pytest.raises(ValueError, match="not authorized"):
        release(store, out["id"])
    with pytest.raises(KeyError):
        release(store, 999)
    st = budget.status(store, s)
    assert st["daily"] == {"cap": "10", "used": "10", "remaining": "0"}
    assert st["tests"] == []


def test_reported_spend_counts_and_other_currency_refused(store):
    s = _settings()
    with store.immediate() as c:
        c.execute("INSERT INTO ad_spend_ledger (kind, amount, currency, reason, created_at)"
                  " VALUES ('reported', '9.5', 'EUR', 'meta', ?)",
                  (datetime.now(timezone.utc).isoformat(timespec="seconds"),))
    _refused("daily_cap", store, s, "0.51")
    authorize_spend(store, s, "0.5", reason="t")
    assert budget.status(store, s)["daily"]["used"] == "10.0"
    with store.immediate() as c:
        c.execute("INSERT INTO ad_spend_ledger (kind, amount, currency, reason, created_at)"
                  " VALUES ('reported', '1', 'USD', 'meta', '2026-01-01T00:00:00+00:00')")
    _refused("invalid", store, _settings(ads_daily_cap="100"), 1)
    assert budget.status(store, s)["currency_conflict"] == ["USD"]


def test_ledger_constraints(store):
    with pytest.raises(Exception, match="CHECK"):
        with store.immediate() as c:
            c.execute("INSERT INTO ad_spend_ledger (kind, amount, currency, reason, created_at)"
                      " VALUES ('released', '1', 'EUR', 'r', 'x')")
    with pytest.raises(Exception, match="CHECK"):
        with store.immediate() as c:
            c.execute("INSERT INTO ad_spend_ledger (kind, amount, currency, reason, created_at)"
                      " VALUES ('spent', '1', 'EUR', 'r', 'x')")


def test_kill_refuses_everything_and_lists_ads_to_pause(store):
    s = _settings()
    a = authorize_spend(store, s, 2, ad_entity_id="111", reason="t")
    b = authorize_spend(store, s, 2, ad_entity_id="222", reason="t")
    authorize_spend(store, s, 2, reason="no ad yet")
    release(store, b["id"])
    assert budget.paused_ids_needed(store) == []  # not killed
    budget.kill(store, "owner pressed stop")
    _refused("killed", store, s, "0.01")
    _refused("killed", store, _settings(ads_daily_cap="100"), 1, test_id=3)
    assert budget.paused_ids_needed(store) == [a["ad_entity_id"]]
    st = budget.status(store, s)
    assert st["killed"] is True and st["killed_reason"] == "owner pressed stop"
    assert st["killed_at"]
    release(store, a["id"])  # releasing never spends: allowed while killed
    budget.unkill(store)
    assert budget.status(store, s)["killed"] is False
    authorize_spend(store, s, 1, reason="t")


def test_status_shape(store):
    s = _settings()
    authorize_spend(store, s, "2.50", test_id=4, reason="t", now=_at("2026-11-18T12:00:00"))
    st = budget.status(store, s, now=_at("2026-11-18T13:00:00"))
    assert st["currency"] == "EUR" and st["day"] == "2026-11-18" and st["killed"] is False
    assert st["daily"] == {"cap": "10", "used": "2.50", "remaining": "7.50"}
    assert st["lifetime"] == {"cap": "100", "used": "2.50", "remaining": "97.50"}
    assert st["tests"] == [{"test_id": 4, "cap": "100", "used": "2.50", "remaining": "97.50"}]


def test_concurrent_authorizations_cannot_exceed_a_cap(tmp_path, monkeypatch):
    """Eight threads on two stores (two connections each, like two processes), each asking
    for 1 under a cap of 3. A slow read widens the race window: without BEGIN IMMEDIATE
    several would pass."""
    real = budget._usage

    def slow_usage(*a, **kw):
        out = real(*a, **kw)
        time.sleep(0.05)
        return out

    monkeypatch.setattr(budget, "_usage", slow_usage)
    path = str(tmp_path / "studio.db")
    stores = [CampaignStore(path), CampaignStore(path)]
    s = _settings(ads_daily_cap="3")
    go = threading.Barrier(8)
    results = []

    def attempt(i):
        go.wait()
        try:
            authorize_spend(stores[i % 2], s, 1, reason=f"t{i}")
            results.append("ok")
        except BudgetRefused as e:
            results.append(e.code)

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    try:
        assert sorted(results) == ["daily_cap"] * 5 + ["ok"] * 3
        assert budget.status(stores[0], s)["daily"]["used"] == "3"
    finally:
        for st in stores:
            st.close()


# --- @spends enforcement ------------------------------------------------------------
WRITE_ATTRS = {"post", "put", "patch", "delete", "request"}


def spend_violations(source: str) -> list:
    """Write requests outside a @spends function, and @spends functions that never call
    authorize_spend. A write = `_make_request(<anything but "GET">, ...)` or an httpx-style
    `.post/.put/.patch/.delete/.request(...)` call."""
    found = []

    def name(node):
        return getattr(node, "attr", None) or getattr(node, "id", None)

    def is_write(call):
        fn = name(call.func)
        if fn == "_make_request":
            method = call.args[0] if call.args else next(
                (k.value for k in call.keywords if k.arg == "method"), None)
            return not (isinstance(method, ast.Constant) and method.value == "GET")
        return isinstance(call.func, ast.Attribute) and fn in WRITE_ATTRS

    def visit(node, spender):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            marked = any(name(d) == "spends" for d in node.decorator_list)
            if marked and not any(isinstance(n, ast.Call) and name(n.func) == "authorize_spend"
                                  for n in ast.walk(node)):
                found.append(f"{node.name}: @spends without authorize_spend")
            spender = spender or marked
        if isinstance(node, ast.Call) and is_write(node) and not spender:
            found.append(f"line {node.lineno}: write request outside @spends")
        for child in ast.iter_child_nodes(node):
            visit(child, spender)

    visit(ast.parse(source), False)
    return found


def test_no_src_ads_write_path_skips_the_guard():
    files = sorted(ADS_DIR.rglob("*.py"))
    assert {"client.py", "budget.py"} <= {f.name for f in files}
    for f in files:
        assert spend_violations(f.read_text(encoding="utf-8")) == [], f.name


@pytest.mark.parametrize("source", [
    'async def f(self):\n    return await self._make_request("POST", "x")\n',
    'async def f(self, m):\n    return await self._make_request(m, "x")\n',
    'async def f(self):\n    return await self._make_request(method="DELETE")\n',
    'async def f(self):\n    return await self.http.post("x")\n',
    '@spends\nasync def f(self):\n    return await self._make_request("POST", "x")\n',
    'class C:\n    async def f(self):\n        await self._make_request("POST", "x")\n',
])
def test_spend_check_catches_unguarded_writes(source):
    assert spend_violations(source)


def test_spend_check_accepts_guarded_writes_and_reads():
    assert spend_violations(
        '@budget.spends\nasync def f(self, store, settings):\n'
        '    authorize_spend(store, settings, 1, reason="x")\n'
        '    return await self._make_request("POST", "x")\n'
        'async def g(self):\n    return await self._make_request("GET", "x")\n') == []


# --- settings --------------------------------------------------------------------------
@pytest.mark.parametrize("kw", [
    {"ads_daily_cap": "-1"}, {"ads_test_cap": "-0.01"}, {"ads_lifetime_cap": "NaN"},
    {"ads_daily_cap": "11", "ads_lifetime_cap": "10"}, {"ads_currency": "EURO"},
    {"ads_currency": "€1"},
])
def test_invalid_cap_settings_refused(kw):
    with pytest.raises(ValidationError):
        InstagramMCPSettings(_env_file=None, **kw)


def test_currency_normalised():
    assert _settings(ads_currency=" usd ").ads_currency == "USD"


# --- API -------------------------------------------------------------------------------
@pytest.fixture
def api():
    started = []

    def make(password=PASSWORD, **kw):
        s = _settings(ui_password=password, instagram_access_token=None, **kw)
        store = CampaignStore(":memory:")
        tc = TestClient(create_app(s, auth=Auth(s), store=store), base_url="http://127.0.0.1")
        started.append((tc.__enter__(), store))
        if password:
            assert tc.post("/api/login", json={"password": password},
                           headers={"Origin": "http://127.0.0.1"}).status_code == 200
        return tc, store

    yield make
    for tc, store in started:
        tc.__exit__(None, None, None)
        store.close()


def _post(tc, path, body=None):
    return tc.post(path, json=body, headers={"Origin": "http://127.0.0.1"})


def test_api_budget_kill_unkill(api):
    tc, store = api()
    r = tc.get("/api/ads/budget")
    assert r.status_code == 200 and r.json()["killed"] is False
    assert r.json()["daily"] == {"cap": "10", "used": "0", "remaining": "10"}
    r = _post(tc, "/api/ads/kill", {"reason": "stop it"})
    assert r.status_code == 200 and r.json()["killed"] is True
    assert r.json()["killed_reason"] == "stop it"
    _refused("killed", store, _settings(), 1)

    assert _post(tc, "/api/ads/unkill", {"password": "wrong"}).json() == {
        "error": "bad_password"}
    assert _post(tc, "/api/ads/unkill", {"password": ""}).status_code == 400
    assert _post(tc, "/api/ads/unkill", {}).status_code == 422
    assert _post(tc, "/api/ads/unkill").status_code == 422
    assert tc.get("/api/ads/budget").json()["killed"] is True  # still killed
    r = _post(tc, "/api/ads/unkill", {"password": PASSWORD})
    assert r.status_code == 200 and r.json()["killed"] is False
    assert _post(tc, "/api/ads/kill").json()["killed_reason"] == "kill switch"  # no body


def test_api_unkill_wrong_password_is_403_and_locks_out(api):
    tc, _ = api()
    _post(tc, "/api/ads/kill")
    for _ in range(4):
        assert _post(tc, "/api/ads/unkill", {"password": "nope"}).status_code == 403
    assert _post(tc, "/api/ads/unkill", {"password": "nope"}).status_code == 403  # 5th locks
    r = _post(tc, "/api/ads/unkill", {"password": PASSWORD})
    assert r.status_code == 429 and r.json()["error"] == "locked"
    assert tc.get("/api/ads/budget").json()["killed"] is True


def test_api_unkill_refused_without_ui_password(api):
    tc, _ = api(password=None)
    _post(tc, "/api/ads/kill")
    r = _post(tc, "/api/ads/unkill", {"password": "anything"})
    assert r.status_code == 403 and r.json() == {"error": "password_not_set"}
    assert tc.get("/api/ads/budget").json()["killed"] is True


def test_api_needs_login_and_same_origin(api):
    tc, _ = api()
    tc.cookies.clear()
    assert tc.get("/api/ads/budget").status_code == 401
    assert _post(tc, "/api/ads/kill").status_code == 401
    tc2, _ = api()
    r = tc2.post("/api/ads/unkill", json={"password": PASSWORD},
                 headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and r.json() == {"error": "bad_origin"}
