"""Agent runs for the website's Agent page (060): list, log tail, start a run detached.

The run itself is `ig-campaign agent run <playbook>` (runner.py), started as its own
process: a 90-minute run must not block or die with a web request. The runner takes the
lock and writes the `agent_runs` row.
"""

from __future__ import annotations

import subprocess
import sys
from collections import deque
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..config import InstagramMCPSettings
from ..store import CampaignStore, parse_iso, utcnow
from .runner import AGENT_DIR, REPO, _playbook_file, check_lock


def list_playbooks(agent_dir: Optional[Path] = None) -> List[str]:
    books = (agent_dir or AGENT_DIR) / "playbooks"
    return sorted(p.stem for p in books.glob("*.md") if p.name != "README.md")


def _compact(run: Dict[str, Any]) -> Dict[str, Any]:
    usage = run.get("usage") or {}
    end = parse_iso(run["finished_at"]) if run["finished_at"] else utcnow()
    return {
        **{k: run[k] for k in ("id", "playbook", "status", "started_at", "finished_at",
                               "summary")},
        "duration_s": round((end - parse_iso(run["started_at"])).total_seconds()),
        "num_turns": usage.get("num_turns"),
        "cost_usd": usage.get("total_cost_usd"),
        "permission_denials": usage.get("permission_denials"),
        "has_log": bool(run["log_path"]),
    }


def list_runs(store: CampaignStore, limit: int = 50) -> List[Dict[str, Any]]:
    """Newest first; a running run's duration counts up to now."""
    return [_compact(r) for r in store.list_agent_runs(limit=limit)]


def log_tail(store: CampaignStore, settings: InstagramMCPSettings, run_id: int,
             lines: int = 60) -> Dict[str, Any]:
    """The last lines of a run's log (secret-redacted by the runner). KeyError: no run or no
    log yet; PermissionError: the stored path is outside `agent_log_dir`."""
    run = store._get("agent_runs", run_id)  # KeyError if missing
    if not run["log_path"]:
        raise KeyError(f"agent run {run_id} has no log yet")
    path = Path(run["log_path"]).resolve()
    if not path.is_relative_to(Path(settings.agent_log_dir).resolve()):
        raise PermissionError(f"log of run {run_id} is outside the agent log folder")
    if not path.is_file():
        raise KeyError(f"log of run {run_id} is gone")
    with path.open(encoding="utf-8", errors="replace") as f:
        tail = deque(f, maxlen=lines)
    return {"id": run_id, "lines": [line.rstrip("\n") for line in tail]}


def start_run(store: CampaignStore, settings: InstagramMCPSettings, playbook: str, *,
              popen: Optional[Callable[..., Any]] = None,
              agent_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Start `agent run <playbook>` detached. AgentError: unknown playbook;
    AgentRunRefused: it is already running."""
    name = _playbook_file(playbook, agent_dir or AGENT_DIR).stem
    check_lock(store, name, settings.agent_timeout_minutes * 60)
    if sys.platform == "win32":
        detach = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP
                  | subprocess.DETACHED_PROCESS}
    else:
        detach = {"start_new_session": True}
    (popen or subprocess.Popen)(
        [sys.executable, "-m", "src.scheduler", "agent", "run", name], cwd=REPO,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        **detach)
    return {"started": True, "playbook": name}
