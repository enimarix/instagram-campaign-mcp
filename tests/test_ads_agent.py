"""Steps 096 and 126: the agent's ads tools (propose, launch, stop, read), the proposal
cap, the `weekly-ads` work packet, and the proof that money moves only through the guard."""

import ast
import json
import re
from pathlib import Path

import pytest

import src.instagram_mcp_server as srv
from src import settings_overrides
from src.ads import budget, tests
from src.agent import packet
from src.learning.learnings import add_learning

from .test_ads_tests import (  # noqa: F401 - meta: the Meta fixture
    CREATIVE,
    _audit,
    _post,
    _posts,
    _settings,
    _status_calls,
    meta,
)

SRC = Path(srv.__file__).parent
ADS_TOOLS = {"list_ad_winners", "propose_ad_test", "launch_ad_test", "stop_ad_test",
             "list_ad_tests", "get_ad_test_results"}


@pytest.fixture
def graph(meta):  # noqa: F811 - Meta (respx), as in test_ads_tests
    return meta


@pytest.fixture
def tools(store, monkeypatch):
    """Point the MCP server at the test store; returns a settings setter."""
    monkeypatch.setattr(srv, "store", lambda: store)

    def use(settings):
        monkeypatch.setattr(srv, "get_settings", lambda: settings)
        return settings

    return use


def _winners(monkeypatch, media=("111", "222")):
    rows = [({"media_id": m, "permalink": f"p/{m}", "posted_at": "t", "caption": "c"},
             {"verdict": "winner", "group": "REELS", "engagement_index": 2.0}) for m in media]
    monkeypatch.setattr(tests, "scored_posts", lambda store, settings: rows)


async def _agent_proposal(store, **kw):
    for v in CREATIVE:
        if not store.get_label(v["media_id"]):
            _post(store, v["media_id"])
    return await srv.propose_ad_test("Post 111's hook gets a higher CTR than post 222's",
                                     "creative", CREATIVE, **kw)


# --- the tools ---------------------------------------------------------------------------
async def test_every_tool_says_ads_not_configured_and_sends_nothing(store, tools, graph):
    tools(_settings(meta_ad_account_id=None))
    outs = [await srv.list_ad_winners(), await srv.list_ad_tests(),
            await srv.get_ad_test_results(1), await _agent_proposal(store),
            await srv.launch_ad_test(1), await srv.stop_ad_test(1, "why")]
    for out in outs:
        assert out["error"] == "ads_not_configured" and "META_AD_ACCOUNT_ID" in out["message"]
    assert not graph.calls and tests.list_tests(store, _settings()) == []


async def test_tools_propose_as_agent_and_read(store, tools, graph, monkeypatch):
    tools(_settings())
    _winners(monkeypatch)
    _post(store, "111")
    assert [w["media_id"] for w in (await srv.list_ad_winners())["winners"]] == ["111"]
    t = await _agent_proposal(store)
    assert t["status"] == "proposed" and t["proposed_by"] == "agent"
    assert t["summary"].startswith("To see a 20% lift you need about")
    assert [x["id"] for x in (await srv.list_ad_tests())["tests"]] == [t["id"]]
    assert (await srv.list_ad_tests("running"))["tests"] == []
    res = await srv.get_ad_test_results(t["id"])
    assert res["id"] == t["id"] and res["spend"]["counted"] == "0" and res["entities"] == []
    with pytest.raises(srv.ToolError):
        await srv.get_ad_test_results(999)
    with pytest.raises(srv.ToolError, match="^invalid: variants must differ in audience"):
        await srv.propose_ad_test("x", "audience", CREATIVE)
    with pytest.raises(srv.ToolError, match="at most 500"):
        await srv.propose_ad_test("x" * 501, "creative", CREATIVE)
    assert not [c for c in graph.calls if c.request.method != "GET"]  # reads only


async def test_agent_proposals_are_capped_and_owner_ones_are_not(store, tools, graph):
    s = tools(_settings())
    owner = await _agent_proposal(store)  # through the tool: agent
    store._update("ad_tests", ("proposed_by",), owner["id"], {"proposed_by": "owner"})
    ids = [(await _agent_proposal(store))["id"] for _ in range(tests.MAX_AGENT_PROPOSALS)]
    sent = len(graph.calls)
    with pytest.raises(srv.ToolError, match="^cap: 3 agent proposals already wait"):
        await _agent_proposal(store)
    with pytest.raises(tests.AdTestRefused, match="MAX_AGENT_PROPOSALS"):  # the service
        await tests.propose(store, s, hypothesis="h", variable="creative",
                            variants=CREATIVE, proposed_by="agent")
    assert len(graph.calls) == sent  # refused before any request
    await tests.propose(store, s, hypothesis="h", variable="creative", variants=CREATIVE)
    store._update("ad_tests", ("status",), ids[0], {"status": "cancelled"})  # owner dropped
    assert (await _agent_proposal(store))["proposed_by"] == "agent"


# --- launch and stop --------------------------------------------------------------------
def _caps(store, **values):
    """The owner changes a setting in the website (another process's settings object)."""
    settings_overrides.update(store, _settings(), values, confirmed=True)


async def test_agent_launch_within_caps_creates_paused_then_activates(store, tools, graph):
    tools(_settings())
    t = await _agent_proposal(store)
    out = await srv.launch_ad_test(t["id"])
    assert out["status"] == "running" and out["budget_total"] == "426.94"  # the need
    creates = [c for c in _posts(graph) if c.request.url.path.startswith("/v25.0/act_42/")]
    assert _posts(graph)[:8] == creates and {s for _, s in _status_calls(graph)} == {"ACTIVE"}
    assert all(json.loads(c.request.content).get("status", "PAUSED") == "PAUSED"
               for c in creates)
    rows = budget.audit_log(store, limit=10)["rows"]
    assert [(r["action"], r["actor"]) for r in reversed(rows)] == [
        ("propose", "agent"), ("approve", "agent"), ("activate", "agent"),
        ("activate", "agent")]
    [shown] = (await srv.list_ad_tests())["tests"]
    assert shown["launched_by"] == "agent" and shown["proposed_by"] == "agent"


async def test_agent_budget_is_capped_by_the_current_caps(store, tools, graph):
    s = tools(_settings())
    t = await _agent_proposal(store)
    _caps(store, ads_test_cap="300")  # lowered in the website a moment ago
    sent = len(graph.calls)
    with pytest.raises(srv.ToolError, match="^underpowered: budget 300.00 is below the 426"):
        await srv.launch_ad_test(t["id"])
    assert s.ads_test_cap == 300 and len(graph.calls) == sent  # read fresh, nothing sent
    _caps(store, ads_test_cap="0", ads_daily_cap="0")
    with pytest.raises(srv.ToolError, match="^underpowered: the caps leave nothing"):
        await srv.launch_ad_test(t["id"])
    with pytest.raises(tests.AdTestRefused, match="the need and the caps"):
        await tests.launch(store, s, t["id"], "5000", actor="agent")  # no budget of its own
    with pytest.raises(tests.AdTestRefused, match="the need and the caps"):
        await tests.launch(store, s, t["id"], actor="agent", underpowered_ok=True)
    assert len(graph.calls) == sent and store._get("ad_tests", t["id"])["status"] == "proposed"


async def test_agent_launch_refused_when_killed_or_at_the_max_running(store, tools, graph):
    tools(_settings())
    first, second = [(await _agent_proposal(store))["id"] for _ in range(2)]
    budget.kill(store, "owner pressed Stop all ads")
    with pytest.raises(srv.ToolError, match="^killed"):
        await srv.launch_ad_test(first)
    assert not _posts(graph)
    budget.unkill(store)  # the owner, in the website
    _caps(store, ads_max_running_tests=1, ads_lifetime_cap="5000", ads_daily_cap="1000")
    await srv.launch_ad_test(first)
    sent = len(graph.calls)
    with pytest.raises(srv.ToolError, match="^max_running: 1 tests already run"):
        await srv.launch_ad_test(second)
    assert len(graph.calls) == sent
    with pytest.raises(tests.AdTestRefused) as e:  # the transaction's own count, too
        tests._set_status(store, second, "approved", expect=("proposed",), max_running=1)
    assert e.value.code == "max_running"


async def test_agent_launch_refused_for_posts_no_longer_advertisable(store, tools, graph):
    tools(_settings())
    t = await _agent_proposal(store)
    asset = store.get_label("111")["asset_id"]
    with store._tx() as c:
        c.execute("UPDATE assets SET status='scheduled' WHERE id=?", (asset,))
    with pytest.raises(srv.ToolError, match="^not_published: post 111's video is scheduled"):
        await srv.launch_ad_test(t["id"])
    src = store.add_source("x", rights_basis="commentary", author="a")["id"]
    with store._tx() as c:
        c.execute("UPDATE assets SET status='published' WHERE id=?", (asset,))
        c.execute("UPDATE ideas SET source_id=?, track='remix' WHERE id=(SELECT idea_id FROM"
                  " assets WHERE id=?)", (src, asset))
    with pytest.raises(srv.ToolError, match="^rights"):
        await srv.launch_ad_test(t["id"])
    assert not _posts(graph)


async def test_propose_refuses_posts_not_published(store, tools, graph):
    tools(_settings())
    idea = store.add_idea("motion")
    store.label_post("111", asset_id=store.add_asset(idea["id"])["id"])  # still rendering
    _post(store, "222")
    with pytest.raises(srv.ToolError, match="^not_published"):
        await _agent_proposal(store)


async def test_agent_does_not_launch_the_owners_proposals(store, tools, graph):
    s = tools(_settings())
    for v in CREATIVE:
        _post(store, v["media_id"])
    t = await tests.propose(store, s, hypothesis="h", variable="creative", variants=CREATIVE)
    with pytest.raises(srv.ToolError, match="^owner_test"):
        await srv.launch_ad_test(t["id"])
    with pytest.raises(srv.ToolError):
        await srv.launch_ad_test(999)
    assert not _posts(graph)


async def test_agent_stop_pauses_and_is_audited(store, tools, graph):
    tools(_settings())
    t = await _agent_proposal(store)
    await srv.launch_ad_test(t["id"])
    graph.reset()
    with pytest.raises(srv.ToolError, match="^invalid: a reason"):
        await srv.stop_ad_test(t["id"], " ")
    out = await srv.stop_ad_test(t["id"], "Meta rejected variant B")
    assert out["status"] == "cancelled" and out["reason"] == (
        "stopped by the AI: Meta rejected variant B")
    assert {s for _, s in _status_calls(graph)} == {"PAUSED"} and len(_status_calls(graph)) == 6
    assert budget.audit_log(store, limit=1)["rows"][0]["actor"] == "agent"
    assert _audit(store)[-1] == "cancel"
    with pytest.raises(srv.ToolError, match="^status"):
        await srv.stop_ad_test(t["id"], "again")


# --- money only through the guard --------------------------------------------------------
# The two gates an agent tool may pass through; the walk does not enter them (inside, the
# guard does its work: tests/test_ads_tests.py and the tests above).
GATES = {("tests.py", "launch"), ("tests.py", "cancel")}
# Identifiers no function an agent tool reaches outside a gate may use (src/ads and src/).
FORBIDDEN = {"AdsWriter", "authorize_spend", "unkill", "kill", "enforce_kill", "activate",
             "release", "report_spend", "create_paused_promotion", "pause", "_pause_active",
             "_set_status"}
MONEY = re.compile(r"approve|activat|kill|budget|cap|spend|promot|writer|delete|setting")


def _module(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    funcs = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef,
                                                             ast.AsyncFunctionDef))}
    aliases = {}  # local name -> (file, function) or (module file, None)
    for n in tree.body:
        if isinstance(n, ast.ImportFrom) and n.level:
            base = path.parents[n.level - 1].joinpath(*(n.module or "").split("."))
            for a in n.names:
                local = a.asname or a.name
                if (base / f"{a.name}.py").is_file():
                    aliases[local] = (base / f"{a.name}.py", None)
                elif base.with_suffix(".py").is_file():
                    aliases[local] = (base.with_suffix(".py"), a.name)
    return funcs, aliases


def reach(path, name, gates=frozenset()):
    """Every (file, function) under src/ads (and src/) reachable from `name`, and the
    identifiers they use. Follows calls and references (a function passed along); a gate
    is recorded as reached but not entered."""
    seen, names, todo = set(), set(), [(path, name)]
    while todo:
        key = todo.pop()
        if key in seen or key[0].parent.name not in ("ads", "src") or key[1] is None:
            continue
        seen.add(key)
        if (key[0].name, key[1]) in gates:
            continue
        funcs, aliases = _module(key[0])
        if key[1] not in funcs:  # a class or a constant
            continue
        for node in ast.walk(funcs[key[1]]):
            if isinstance(node, ast.Name):
                names.add(node.id)
                if node.id in funcs:
                    todo.append((key[0], node.id))
                elif node.id in aliases:
                    todo.append(aliases[node.id])
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
                base = getattr(node.value, "id", None)
                if base in aliases and aliases[base][1] is None:
                    todo.append((aliases[base][0], node.attr))
    return {(p.name, f) for p, f in seen}, names


def violations(path, name):
    """What `name` reaches outside the gates that moves money or changes a setting."""
    reached, names = reach(path, name, GATES)
    return ({f"uses {n}" for n in names & FORBIDDEN}
            | {f"reaches {f}.{fn}" for f, fn in reached
               if (f, fn) in {("settings_overrides.py", "update"), ("sync.py", "sync"),
                              ("budget.py", "unkill")}})


async def test_agent_money_only_through_the_guard():
    agent = {t.name for t in await srv.build_server("agent").list_tools()}
    assert ADS_TOOLS <= agent
    assert not {n for n in agent if MONEY.search(n)}, "a tool name with money power"
    gated = set()
    for tool in sorted(agent):
        assert not violations(SRC / "instagram_mcp_server.py", tool), tool
        gated |= reach(SRC / "instagram_mcp_server.py", tool, GATES)[0] & GATES
    assert gated == GATES  # launch and stop do pass the gates: the walk is not vacuous
    reached, _ = reach(SRC / "instagram_mcp_server.py", "launch_ad_test", GATES)
    assert {("agent.py", "launch"), ("tests.py", "launch")} <= reached
    assert ("sync.py", "results") in reach(SRC / "instagram_mcp_server.py",
                                           "get_ad_test_results", GATES)[0]


def test_the_walk_catches_money_power(tmp_path):
    """The self-check: each path the test above forbids makes `violations` non-empty."""
    ads = SRC / "ads"
    rogue = tmp_path / "ads" / "rogue.py"  # an agent helper that skips the gates
    rogue.parent.mkdir()
    rogue.write_text("def rogue(store, settings, w):\n"
                     "    authorize_spend(store, settings, 1, reason='x')\n"
                     "    unkill(store)\n", encoding="utf-8")
    assert violations(rogue, "rogue") == {"uses authorize_spend", "uses unkill"}
    assert "uses AdsWriter" in violations(ads / "sync.py", "sync")
    assert "uses AdsWriter" in violations(ads / "promote.py", "create_paused_promotion")
    assert "reaches budget.py.unkill" in violations(ads / "budget.py", "unkill")
    assert "reaches settings_overrides.py.update" in violations(SRC / "settings_overrides.py",
                                                                 "update")
    # the gate shields exactly this: launch's insides spend
    assert {"activate", "AdsWriter", "authorize_spend"} <= reach(ads / "tests.py", "launch")[1]
    assert violations(ads / "tests.py", "launch") == set()


def test_only_known_modules_import_ads():
    """Agent tools reach src/ads through the server only: another module importing it
    would be a path the walk above does not follow."""
    pattern = re.compile(r"^from \.+ads\b|^from \.+ import .*\bads\b", re.M)
    importers = {str(p.relative_to(SRC)).replace("\\", "/") for p in SRC.rglob("*.py")
                 if p.parent.name != "ads" and pattern.search(p.read_text(encoding="utf-8"))}
    assert importers <= {"instagram_mcp_server.py", "agent/packet.py", "api/ads.py",
                         "worker.py"}, importers
    assert "instagram_mcp_server.py" in importers  # the pattern still matches


# --- the work packet ---------------------------------------------------------------------
def _finish(store, test_id, status="winner"):
    ev = {"status": status, "winner": "A" if status == "winner" else None,
          "lift": {"vs": "B", "value": 0.3, "ci_low": 0.1, "ci_high": 0.5} if status ==
          "winner" else None, "p_values": {"B": 0.01}, "variants": {}}
    store._update("ad_tests", ("status", "result"), test_id,
                  {"status": "finished", "result": {"evaluation": ev}})


async def test_weekly_ads_packet(store, tools, graph, monkeypatch, tmp_path):
    out = packet.write_packet(store, _settings(meta_ad_account_id=None), "weekly-ads",
                              tmp_path)
    assert out["skip"] and out["manifest"]["run_kind"] == "ads"
    assert set(out["manifest"]["sections"]) == {"ads"}
    assert json.loads((tmp_path / "work" / "ads.json").read_bytes())["configured"] is False

    s = tools(_settings())
    assert packet.write_packet(store, s, "weekly-ads", tmp_path)["skip"]  # nothing to do
    _winners(monkeypatch, ("111",))
    done, still = (await _agent_proposal(store))["id"], (await _agent_proposal(store))["id"]
    _finish(store, done)
    out = packet.write_packet(store, s, "weekly-ads", tmp_path)
    data = json.loads((tmp_path / "work" / "ads.json").read_bytes())
    # a test to learn, a winner, a proposal to launch (2 more may run)
    assert not out["skip"] and out["manifest"]["sections"]["ads"]["count"] == 3
    assert data["launches_left"] == 2 and [t["launched_by"] for t in data["open_tests"]] == [None]
    assert data["proposals_left"] == 2 and [w["media_id"] for w in data["winners"]] == ["111"]
    assert [t["id"] for t in data["open_tests"]] == [still]
    [learn] = data["to_learn"]
    assert learn["id"] == done and learn["evaluation"]["lift"]["ci_low"] == 0.1
    assert learn["primary_metric"] == "ctr"

    add_learning(store, "Post 111's hook wins on CTR", "hypothesis", "ads",
                 evidence=[{"test_id": done, "metric": "ctr", "lift": 0.3}])
    await _agent_proposal(store)
    await _agent_proposal(store)  # 3 waiting: no room, so no winners either
    out = packet.write_packet(store, s, "weekly-ads", tmp_path)
    data = json.loads((tmp_path / "work" / "ads.json").read_bytes())
    assert out["manifest"]["sections"]["ads"]["count"] == 3  # the 3 proposals to launch
    assert data["to_learn"] == [] and data["winners"] == [] and data["proposals_left"] == 0
    s.ads_max_running_tests = 0  # as if the most tests at once already ran
    assert packet.write_packet(store, s, "weekly-ads", tmp_path)["skip"]  # no room to launch


def test_daily_produce_packet_has_no_ads_section(store, tmp_path):
    out = packet.write_packet(store, _settings(), "daily-produce", tmp_path)
    assert "ads" not in out["manifest"]["sections"]
