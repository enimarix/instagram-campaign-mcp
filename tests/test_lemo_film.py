"""The Lemo film runner (step 173): the one agent run with a shell. The guard tests fail if
its command, workspace or environment loosen; the rest drive a fake `claude` executable
that delivers a tiny film."""

import json
import os
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from src.agent import film, runner, schedule
from src.config import InstagramMCPSettings
from src.store import to_iso, utcnow
from src.studio import feedback, gpu_run, lemo, media, production, work_orders
from src.studio.assets import transition
from src.studio.feedback import add_comment

from .test_agent_packet import _asset

TOKEN = "IGQ-film-secret-789"
SAMPLE = Path(__file__).resolve().parents[1] / "src" / "studio" / "samples" / "sample.mp4"
# Written out again on purpose: loosening the film runner must touch this test too.
TOOLS = {"Read", "Write", "Edit", "Glob", "Grep", "Bash", "Skill"}
MUST_DISALLOW = {"PowerShell", "WebSearch", "WebFetch", "Agent", "NotebookEdit"}

FAKE = r'''
import json, os, sys, time
from pathlib import Path
args = sys.argv[1:]
mode = os.environ.get("FAKE_CLAUDE", "success")
if args[:2] == ["auth", "status"]:
    print(json.dumps({"loggedIn": mode != "signed_out"}))
    sys.exit(0)
seen = {"args": args, "cwd": os.getcwd(), "env": dict(os.environ),
        "brief": Path("BRIEF.md").read_text(encoding="utf-8")}
Path(os.environ["FAKE_CLAUDE_SEEN"]).write_text(json.dumps(seen))
if mode == "sleep":
    time.sleep(60)
if mode in ("success", "QC", "bare"):
    Path("film").mkdir(exist_ok=True)
    Path("film/final.mp4").write_bytes(Path(os.environ["FAKE_FILM"]).read_bytes())
if mode in ("success", "QC"):
    Path("film/post.json").write_text(json.dumps({
        "hook": "Où partent vos calories ?", "script": "Disons 2 000 kcal par jour.",
        "caption": "Où partent vos 2 000 kcal ? Envoyez ça à un ami.",
        "description": "Un diorama isométrique.",
        "sources": [{"title": "FAO 2004", "url": "https://www.fao.org/x"},
                    {"title": "a book, no link"}]}), encoding="utf-8")
ok = mode != "fail"
print(json.dumps({"type": "result", "subtype": "success" if ok else "error_max_turns",
                  "is_error": not ok, "result": "film made" if ok else None, "num_turns": 90,
                  "total_cost_usd": 4.2, "usage": {"output_tokens": 20}}))
sys.exit(0 if ok else 1)
'''


def _fake_cli(tmp_path: Path) -> str:
    script = tmp_path / "fake_claude.py"
    script.write_text(FAKE, encoding="utf-8")
    if sys.platform == "win32":
        exe = tmp_path / "claude.cmd"
        exe.write_text(f'@"{sys.executable}" "{script}" %*\n')
    else:
        exe = tmp_path / "claude"
        exe.write_text(f"#!{sys.executable}\n{FAKE}")
        exe.chmod(0o755)
    return str(exe)


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    lib = tmp_path / "lemo-opuscar"
    for slug, needs in (("watercolor", []), ("collage", ["image-generation"])):
        (lib / "styles" / slug).mkdir(parents=True)
        (lib / "styles" / slug / "STYLE.md").write_text(
            f"# {slug.title()} Brush — Style Prompt\n\n> A painted walk. More.\n",
            encoding="utf-8")
        (lib / "styles" / slug / "style.json").write_text(json.dumps({"needs": needs}))
    skill = tmp_path / "skill"
    (skill / "scripts").mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: lemo-opuscar\n---\n")
    (skill / "scripts" / "setup.sh").write_text("echo LIB=x\n")
    monkeypatch.setenv("FAKE_CLAUDE_SEEN", str(tmp_path / "seen.json"))
    monkeypatch.setenv("FAKE_FILM", str(SAMPLE))
    s = InstagramMCPSettings(
        _env_file=None, instagram_access_token=TOKEN, database_path=":memory:",
        agent_workspace=str(tmp_path / "ws"), agent_log_dir=str(tmp_path / "logs"),
        media_root=str(tmp_path / "media"), claude_bin=_fake_cli(tmp_path),
        lemo_library=str(lib), lemo_skill_dir=str(skill))
    monkeypatch.setattr(lemo, "get_settings", lambda: s)
    return s


@pytest.fixture
def judged(monkeypatch):
    """No worker in tests: the render + QC of the delivered film is judged at once."""
    verdict = {"status": "ready"}

    def wait(store, asset_id, wait_s, poll_s):
        if verdict["status"] == "failed":
            store.update_asset(asset_id, qc={"passed": False, "reasons": ["too dark"]})
        return transition(store, asset_id, verdict["status"], actor="worker")

    monkeypatch.setattr(film, "_wait_render", wait)
    return verdict


def _order(store, style="lemo:watercolor", text="Où partent les calories ?"):
    return work_orders.create_video(store, text, style)


def _flag(cmd, name):
    return cmd[cmd.index(name) + 1]


# --- guard: the command, workspace and environment never loosen ----------------------
def test_command_is_locked_down(cfg):
    ws = film.prepare_workspace(cfg, 7, "brief")
    cmd = film.build_command(cfg, ws)
    assert cmd[:2] == [cfg.claude_bin, "-p"]
    assert set(_flag(cmd, "--tools").split(",")) == TOOLS
    assert MUST_DISALLOW <= set(_flag(cmd, "--disallowedTools").split(","))
    allowed = _flag(cmd, "--allowedTools").split(",")
    assert [a for a in allowed if a.startswith(("Edit", "Write"))] == [
        f"Edit({runner._rule_path(ws)}/**)"]  # writes in its workspace only
    assert set(allowed) - {allowed[-1]} == {"Bash", "Read", "Glob", "Grep", "Skill"}
    assert "--strict-mcp-config" in cmd and "--mcp-config" not in cmd  # no MCP server
    assert _flag(cmd, "--permission-mode") == "dontAsk"
    assert _flag(cmd, "--permission-prompts") == "none"
    assert _flag(cmd, "--setting-sources") == "project"
    assert "--dangerously-skip-permissions" not in cmd and "bypassPermissions" not in cmd
    for f in ("--allowedTools", "--disallowedTools", "--tools", "--settings", "--add-dir",
              "--plugin-dir", "--setting-sources"):
        assert cmd.count(f) <= 1
    assert TOKEN not in " ".join(cmd)


def test_workspace_holds_brief_skill_and_deny_rules(cfg, tmp_path):
    ws = film.prepare_workspace(cfg, 7, "the brief")
    assert ws == (tmp_path / "ws" / "films" / "7").resolve()
    assert (ws / "BRIEF.md").read_text(encoding="utf-8") == "the brief"
    skills = ws / ".claude" / "skills"
    assert [p.name for p in skills.iterdir()] == ["lemo-opuscar"]
    assert (skills / "lemo-opuscar" / "scripts" / "setup.sh").is_file()
    deny = json.loads((ws / ".claude" / "settings.json").read_text())["permissions"]["deny"]
    assert "Read(//**/.env)" in deny


@pytest.mark.parametrize("where", [runner.REPO, runner.REPO / "agent"])
def test_workspace_inside_the_repo_is_refused(cfg, where):
    cfg.agent_workspace = str(where)
    with pytest.raises(runner.AgentError, match="outside|git repository"):
        film.prepare_workspace(cfg, 7, "brief")


def test_a_foreign_claude_folder_is_never_replaced(cfg, tmp_path):
    (tmp_path / "ws" / "films" / "7" / ".claude").mkdir(parents=True)
    with pytest.raises(runner.AgentError, match="not made by"):
        film.prepare_workspace(cfg, 7, "brief")


def test_missing_skill_is_a_clear_error(cfg, tmp_path):
    cfg.lemo_skill_dir = str(tmp_path / "nope")
    with pytest.raises(runner.AgentError, match="skill is not installed"):
        film.skill_dir(cfg)


def test_env_has_no_secret_and_no_env_file_name(cfg, tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("SOME_API_KEY=abc\n")
    monkeypatch.setattr(film, "ENV_FILE", env_file)
    monkeypatch.setenv("SOME_API_KEY", "abc")
    monkeypatch.setenv("HIDDEN_COPY", f"x{TOKEN}x")
    monkeypatch.setenv("IG_MCP_HOME", "D:/studio")
    env = film.film_env(cfg)
    assert "SOME_API_KEY" not in env and "HIDDEN_COPY" not in env
    assert not any(k.startswith("IG_MCP_") for k in env)
    assert not any(TOKEN in v for v in env.values())
    assert "PATH" in {k.upper() for k in env} and env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"
    assert env["LEMO_OPUSCAR_HOME"] == cfg.lemo_library


# --- orders in a Lemo style ----------------------------------------------------------
def test_lemo_styles_are_checked_in_the_library(store, cfg):
    assert _order(store)["style"] == "lemo:watercolor"
    for bad in ("lemo:nope", "lemo:../x", "lemo:"):
        with pytest.raises(ValueError, match="unknown Lemo-Opuscar style"):
            _order(store, bad)
    with pytest.raises(ValueError, match="générateur d'images"):
        _order(store, "lemo:collage")  # shown in the catalog, not selectable


def test_lemo_orders_never_reach_the_agent(store, cfg, settings):
    order = _order(store)
    assert work_orders.for_agent(store) == []
    settings.order_run_debounce_minutes = 0
    started = []
    assert schedule.order_run(store, settings, utcnow() + timedelta(minutes=5),
                              start=lambda *a: started.append(a), check=lambda s: None) is None
    assert not started
    work_orders.set_blocked(store, "agent reason")  # the agent's wait reason is not theirs
    assert work_orders.get_order(store, order["id"])["blocked_reason"] is None


def test_a_lemo_style_is_for_owner_mode_only(store, cfg):
    order = _order(store)
    with pytest.raises(ValueError, match="your own orders only"):
        work_orders.set_instruction(store, order["id"], "autre chose", mode="react")


def test_a_change_order_may_remake_a_video_in_a_lemo_style(store, cfg):
    idea = store.add_idea("motion", hook="h")
    asset = store.add_asset(idea["id"])
    order = work_orders.restyle(store, asset["id"], "lemo:watercolor")
    assert order["style"] == "lemo:watercolor" and "Watercolor Brush" in order["instruction"]


# --- runs with the fake CLI ----------------------------------------------------------
def test_a_film_reaches_the_inbox(store, cfg, judged, tmp_path):
    order = _order(store)
    run = film.run_film(store, cfg, order["id"])
    assert run["status"] == "succeeded" and run["playbook"] == film.PLAYBOOK
    assert run["usage"]["total_cost_usd"] == 4.2 and "film made" in run["summary"]
    seen = json.loads((tmp_path / "seen.json").read_text())
    assert Path(seen["cwd"]).resolve() == (tmp_path / "ws" / "films" / str(order["id"]))
    assert "watercolor" in seen["brief"] and "Où partent les calories ?" in seen["brief"]
    assert "$" not in seen["brief"].replace("$LIB", "")  # every placeholder filled in
    # 207: the film speaks through the runner's voice door, never the local service directly
    assert "http://127.0.0.1:" in seen["brief"] and "127.0.0.1:8766" not in seen["brief"]
    assert not any(TOKEN in v for v in seen["env"].values())
    done = work_orders.get_order(store, order["id"])
    assert done["status"] == "in_feed"
    asset = store.get_asset(done["asset_id"])
    assert asset["status"] == "ready" and asset["caption"].startswith("Où partent vos")
    rel = asset["recipe"]["inputs"]["source"]
    assert rel == f"films/{order['id']}/final.mp4"
    assert media.resolve(cfg.media_root, rel).read_bytes() == SAMPLE.read_bytes()
    assert store.list_render_jobs(asset_id=asset["id"])
    idea = store.get_idea(asset["idea_id"])
    assert idea["style"] == "lemo:watercolor" and idea["track"] == "motion"
    assert idea["hook"] == "Où partent vos calories ?"
    assert idea["citations"] == [{"url": "https://www.fao.org/x", "title": "FAO 2004"}]
    assert TOKEN not in Path(run["log_path"]).read_text()


def test_a_film_without_post_json_still_carries_the_ai_label(store, cfg, judged,
                                                              monkeypatch):
    from src.studio.publish import ai_generated

    monkeypatch.setenv("FAKE_CLAUDE", "bare")
    order = _order(store)
    assert film.run_film(store, cfg, order["id"])["status"] == "succeeded"
    asset = store.get_asset(work_orders.get_order(store, order["id"])["asset_id"])
    idea = store.get_idea(asset["idea_id"])
    assert idea["hook"] == order["instruction"] == asset["caption"]
    assert idea["script"] and ai_generated(asset, idea)
    assert asset["best_before"]


@pytest.mark.parametrize("mode, why", [("fail", "error_max_turns"),
                                       ("nothing", "delivered no film/final.mp4"),
                                       ("QC", "QC")])
def test_a_failed_film_skips_the_order_with_the_reason(store, cfg, judged, monkeypatch,
                                                       mode, why):
    monkeypatch.setenv("FAKE_CLAUDE", mode)
    if mode == "QC":
        judged["status"] = "failed"
    order = _order(store)
    run = film.run_film(store, cfg, order["id"])
    assert run["status"] == "failed" and why in run["summary"]
    done = work_orders.get_order(store, order["id"])
    assert done["status"] == "skipped" and why in done["skip_reason"]


def test_timeout_kills_the_film(store, cfg, judged, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE", "sleep")
    cfg.lemo_film_max_min = 0.05  # 3 s
    order = _order(store)
    run = film.run_film(store, cfg, order["id"])
    assert run["status"] == "failed" and "timed out" in run["summary"]
    assert work_orders.get_order(store, order["id"])["status"] == "skipped"
    assert store.running_agent_run(film.PLAYBOOK) is None


def test_one_film_at_a_time_and_a_daily_cap(store, cfg, judged):
    first, second = _order(store), _order(store, text="Les protéines")
    held = store.start_agent_run(film.PLAYBOOK, os.getpid())
    with pytest.raises(runner.AgentRunRefused):
        film.run_film(store, cfg, first["id"])
    store.finish_agent_run(held["id"], "succeeded")
    cfg.lemo_films_per_day = 2
    film.run_film(store, cfg, first["id"])
    with pytest.raises(runner.AgentError, match="films du jour"):
        film.run_film(store, cfg, second["id"])
    assert work_orders.get_order(store, second["id"])["status"] == "scheduled"


def test_no_film_limit_at_0_and_a_restart_kill_does_not_count(store, cfg):
    killed = store.start_agent_run(film.PLAYBOOK, os.getpid())
    store.finish_agent_run(killed["id"], "failed", summary=runner.DEAD_RUN)
    assert film.films_today(store, cfg, utcnow()) == 0
    for _ in range(5):
        done = store.start_agent_run(film.PLAYBOOK, os.getpid())
        store.finish_agent_run(done["id"], "succeeded")
    cfg.lemo_films_per_day = 0
    film.check_film(store, cfg, utcnow())  # no limit: no AgentError
    cfg.lemo_films_per_day = 5
    with pytest.raises(runner.AgentError, match="films du jour"):
        film.check_film(store, cfg, utcnow())
    cfg.lemo_films_per_day = 3


# --- the worker's catch-up -----------------------------------------------------------
def test_catch_up_hands_the_oldest_lemo_order_to_the_film_runner(store, cfg):
    first, _ = _order(store), _order(store, text="Les protéines")
    started = []
    assert schedule.film_run(store, cfg, utcnow(), start=lambda s, c, i: started.append(i),
                             check=lambda s: None) == first["id"]
    assert started == [first["id"]]


def test_catch_up_says_why_lemo_orders_wait(store, cfg):
    order = _order(store)
    cfg.lemo_films_per_day = 1
    done = store.start_agent_run(film.PLAYBOOK, os.getpid())
    store.finish_agent_run(done["id"], "succeeded")
    assert schedule.film_run(store, cfg, utcnow(), start=None, check=None) is None
    assert "films du jour" in work_orders.get_order(store, order["id"])["blocked_reason"]
    cfg.lemo_films_per_day = 3

    def signed_out(s):
        raise runner.AgentError("not signed in")

    assert schedule.film_run(store, cfg, utcnow(), start=None, check=signed_out) is None
    assert "not signed in" in work_orders.get_order(store, order["id"])["blocked_reason"]
    assert store.get_state("order_preflight_failed_at")


def test_an_order_a_dead_film_left_is_skipped(store, cfg):
    order = _order(store)
    idea = store.add_idea("motion", hook="h", style="lemo:watercolor")
    work_orders.start(store, order["id"], idea)
    store.set_state("order_preflight_failed_at", to_iso(utcnow()))  # nothing new starts
    assert schedule.film_run(store, cfg, utcnow(), start=None) is None
    done = work_orders.get_order(store, order["id"])
    assert done["status"] == "skipped" and done["skip_reason"] == film.INTERRUPTED


def test_the_film_brief_is_not_an_agent_playbook(cfg):
    from src.agent.runs import list_playbooks

    assert film.PLAYBOOK not in list_playbooks()
    with pytest.raises(runner.AgentError, match="unknown playbook"):
        runner._playbook_file(film.PLAYBOOK, runner.AGENT_DIR)


# --- the GPU lock wrapper ------------------------------------------------------------
def test_gpu_run_runs_the_command_under_the_lock_and_returns_its_code(capsys):
    assert gpu_run.main(["--", sys.executable, "-c", "raise SystemExit(3)"]) == 3
    assert gpu_run.main([]) == 2 and "usage" in capsys.readouterr().err


# --- step 198: the film waits through its render's machine backoff ----------------------
def _waited(store, monkeypatch, events, wait_s=100, poll_s=10):
    """_wait_render on a fake clock; events: {t: change(store, asset_id, job_id)} applied
    once the clock reaches t. Returns (the asset it returned, the time it returned at)."""
    from types import SimpleNamespace

    asset = store.add_asset(store.add_idea("motion")["id"])
    job = store.add_render_job(asset["id"], f"film{asset['id']}")["id"]
    clock = {"t": 0.0}

    def sleep(s):
        clock["t"] += s
        for at in sorted(t for t in events if t <= clock["t"]):
            events.pop(at)(store, asset["id"], job)

    monkeypatch.setattr(film, "time", SimpleNamespace(monotonic=lambda: clock["t"], sleep=sleep))
    return film._wait_render(store, asset["id"], wait_s, poll_s), clock["t"]


def _machine(n):  # render.machine_wait's mark on the job
    return lambda store, a, j: store.update_render_job(
        j, failure=f"machine {n}/6: TTSError: no answer in time")


def _to(status):  # the worker judged the render
    return lambda store, a, j: transition(store, a, status, actor="worker")


def test_the_film_keeps_waiting_while_its_render_waits_for_the_machine(store, monkeypatch):
    got, at = _waited(store, monkeypatch, {90: _machine(1), 180: _machine(2), 270: _to("ready")})
    assert got["status"] == "ready" and at == 270  # past the first wait (100 here)


def test_a_video_failure_still_ends_the_films_wait_at_once(store, monkeypatch):
    got, at = _waited(store, monkeypatch, {30: _to("failed")})
    assert got["status"] == "failed" and at == 30


def test_a_render_that_never_ends_still_times_the_film_out(store, monkeypatch):
    got, at = _waited(store, monkeypatch, {})
    assert got["status"] == "rendering" and at == 100
    got, at = _waited(store, monkeypatch, {50: _machine(1)})  # one restart, not one per poll
    assert got["status"] == "rendering" and at == 150


# --- 202: a sent-back film is remade by the film runner; orphan orders come back ------
def _sent_back_film(store, cfg):
    idea = store.add_idea("motion", hook="Œuf ou yaourt ?", style="lemo:watercolor")
    asset = store.add_asset(idea["id"], recipe={"kind": "ffmpeg", "recipe": {"version": 1,
                                                "ops": []}, "inputs": {"source": "f.mp4"}})
    transition(store, asset["id"], "ready", actor="worker")
    return add_comment(store, asset["id"], text="trop lent, pas de hook",
                       wants_changes=True)["asset"]["id"]


def test_a_sent_back_film_is_remade_in_its_own_look(store, cfg, judged):
    """Was: the AI could only answer « waiting » for a film (no template), forever."""
    aid = _sent_back_film(store, cfg)
    first = feedback.decide_revision(store, aid, "remade", "un hook qui bouge")["order"]
    got = feedback.decide_revision(store, aid, "remade", "hook qui bouge, plus rapide")
    order, d = got["order"], got["asset"]["agent_decision"]
    assert (order["style"], order["source"], order["from_asset_id"]) == (
        "lemo:watercolor", "change", aid)
    assert "Même film" in order["instruction"] and "plus rapide" in order["instruction"]
    assert (d["kind"], d["order_id"], d["text"]) == ("remade", order["id"],
                                                    "Refaite en Watercolor Brush")
    # never two remakes of one video: the earlier decision's order is replaced
    assert work_orders.get_order(store, first["id"])["status"] == "skipped"
    assert film.next_order(store)["id"] == order["id"]  # the film runner's, not the agent's
    assert not work_orders.for_agent(store)
    assert film.run_film(store, cfg, order["id"])["status"] == "succeeded"
    assert store.get_asset(aid)["status"] == "archived"  # the remake replaced it
    # a template video still re-renders itself: no order
    other = add_comment(store, _asset(store), text="x", wants_changes=True)["asset"]["id"]
    assert feedback.decide_revision(store, other, "remade", "x")["order"] is None
    with pytest.raises(ValueError, match="not a Lemo film"):
        work_orders.refilm(store, other, "x")


def test_a_video_restyled_into_a_film_is_made_by_the_film_runner(store, cfg, judged):
    """Was: orders 63 and 66, the AI wrote their idea itself (in_production, no film), and
    the film runner closed them as interrupted; 64 and 65 it skipped as duplicates."""
    aid = add_comment(store, _asset(store), text="plus de scènes", wants_changes=True
                      )["asset"]["id"]
    order = feedback.decide_revision(store, aid, "restyled", "un vrai film",
                                     style="lemo:watercolor")["order"]
    with pytest.raises(ValueError, match="film runner makes it"):
        production.create_idea(store, cfg, "motion", hook="h", work_order_id=order["id"])
    with pytest.raises(ValueError, match="film runner makes it"):
        work_orders.skip_for_agent(store, order["id"], "doublon")
    assert work_orders.get_order(store, order["id"])["status"] == "scheduled"
    assert film.close_orphans(store) == 0  # nothing to mistake for a dead film
    assert film.next_order(store)["id"] == order["id"]
    assert film.run_film(store, cfg, order["id"])["status"] == "succeeded"
    assert store.get_asset(aid)["status"] == "archived"  # the film replaced it


def test_an_order_a_dead_run_left_half_made_comes_back(store, cfg):
    """Was: order 51, in_production since its run was killed, with nothing ever made."""

    def started(order, *, made=False):
        idea = store.add_idea("motion", hook="h", style=order["style"])
        work_orders.start(store, order["id"], idea)
        if made:
            store.add_asset(idea["id"])
        return order["id"]

    old = to_iso(utcnow() - timedelta(hours=3))
    orphan = started(work_orders.create_video(store, "un sujet"))
    fresh = started(work_orders.create_video(store, "un autre"))
    made = started(work_orders.create_video(store, "fait"), made=True)
    films = started(_order(store))
    aid = _sent_back_film(store, cfg)
    replaced = started(work_orders.restyle(store, aid, None, "x"))  # an earlier decision's
    feedback.decide_revision(store, aid, "waiting", "un rendu")  # another decision since
    # was order 31: its video got another restyle since, then was archived
    gone = _sent_back_film(store, cfg)
    stale = started(work_orders.restyle(store, gone, None, "x"))
    feedback.decide_revision(store, gone, "remade", "y")  # a newer order
    transition(store, gone, "archived", actor="system")
    # an owner's own change order (no agent decision) on an archived video comes back
    mine = started(work_orders.restyle(store, _asset(store), "lemo:watercolor"))
    with store._tx() as c:
        c.execute("UPDATE work_orders SET updated_at=?, style=NULL WHERE id=?", (old, mine))
        c.execute("UPDATE work_orders SET updated_at=? WHERE id IN (?,?,?,?,?)",
                  (old, orphan, made, films, replaced, stale))
    got = work_orders.recover(store, utcnow() - timedelta(minutes=90))
    assert got == {"rescheduled": [orphan, mine], "skipped": [replaced, stale]}
    back = work_orders.get_order(store, orphan)
    assert (back["status"], back["idea_id"]) == ("scheduled", None)
    assert "autre décision" in work_orders.get_order(store, replaced)["skip_reason"]
    for oid in (fresh, made, films):
        assert work_orders.get_order(store, oid)["status"] == "in_production"


def test_a_films_voice_engine_reaches_its_badge_and_the_bell(store, cfg, tmp_path):
    from src.studio import alerts

    ws = tmp_path / "w"
    (ws / lemo.FILM_DIR).mkdir(parents=True)
    (ws / lemo.FILM_DIR / "final.mp4").write_bytes(SAMPLE.read_bytes())
    (ws / lemo.VOICE_TAKES).write_text(json.dumps([  # the voice door's takes (film_voice)
        {"voice": "el_liam", "engine": "elevenlabs", "fallback": None},
        {"voice": "conteur", "engine": "local", "fallback": "ElevenLabs credits: 0 left"}]))
    order = _order(store)
    idea = store.add_idea("motion", hook="h", style=order["style"])
    asset = lemo.register_film(store, cfg, order, idea, ws)["asset"]
    assert asset["recipe"]["voiced_by"] == {"engine": "http", "voice": "conteur",
                                            "fallback": "ElevenLabs credits: 0 left"}
    raised = store.get_state(alerts.RAISED_KEY).values()
    assert [a["kind"] for a in raised] == ["tts_fallback"]


def test_a_refilm_brief_quotes_the_owners_words(store, cfg, judged, tmp_path):
    """Was: video 76, only the AI's one-line paraphrase reached the film."""
    aid = _sent_back_film(store, cfg)
    order = feedback.decide_revision(store, aid, "remade", "un hook")["order"]
    film.run_film(store, cfg, order["id"])
    brief = json.loads((tmp_path / "seen.json").read_text())["brief"]
    assert "his own words" in brief and "> trop lent, pas de hook" in brief


def test_instagram_music_is_never_promised_by_a_film(store, cfg):
    """Was: remake 78 of video 76 had no music: a film can't take an Instagram track."""
    aid = _sent_back_film(store, cfg)
    add_comment(store, aid, text="do again with new voice and music from instagram",
                wants_changes=True)
    for decision, style in (("remade", None), ("restyled", "lemo:watercolor")):
        other = aid if decision == "remade" else add_comment(
            store, _asset(store), text="musique Instagram stp", wants_changes=True
        )["asset"]["id"]
        with pytest.raises(ValueError, match="cannot take an Instagram track"):
            feedback.decide_revision(store, other, decision, "x", style=style)
    assert not work_orders.list_orders(store)


def test_a_failed_refilm_leaves_the_video_waiting_and_wakes_the_light_run(
        store, cfg, judged, monkeypatch):
    """Was: the card kept « Refaite en … » and nothing woke the AI to decide again."""
    monkeypatch.setenv("FAKE_CLAUDE", "fail")
    aid = _sent_back_film(store, cfg)
    order = feedback.decide_revision(store, aid, "remade", "un hook")["order"]
    with store._tx() as c:  # the run that decided is long past: it saw the comment
        c.execute("UPDATE feedback SET updated_at='2000-01-01T00:00:00+00:00'")
    film.run_film(store, cfg, order["id"])
    d = store.get_asset(aid)["agent_decision"]
    assert (d["kind"], d["order_id"]) == ("waiting", order["id"])
    assert "le film n'a pas abouti" in d["text"]
    with store._tx() as c:
        assert c.execute(schedule._NEWEST_WORK).fetchone()[0] == d["at"]
