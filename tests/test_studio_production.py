"""Production tools (step 053): services in src/studio/production.py and their MCP doors."""

import asyncio
import time

import pytest
from mcp.server.mcpserver.exceptions import ToolError

import src.instagram_mcp_server as srv
from src.studio import production
from src.studio.assets import set_verdict, transition

QC_OK = {"passed": True, "checks": [], "reasons": []}
QC_BAD = {"passed": False, "checks": [], "reasons": ["too quiet", "frozen 9 s"]}


def _asset(store, pillar="fun_facts", batch_date="2026-11-17"):
    idea = store.add_idea("motion", pillar=pillar, hook="Did you know?", batch_date=batch_date)
    asset = store.add_asset(idea["id"], batch_date=batch_date,
                            recipe={"kind": "motion", "template": "FactQuest",
                                    "props": {"hook": "x" * 500}})
    job = store.add_render_job(asset["id"], f"k{asset['id']}")
    return asset["id"], job["id"]


def _finish(store, asset_id, job_id, qc=QC_OK):
    store.update_asset(asset_id, qc=qc, file_path=f"2026-11-17/{asset_id}/video.mp4")
    transition(store, asset_id, "ready" if qc["passed"] else "failed", actor="worker")
    store.update_render_job(job_id, state="done", progress=1)


@pytest.fixture
def mcp_store(store, monkeypatch):
    monkeypatch.setattr(srv, "store", lambda: store)
    return store


def test_create_idea_uses_local_date_and_rejects_bad_tags(store, settings):
    idea = production.create_idea(store, settings, "motion", hook="Hi", pillar="myths",
                                  script=None, citations=[{"url": "https://a.org"}])
    assert idea["pillar"] == "myths" and idea["script"] is None and idea["batch_date"]
    with pytest.raises(ValueError, match="valid: fun_facts"):
        production.create_idea(store, settings, "motion", hook="Hi", pillar="cats")


async def test_mcp_create_idea_error_lists_values(mcp_store):
    assert (await srv.create_idea("motion", "Hook", hook_type="question"))["hook"] == "Hook"
    with pytest.raises(ToolError, match="valid: remix, motion"):
        await srv.create_idea("vlog", "Hook")


def test_submit_sets_caption_note_and_pillar_default(store, settings):
    a, j = _asset(store, pillar="everyday_humor")  # shelf_days 3
    _finish(store, a, j)
    store.update_asset(a, self_score=8)  # a legacy score (189: the agent no longer scores)
    assert production.list_assets(store)[0]["submitted"] is False
    row = production.submit_asset(store, settings, a, caption="Fact #fun",
                                  note=" Changed: cut to 12 s ")
    assert row["best_before"] == "2026-11-20" and "self_score" not in row
    assert row["submitted"] and row["note"] == "Changed: cut to 12 s"
    assert store.get_asset(a)["self_score"] is None  # the legacy score is cleared
    # re-submitting before the owner reacts overwrites; no note is still a submit
    row = production.submit_asset(store, settings, a, caption="Other", best_before="2026-12-01")
    assert row["best_before"] == "2026-12-01" and row["submitted"] and row["note"] is None


def test_submit_default_falls_back_to_setting(store, settings):
    settings.best_before_default_days = 10
    a, j = _asset(store, pillar=None)
    _finish(store, a, j)
    row = production.submit_asset(store, settings, a, caption="c")
    assert row["best_before"] == "2026-11-27"


@pytest.mark.parametrize("kw, match", [
    ({"note": "two\nlines"}, "one line"), ({"note": "x" * 201}, "one line"),
    ({"caption": ""}, "caption is required"),
    ({"caption": "#a #b #c #d #e #f"}, "hashtags"), ({"best_before": "20/11/2026"}, "YYYY-MM-DD"),
])
def test_submit_refuses_bad_input_and_writes_nothing(store, settings, kw, match):
    a, j = _asset(store)
    _finish(store, a, j)
    args = {"note": "ok", "caption": "c", **kw}
    with pytest.raises(ValueError, match=match):
        production.submit_asset(store, settings, a, **args)
    after = store.get_asset(a)
    assert after["self_score_reason"] is None and after["caption"] is None


def test_submit_refuses_wrong_status_or_judged(store, settings):
    args = {"caption": "c"}
    a, j = _asset(store)
    with pytest.raises(ValueError, match="still rendering"):
        production.submit_asset(store, settings, a, **args)
    _finish(store, a, j, QC_BAD)
    with pytest.raises(ValueError, match="QC failed: too quiet; frozen 9 s"):
        production.submit_asset(store, settings, a, **args)
    b, k = _asset(store)
    _finish(store, b, k)
    set_verdict(store, b, "liked")
    with pytest.raises(ValueError, match="already judged it"):
        production.submit_asset(store, settings, b, **args)
    set_verdict(store, b, "none")
    transition(store, b, "approved", actor="owner")
    with pytest.raises(ValueError, match="is approved"):
        production.submit_asset(store, settings, b, **args)


async def test_wait_returns_on_first_finish_with_reasons(store, settings):
    a, j = _asset(store)
    b, k = _asset(store)

    async def worker():
        await asyncio.sleep(0.1)
        _finish(store, a, j, QC_BAD)

    task = asyncio.create_task(worker())
    start = time.monotonic()
    out = await production.wait_for_renders(store, settings, batch_date="2026-11-17",
                                            timeout_s=5, poll_s=0.02)
    await task
    assert time.monotonic() - start < 2
    assert out["finished"] == [{"job_id": j, "asset_id": a, "state": "done", "status": "failed",
                                "qc": "failed: too quiet; frozen 9 s"}]
    assert [p["job_id"] for p in out["pending"]] == [k] and out["timed_out"] is False
    # batch mode: a job finished before the call is not news, so it waits for the next one
    out = await production.wait_for_renders(store, settings, batch_date="2026-11-17",
                                            timeout_s=0.1, poll_s=0.02)
    assert out["timed_out"] is True and len(out["finished"]) == 1
    # job_ids mode: the caller waits on exactly these, so an already finished one returns
    out = await production.wait_for_renders(store, settings, job_ids=[j, k], timeout_s=5)
    assert [f["job_id"] for f in out["finished"]] == [j]
    _finish(store, b, k)
    out = await production.wait_for_renders(store, settings, batch_date="2026-11-17")
    assert out["pending"] == [] and out["timed_out"] is False  # all done: at once


async def test_wait_respects_timeout_and_cap(store, settings):
    _asset(store)
    settings.wait_for_renders_max_s = 0.15
    start = time.monotonic()
    out = await production.wait_for_renders(store, settings, batch_date="2026-11-17",
                                            timeout_s=999, poll_s=0.02)
    assert 0.1 <= time.monotonic() - start < 1.5
    assert out["timed_out"] is True and out["finished"] == []
    with pytest.raises(ValueError, match="exactly one"):
        await production.wait_for_renders(store, settings)
    with pytest.raises(ValueError, match="no render job 99"):
        await production.wait_for_renders(store, settings, job_ids=[99])


async def test_mcp_read_tools_are_compact(mcp_store):
    a, j = _asset(mcp_store)
    _finish(mcp_store, a, j)
    mcp_store.update_asset(a, caption="y" * 300)
    (row,) = (await srv.list_assets(batch_date="2026-11-17", limit=500))["assets"]
    assert row["template"] == "FactQuest" and row["qc"] == "passed"
    assert len(row["caption"]) == production.EXCERPT_CHARS + 1 and "recipe" not in row
    assert row["file_path"] == f"2026-11-17/{a}/video.mp4"
    status = await srv.get_render_status(asset_id=a)
    assert status["job"]["id"] == j and status["job"]["state"] == "done"
    assert (await srv.get_render_status(job_id=j))["asset"]["id"] == a
    with pytest.raises(ToolError, match="exactly one"):
        await srv.get_render_status()
    with pytest.raises(ToolError, match="exactly one"):
        await srv.wait_for_renders()
    with pytest.raises(ToolError, match="one line"):
        await srv.submit_asset(a, "c", note="two\nlines")
    assert (await srv.submit_asset(a, "c", note="Changed: hook"))["note"] == "Changed: hook"
