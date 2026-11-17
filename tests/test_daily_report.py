"""Step 083: the daily report (src/learning/report.py), its MCP tool, the brief and the
daily-learn work packet gate."""

from datetime import date, datetime, timezone

import pytest

import src.instagram_mcp_server as srv
from src.agent import packet
from src.config import InstagramMCPSettings
from src.learning import brief, report

NOW = datetime(2026, 11, 17, 1, tzinfo=timezone.utc)  # 2026-11-17 in UTC
DAY = "2026-11-16"
FACTS = {"report_date": DAY,
         "yesterday": {"matured": {"count": 1, "posts": [{"media_id": "m1"}]}},
         "last_7_days": {"matured": {"count": 2, "posts": [{"media_id": "m1"},
                                                           {"media_id": "m2"}]}}}
EXP = {"hypothesis": "A question hook keeps viewers past 3 s", "variable": "hook_type",
       "variants": ["question", "pov"]}


@pytest.fixture
def cfg():
    return InstagramMCPSettings(_env_file=None, instagram_access_token=None,
                                database_path=":memory:", timezone="UTC")


@pytest.fixture
def facts_day(store):
    store.save_daily_report(date(2026, 11, 16), None, FACTS)
    return store


def _save(store, cfg, day=DAY, summary="Quiet day.", **kw):
    return report.save_daily_report(store, cfg, day, summary, now=NOW, **kw)


def test_save_then_overwrite_keeps_the_facts(facts_day, cfg):
    row = _save(facts_day, cfg, "2026-11-16", "**m1 won**",
                best=[{"media_id": "m1", "why": " hook at 0.5 s, skip 20 % vs 35 % "}],
                worst=[{"media_id": "m2", "why": "left at 6.4 s: punchline freeze"}],
                experiments=[EXP])
    assert row["summary"] == "**m1 won**" and row["facts"] == FACTS
    assert row["analysis"] == {
        "best": [{"media_id": "m1", "why": "hook at 0.5 s, skip 20 % vs 35 %"}],
        "worst": [{"media_id": "m2", "why": "left at 6.4 s: punchline freeze"}],
        "experiments": [EXP]}
    again = _save(facts_day, cfg, summary="v2")
    assert again["id"] == row["id"] and again["summary"] == "v2"
    assert again["analysis"] == {"best": [], "worst": [], "experiments": []}
    # the worker re-storing the facts keeps the agent's summary and analysis
    facts_day.save_daily_report(date(2026, 11, 16), again["summary"], FACTS)
    assert facts_day.get_daily_report(DAY)["analysis"] == again["analysis"]


@pytest.mark.parametrize("day, match", [
    ("16/11/2026", "YYYY-MM-DD"), (None, "YYYY-MM-DD"), ("2026-11-17", "past days"),
    ("2026-12-01", "past days"), ("2026-11-10", "no facts"),
])
def test_bad_dates_are_refused(facts_day, cfg, day, match):
    with pytest.raises(ValueError, match=match):
        _save(facts_day, cfg, day)


def test_empty_facts_row_is_refused(store, cfg):
    store.save_daily_report(date(2026, 11, 16), None, {})
    with pytest.raises(ValueError, match="no facts"):
        _save(store, cfg)


@pytest.mark.parametrize("kw, match", [
    ({"summary": "  "}, "summary"),
    ({"summary": "x" * (report.SUMMARY_CHARS + 1)}, "summary"),
    ({"best": [{"media_id": "m1", "why": "w"}] * 4}, "at most 3"),
    ({"best": [{"media_id": "m1"}]}, "why"),
    ({"worst": [{"media_id": "m1", "why": "x" * 501}]}, "500"),
    ({"worst": [{"media_id": "m1", "why": "w", "extra": 1}]}, "extra"),
    ({"best": [{"media_id": "nope", "why": "w"}]}, "not a matured post"),
    ({"experiments": [EXP] * 4}, "at most 3"),
    ({"experiments": [{**EXP, "variants": ["one"]}]}, "at least 2"),
    ({"experiments": [{"hypothesis": "h", "variants": ["a", "b"]}]}, "variable"),
])
def test_invalid_content_is_refused(facts_day, cfg, kw, match):
    with pytest.raises(ValueError, match=match):
        _save(facts_day, cfg, **kw)
    assert facts_day.get_daily_report(DAY)["summary"] is None


async def test_mcp_tool(facts_day, cfg, monkeypatch):
    monkeypatch.setattr(srv, "store", lambda: facts_day)
    monkeypatch.setattr(srv, "get_settings", lambda: cfg)
    monkeypatch.setattr(srv, "utcnow", lambda: NOW)
    row = await srv.save_daily_report(DAY, "ok", experiments=[EXP])
    assert row["summary"] == "ok" and row["analysis"]["experiments"] == [EXP]
    with pytest.raises(srv.ToolError, match="past days"):
        await srv.save_daily_report("2026-11-17", "ok")


def test_brief_lists_the_proposed_experiments_of_the_last_summarised_report(facts_day, cfg):
    _save(facts_day, cfg, summary="analysed", experiments=[EXP])
    facts_day.save_daily_report(date(2026, 11, 17), None, FACTS)  # a quiet day after
    last = brief.creative_brief(facts_day, cfg, datetime(2026, 11, 18, 1,
                                                         tzinfo=timezone.utc))["last_daily_report"]
    assert last == {"report_date": DAY, "summary": "analysed", "proposed_experiments": [EXP]}


@pytest.mark.parametrize("count, skip", [(0, True), (2, False)])
def test_daily_learn_is_gated_by_the_facts(store, cfg, tmp_path, monkeypatch, count, skip):
    real = packet.SECTIONS["facts"]  # valid facts of an empty day, counted as asked
    monkeypatch.setitem(packet.SECTIONS, "facts", lambda *a: (real(*a)[0], count))
    out = packet.write_packet(store, cfg, "daily-learn", tmp_path)
    assert set(out["manifest"]["sections"]) == {"facts", "brief"}
    assert out["manifest"]["run_kind"] == "learn" and out["skip"] is skip
