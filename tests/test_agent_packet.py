"""Work packets (step 112): src/agent/packet.py and its use by the runner."""

import hashlib
import json
import random

import pytest

from src.agent import packet, runner
from src.config import InstagramMCPSettings
from src.studio.assets import transition
from src.studio.feedback import add_comment
from src.studio.seed import seed

from .test_agent_runner import _fake_cli


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_SEEN", str(tmp_path / "seen.json"))
    return InstagramMCPSettings(
        _env_file=None, instagram_access_token=None, database_path=":memory:",
        agent_workspace=str(tmp_path / "ws"), agent_log_dir=str(tmp_path / "logs"),
        claude_bin=_fake_cli(tmp_path))


@pytest.fixture
def agent_dir(tmp_path):
    d = tmp_path / "agent"
    (d / "playbooks").mkdir(parents=True)
    for name in ("daily-produce", "daily-revise"):
        (d / "playbooks" / f"{name}.md").write_text("Work.\n")
    return d


def _asset(store, status="ready"):
    idea = store.add_idea("motion", pillar="fun_facts", hook="Did you know?",
                          hook_type="question", batch_date="2026-11-17")
    a = store.add_asset(idea["id"], batch_date="2026-11-17",
                        recipe={"kind": "motion", "template": "FactQuest", "props": {"x": 1}})
    transition(store, a["id"], "ready", actor="worker")
    return a["id"]


def _files(ws):
    return sorted(p.name for p in (ws / "work").iterdir()) if (ws / "work").exists() else []


def test_every_section_is_valid_with_counts_and_checksums_on_a_seeded_db(
        store, cfg, tmp_path):
    seed(store, tmp_path / "media", days=3, rng=random.Random(1))
    ws = tmp_path / "ws"
    out = packet.write_packet(store, cfg, "daily-produce", ws)
    manifest = json.loads((ws / "work" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest == out["manifest"] and manifest["run_kind"] == "produce"
    produce = packet.RUNS["daily-produce"][1]
    assert set(manifest["sections"]) == set(packet.SECTIONS) - {"ads", "style_requests", "checks"} == set(produce)
    assert _files(ws) == sorted(["manifest.json", *(f"{n}.json" for n in produce)])
    for name, entry in manifest["sections"].items():
        raw = (ws / "work" / entry["file"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == entry["sha256"]
        data = json.loads(raw)
        packet.encode(data, name)  # valid against its schema
        if isinstance(data, list):
            assert entry["count"] == len(data)
    feedback = json.loads((ws / "work" / "feedback.json").read_bytes())
    assert out["ids"]["feedback"] == [f["id"] for f in feedback] and feedback
    assert all("file_path" not in f["asset"] for f in feedback)  # no paths, no recipes
    assert "recipe" not in (ws / "work" / "revisions.json").read_text(encoding="utf-8")
    assert not out["skip"]


def test_light_run_has_only_its_sections_and_lists_are_capped(store, cfg, tmp_path,
                                                              monkeypatch):
    monkeypatch.setattr(packet, "MAX_ITEMS", 2)
    a = _asset(store)
    for i in range(3):
        store.add_feedback(a, text="x" * (packet.MAX_TEXT + 5) if i == 0 else f"note {i}")
    out = packet.write_packet(store, cfg, "daily-revise", tmp_path)
    assert set(out["manifest"]["sections"]) == {"work_orders", "revisions", "feedback",
                                                 "dm_picks"}
    assert out["manifest"]["sections"]["feedback"]["count"] == 2
    data = json.loads((tmp_path / "work" / "feedback.json").read_bytes())
    assert len(data) == 2 and len(data[0]["text"]) == packet.MAX_TEXT + 1


def test_invalid_section_raises_and_writes_nothing(store, cfg, tmp_path, monkeypatch):
    (tmp_path / "work").mkdir()
    (tmp_path / "work" / "manifest.json").write_text("{}")  # last run's packet
    monkeypatch.setitem(packet.SECTIONS, "quotas", lambda *a: ({"date": "today"}, 1))
    with pytest.raises(packet.PacketError, match="quotas is invalid"):
        packet.write_packet(store, cfg, "daily-produce", tmp_path)
    assert _files(tmp_path) == []


def test_atomic_write_leaves_no_partial_file(tmp_path, monkeypatch):
    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(packet.os, "replace", boom)
    with pytest.raises(OSError):
        packet._write_atomic(tmp_path / "brief.json", b"{}")
    assert list(tmp_path.iterdir()) == []


def test_gaps_name_the_items_not_handled(store, cfg, tmp_path):
    done, left = _asset(store), _asset(store)
    for a in (done, left):
        add_comment(store, a, text="shorter", wants_changes=True)
    note = store.add_feedback(done, text="nice")["id"]
    out = packet.write_packet(store, cfg, "daily-revise", tmp_path)
    assert sorted(out["ids"]["revisions"]) == [done, left]
    fb = out["ids"]["feedback"]
    assert packet.gaps(store, out) == (
        f"2 of 2 revisions not handled: #{done}, #{left}; 3 of 3 feedback comments not "
        f"digested: {', '.join(f'#{i}' for i in fb)}")
    store.add_asset(store.get_asset(done)["idea_id"], parent_asset_id=done,
                    batch_date="2026-11-17", recipe={"kind": "motion", "template": "FactQuest",
                                                     "props": {}})
    store.mark_feedback_digested([i for i in fb if i != note])
    assert packet.gaps(store, out) == (
        f"1 of 2 revisions not handled: #{left}; 1 of 3 feedback comments not digested: "
        f"#{note}")
    # a request whose new version is still rendering is not work for the next run
    assert packet.write_packet(store, cfg, "daily-revise", tmp_path)["ids"]["revisions"] == [
        left]


# --- through the runner (fake `claude` CLI) ------------------------------------------------
def test_empty_light_run_is_skipped_without_claude(store, cfg, agent_dir, tmp_path):
    run = runner.run_agent(store, cfg, "daily-revise", agent_dir=agent_dir, timeout_s=60)
    assert run["status"] == "succeeded" and run["summary"] == packet.SKIPPED
    assert not (tmp_path / "seen.json").exists()
    assert _files(tmp_path / "ws") == ["dm_picks.json", "feedback.json", "manifest.json",
                                       "revisions.json", "work_orders.json"]


def test_daily_produce_runs_even_with_empty_sections(store, cfg, agent_dir, tmp_path):
    run = runner.run_agent(store, cfg, "daily-produce", agent_dir=agent_dir, timeout_s=60)
    assert run["status"] == "succeeded" and run["summary"] == "made 3 ideas"
    assert (tmp_path / "seen.json").exists()


@pytest.mark.parametrize("producer, match", [
    (lambda *a: ({"date": 3}, 1), "quotas is invalid at top level"),
    (lambda *a: 1 / 0, "section quotas failed: ZeroDivisionError"),
])
def test_bad_section_fails_the_run_before_claude(store, cfg, agent_dir, tmp_path,
                                                 monkeypatch, producer, match):
    monkeypatch.setitem(packet.SECTIONS, "quotas", producer)
    run = runner.run_agent(store, cfg, "daily-produce", agent_dir=agent_dir, timeout_s=60)
    assert run["status"] == "failed" and match in run["summary"]
    assert not (tmp_path / "seen.json").exists()


def test_gaps_are_appended_to_the_run_summary(store, cfg, agent_dir):
    a = _asset(store)
    add_comment(store, a, text="louder", wants_changes=True)
    run = runner.run_agent(store, cfg, "daily-revise", agent_dir=agent_dir, timeout_s=60)
    fb = store.list_feedback()[0]["id"]
    assert run["status"] == "succeeded"
    assert run["summary"] == (f"made 3 ideas\nwork packet: 1 of 1 revisions not handled: #{a}; "
                              f"1 of 1 feedback comments not digested: #{fb}")
