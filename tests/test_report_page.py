"""Step 085: the daily report page API (src/api/reports.py, src/learning/report.py)."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app

from .conftest import LOCAL
from .test_analytics import _post, _studio_post
from .test_api_assets import _settings

FINDING = {"kind": "exit", "at_s": 6.4, "confidence": "low", "text": "leaves at 0:06"}
FACTS = {
    "report_date": "2026-11-16",
    "yesterday": {"published": {"count": 2, "posts": []},
                  "matured": {"count": 1, "posts": [{"media_id": "ours", "retention": [FINDING]}]},
                  "winners": [], "losers": [{"media_id": "ours", "verdict": "weak",
                                             "retention": [FINDING]}]},
    "last_7_days": {"matured": {"count": 2, "posts": [{"media_id": "ext", "retention": []}]},
                    "winners": [{"media_id": "ext", "verdict": "winner", "retention": []}],
                    "losers": []},
}
ANALYSIS = {"best": [{"media_id": "ext", "why": "hook holds"}],
            "worst": [{"media_id": "ours", "why": "left at 6.4 s"}],
            "experiments": [{"hypothesis": "h", "variable": "hook_type", "variants": ["a", "b"]}]}


@pytest.fixture
def tc(store):
    with TestClient(create_app(_settings(timezone="UTC"), store=store), base_url=LOCAL) as c:
        yield c


def _report(store, day, summary, facts=FACTS, analysis=ANALYSIS):
    store.save_daily_report(date.fromisoformat(day), None, facts)
    if summary is not None:
        store.save_daily_analysis(day, summary, analysis)


def test_no_report_yet(tc):
    r = tc.get("/api/reports/latest")
    assert r.status_code == 404 and r.json() == {"error": "not_found"}
    assert tc.get("/api/reports").json() == []


def test_latest_by_date_and_media_enrichment(tc, store):
    _post(store, "ext", 100, "REELS", caption="Big win\nsecond line")
    _post(store, "ours", 100, "REELS")
    asset = _studio_post(store, "ours")
    store.update_asset(asset["id"], thumbnail_path="2026-11-01/1/thumb.jpg")
    _report(store, "2026-11-15", "## Older\nbody")
    _report(store, "2026-11-16", "# Good day\n**ext** won")
    _report(store, "2026-11-17", None, facts={"yesterday": {}})  # quiet: facts only

    body = tc.get("/api/reports/latest").json()
    assert body["report_date"] == "2026-11-16" and body["summary"].startswith("# Good day")
    assert body["analysis"] == ANALYSIS and body["facts"] == FACTS
    ext, ours = body["posts"]["ext"], body["posts"]["ours"]
    assert ext == {"media_id": "ext", "permalink": "https://instagram.com/p/ext",
                   "title": "Big win", "asset_id": None, "thumbnail_url": None,
                   "verdict": "winner", "retention": []}
    assert ours["asset_id"] == asset["id"] and ours["verdict"] == "weak"
    assert ours["thumbnail_url"] == "/api/media/2026-11-01/1/thumb.jpg"
    assert ours["retention"] == [FINDING] and ours["title"] == "post ours"

    assert tc.get("/api/reports/2026-11-15").json()["summary"] == "## Older\nbody"
    quiet = tc.get("/api/reports/2026-11-17").json()
    assert quiet["summary"] is None and quiet["posts"] == {} and quiet["analysis"] == {}
    for bad in ("2026-01-01", "nope"):
        r = tc.get(f"/api/reports/{bad}")
        assert r.status_code == 404 and r.json() == {"error": "not_found"}


def test_archive(tc, store):
    _report(store, "2026-11-15", "## Older\nbody")
    _report(store, "2026-11-16", "  # Good day\n**ext** won")
    _report(store, "2026-11-17", None, facts={"yesterday": {}})
    rows = tc.get("/api/reports").json()
    assert rows[0] == {"report_date": "2026-11-17", "first_line": None, "published": None,
                       "matured": None, "best": 0, "worst": 0, "experiments": 0}
    assert rows[1] == {"report_date": "2026-11-16", "first_line": "Good day", "published": 2,
                       "matured": 1, "best": 1, "worst": 1, "experiments": 1}
    assert rows[2]["first_line"] == "Older"
    assert [r["report_date"] for r in tc.get("/api/reports?limit=1").json()] == ["2026-11-17"]
    assert tc.get("/api/reports?limit=0").status_code == 422
