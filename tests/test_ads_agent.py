"""Step 096: the agent's ads tools (propose and read only), the proposal cap, the
`weekly-ads` work packet, and the proof that no agent tool reaches money power."""

import ast
import json
import re
from pathlib import Path

import pytest

import src.instagram_mcp_server as srv
from src.ads import tests
from src.agent import packet
from src.learning.learnings import add_learning

from .test_ads_tests import CREATIVE, _post, _settings, meta  # noqa: F401 - the Meta fixture

SRC = Path(srv.__file__).parent
ADS_TOOLS = {"list_ad_winners", "propose_ad_test", "list_ad_tests", "get_ad_test_results"}


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
            await srv.get_ad_test_results(1), await _agent_proposal(store)]
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


# --- no money power ----------------------------------------------------------------------
MONEY = re.compile(r"approve|activat|launch|cancel|kill|budget|cap|spend|pause|promot|"
                   r"writer|delete")
# Identifiers no function an agent tool reaches may use (src/ads, transitively).
FORBIDDEN = {"approve", "cancel", "activate", "unkill", "kill", "enforce_kill", "AdsWriter",
             "authorize_spend", "release", "report_spend", "create_paused_promotion", "pause",
             "_pause_active", "_set_status"}


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


def reach(path, name):
    """Every (file, function) under src/ads (and the server) reachable from `name`, and
    the identifiers they use. Follows calls and references (a function passed along)."""
    seen, names, todo = set(), set(), [(path, name)]
    while todo:
        key = todo.pop()
        if key in seen or key[0].parent.name not in ("ads", "src") or key[1] is None:
            continue
        seen.add(key)
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


async def test_agent_profile_has_no_money_power():
    agent = {t.name for t in await srv.build_server("agent").list_tools()}
    assert ADS_TOOLS <= agent
    assert not {n for n in agent if MONEY.search(n)}, "a tool name with money power"
    for tool in sorted(agent):
        reached, names = reach(SRC / "instagram_mcp_server.py", tool)
        assert not names & FORBIDDEN, (tool, names & FORBIDDEN)
        assert ("sync.py", "sync") not in reached, tool
    reached, _ = reach(SRC / "instagram_mcp_server.py", "propose_ad_test")
    assert {("agent.py", "propose"), ("tests.py", "propose")} <= reached  # not vacuous
    assert ("sync.py", "results") in reach(SRC / "instagram_mcp_server.py",
                                           "get_ad_test_results")[0]


def test_the_walk_catches_money_power():
    assert {"activate", "AdsWriter"} <= reach(SRC / "ads" / "tests.py", "approve")[1]
    assert "AdsWriter" in reach(SRC / "ads" / "sync.py", "sync")[1]


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
    assert not out["skip"] and out["manifest"]["sections"]["ads"]["count"] == 2
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
    assert out["skip"] and data["to_learn"] == [] and data["winners"] == []
    assert data["proposals_left"] == 0


def test_daily_produce_packet_has_no_ads_section(store, tmp_path):
    out = packet.write_packet(store, _settings(), "daily-produce", tmp_path)
    assert "ads" not in out["manifest"]["sections"]
