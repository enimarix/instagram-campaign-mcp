"""Step 034: render queue, render outputs, keep-awake, re-render API."""

import argparse
import asyncio
import ctypes
import random
import sys
import threading
import time
from contextlib import suppress
from datetime import timedelta
from functools import partial

import pytest
from fastapi.testclient import TestClient

from src import scheduler, worker
from src.api.app import create_app
from src.config import InstagramMCPSettings
from src.store import utcnow
from src.studio import ffmpeg, power, render
from src.studio.assets import transition
from src.studio.ffmpeg import MediaInfo
from src.studio.seed import seed
from tests.test_studio_ffmpeg import needs_ffmpeg
from tests.test_studio_recipe import make_clip

from .conftest import LOCAL

FFMPEG = {"kind": "ffmpeg", "recipe": {"version": 1, "ops": [{"op": "fit_vertical"}]},
          "inputs": {"source": "src/clip.mp4"}}
FAR_PAST = utcnow() - timedelta(days=1)
INFO = MediaInfo(2.0, 1080, 1920, 30.0, "h264", True, "aac", 48000, 1)


def _settings(tmp_path, **kw):
    return InstagramMCPSettings(_env_file=None, instagram_access_token=None,
                                database_path=":memory:", media_root=str(tmp_path), **kw)


def _asset(store, recipe=FFMPEG, status="rendering"):
    a = store.add_asset(store.add_idea("motion")["id"], recipe=recipe)
    if status != "rendering":
        a = transition(store, a["id"], status, actor="worker")
    return a


def _claim(store):
    return store.claim_render_jobs(1, stale_before=FAR_PAST)[0]


def test_enqueue_is_idempotent(store):
    a = _asset(store)
    job = render.enqueue_render(store, a["id"])
    assert render.enqueue_render(store, a["id"]) == job
    assert job["state"] == "queued" and job["idempotency_key"].startswith(f"{a['id']}:")
    assert render.enqueue_render(store, a["id"], key="k")["id"] != job["id"]
    store.update_asset(a["id"], recipe={**FFMPEG, "thumb_offset_ms": 500})
    assert render.enqueue_render(store, a["id"])["id"] not in (job["id"],)
    # a failed job stays failed while the asset is failed, re-queues once it renders again
    store.update_render_job(job["id"], state="failed", failure="x", attempts=3)
    store.update_asset(a["id"], recipe=FFMPEG)
    transition(store, a["id"], "failed", actor="worker")
    assert render.enqueue_render(store, a["id"])["state"] == "failed"
    transition(store, a["id"], "rendering", actor="owner")
    again = render.enqueue_render(store, a["id"])
    assert (again["id"], again["state"], again["attempts"]) == (job["id"], "queued", 0)


@needs_ffmpeg
def test_render_writes_master_preview_poster_thumb(store, tmp_path):
    (tmp_path / "src").mkdir()
    make_clip(tmp_path / "src" / "clip.mp4", "320x240", duration=2)
    a = _asset(store)
    render.enqueue_render(store, a["id"])
    job = render.run_job(store, tmp_path, _claim(store),
                         render_fn=partial(render.render_files, preset="ultrafast"))
    assert job["state"] == "done" and job["progress"] == 1 and job["render_ms"] > 0
    a = store.get_asset(a["id"])
    assert a["status"] == "ready" and a["qc"]["passed"] and a["qc"]["stub"]
    assert a["duration"] == pytest.approx(2.0, abs=0.1)
    folder = f"{a['batch_date']}/{a['id']}"
    assert (a["file_path"], a["preview_path"], a["poster_path"], a["thumbnail_path"]) == (
        f"{folder}/video.mp4", f"{folder}/preview.mp4", f"{folder}/poster.jpg",
        f"{folder}/thumb.jpg")
    master = ffmpeg.probe(tmp_path / a["file_path"])
    assert (master.width, master.height) == (1080, 1920)
    preview = ffmpeg.probe(tmp_path / a["preview_path"])
    assert (preview.width, preview.height, preview.video_codec) == (720, 1280, "h264")
    assert preview.has_audio and preview.size_bytes * 8 / preview.duration < 2_000_000
    data = (tmp_path / a["preview_path"]).read_bytes()
    assert data.index(b"moov") < data.index(b"mdat")  # +faststart
    poster = ffmpeg.probe(tmp_path / a["poster_path"])
    assert (poster.width, poster.height) == (1080, 1920)
    assert ffmpeg.probe(tmp_path / a["thumbnail_path"]).width == render.THUMB_WIDTH


def test_failure_retries_then_fails_the_asset(store, tmp_path):
    a = _asset(store)
    render.enqueue_render(store, a["id"])
    calls = []

    def broken(asset, media_root, progress):
        calls.append(asset["id"])
        raise RuntimeError("ffmpeg exited with code 1")

    for attempt in range(1, render.MAX_ATTEMPTS + 1):
        job = render.run_job(store, tmp_path, _claim(store), render_fn=broken)
        assert job["attempts"] == attempt
        assert job["failure"] == "RuntimeError: ffmpeg exited with code 1"
        assert job["state"] == ("failed" if attempt == render.MAX_ATTEMPTS else "queued")
    assert len(calls) == render.MAX_ATTEMPTS and job["finished_at"]
    a = store.get_asset(a["id"])
    assert a["status"] == "failed" and a["qc"]["passed"] is False
    assert "ffmpeg exited" in a["qc"]["reason"]
    assert store.claim_render_jobs(1, stale_before=FAR_PAST) == []


def test_motion_recipe_fails_without_retry(store, tmp_path):
    a = _asset(store, {"kind": "motion", "template": "Hello", "props": {}})
    render.enqueue_render(store, a["id"])
    job = render.run_job(store, tmp_path, _claim(store))
    assert job["state"] == "failed" and "step 048" in job["failure"] and job["attempts"] == 1
    assert store.get_asset(a["id"])["status"] == "failed"


def test_stale_running_job_is_requeued(store):
    a = _asset(store)
    render.enqueue_render(store, a["id"])
    job = _claim(store)
    assert store.claim_render_jobs(1, stale_before=FAR_PAST) == []  # heartbeat is fresh
    again = store.claim_render_jobs(1, stale_before=utcnow() + timedelta(seconds=1))
    assert [(j["id"], j["attempts"]) for j in again] == [(job["id"], 2)]


def test_job_requeued_after_every_attempt_crashed_gives_up(store, tmp_path):
    a = _asset(store)
    render.enqueue_render(store, a["id"])
    job = _claim(store)
    store.update_render_job(job["id"], attempts=render.MAX_ATTEMPTS)
    job = store.claim_render_jobs(1, stale_before=utcnow() + timedelta(seconds=1))[0]
    out = render.run_job(store, tmp_path, job, render_fn=pytest.fail)
    assert out["state"] == "failed" and "gave up" in out["failure"]
    assert store.get_asset(a["id"])["status"] == "failed"


async def test_render_loop_respects_concurrency_and_keeps_awake(store, tmp_path, monkeypatch):
    awake = []

    class FakeAwake:
        def __enter__(self):
            awake.append(True)

        def __exit__(self, *exc):
            awake.append(False)

    monkeypatch.setattr(worker, "keep_awake", FakeAwake)
    ids = [_asset(store)["id"] for _ in range(5)]
    for i in ids:
        render.enqueue_render(store, i)
    lock, active, peak = threading.Lock(), [0], [0]

    def fake_render(asset, media_root, progress):
        assert awake[-1] is True  # held while a job runs
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.05)
        with lock:
            active[0] -= 1
        return INFO, {}

    settings = _settings(tmp_path, render_concurrency=2)
    run = partial(render.run_job, store, tmp_path, render_fn=fake_render)
    loop = asyncio.create_task(worker.render_loop(store, settings, run=run, interval=0.05))
    deadline = time.monotonic() + 20
    try:
        while len(store.list_render_jobs(state="done")) < 5 and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
    finally:
        loop.cancel()
        with suppress(asyncio.CancelledError):
            await loop
    assert len(store.list_render_jobs(state="done")) == 5
    assert peak[0] == 2
    assert awake[0] is True and awake[-1] is False
    assert {store.get_asset(i)["status"] for i in ids} == {"ready"}


def test_keep_awake_windows_and_elsewhere(monkeypatch):
    calls = []

    class Kernel32:
        def SetThreadExecutionState(self, flags):
            calls.append(flags)

    monkeypatch.setattr(ctypes, "windll", type("W", (), {"kernel32": Kernel32()})(),
                        raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    with power.keep_awake():
        assert calls == [power.ES_CONTINUOUS | power.ES_SYSTEM_REQUIRED]
    assert calls[-1] == power.ES_CONTINUOUS and len(calls) == 2
    monkeypatch.setattr(sys, "platform", "linux")
    with power.keep_awake():
        pass
    assert len(calls) == 2


@pytest.fixture
def tc(store, tmp_path):
    with TestClient(create_app(_settings(tmp_path), store=store), base_url=LOCAL) as c:
        yield c


def test_rerender_from_failed_and_ready(tc, store):
    edited = {**FFMPEG, "recipe": {"version": 1, "ops": [{"op": "fit_vertical", "mode": "crop"}]}}
    failed = _asset(store, status="failed")
    r = tc.post(f"/api/assets/{failed['id']}/rerender", json={"recipe": edited},
                headers={"Origin": LOCAL})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["asset"]["id"] == failed["id"] and body["asset"]["status"] == "rendering"
    assert body["asset"]["recipe"] == edited and body["job"]["state"] == "queued"

    ready = _asset(store, status="ready")
    body = tc.post(f"/api/assets/{ready['id']}/rerender", json={"recipe": edited},
                   headers={"Origin": LOCAL}).json()
    child = body["asset"]
    assert child["id"] != ready["id"] and child["parent_asset_id"] == ready["id"]
    assert child["status"] == "rendering" and child["idea_id"] == ready["idea_id"]
    assert store.get_asset(ready["id"])["status"] == "ready"  # the reviewed one stays
    assert body["job"]["asset_id"] == child["id"]

    jobs = tc.get("/api/render-jobs?state=queued").json()
    assert [j["asset_id"] for j in jobs] == [child["id"], failed["id"]]
    assert tc.get("/api/render-jobs?state=done").json() == []


def test_rerender_refusals(tc, store):
    rendering = _asset(store)
    r = tc.post(f"/api/assets/{rendering['id']}/rerender", json={"recipe": FFMPEG},
                headers={"Origin": LOCAL})
    assert r.status_code == 409
    failed = _asset(store, status="failed")
    for bad in ({"kind": "ffmpeg", "recipe": {"ops": [{"op": "hflip"}]}, "inputs": {"source": "a"}},
                {**FFMPEG, "inputs": {"music": "a.mp3"}},
                {**FFMPEG, "inputs": {"source": "../../etc/passwd"}},
                {"kind": "other"}):
        r = tc.post(f"/api/assets/{failed['id']}/rerender", json={"recipe": bad},
                    headers={"Origin": LOCAL})
        assert r.status_code == 422, bad
    assert store.get_asset(failed["id"])["status"] == "failed"
    assert tc.post("/api/assets/999/rerender", json={"recipe": FFMPEG},
                   headers={"Origin": LOCAL}).status_code == 404


def test_seed_recipes_are_valid_envelopes(store, tmp_path):
    seed(store, tmp_path, days=1, rng=random.Random(1))
    for a in store.list_assets(limit=500):
        render.validate_recipe(a["recipe"], tmp_path)


async def test_worker_cli_runs_renders_in_setup_mode(tmp_path, monkeypatch, capsys):
    settings = InstagramMCPSettings(_env_file=None, instagram_access_token=None,
                                    database_path=str(tmp_path / "db.sqlite"))
    ran = []

    async def fake_loop(store, s):
        ran.append(s)

    monkeypatch.setattr(scheduler, "get_settings", lambda: settings)
    monkeypatch.setattr(scheduler, "configure_logging", lambda *a: None)
    monkeypatch.setattr(worker, "render_loop", fake_loop)
    args = argparse.Namespace(command="daemon", interval=60, stories_every=60)
    assert await scheduler._run(args) == 0
    assert ran == [settings]
    assert "renders run" in capsys.readouterr().err
