"""
Work packets (step 112, GOAL.md §4 fourth rule): the server prepares the work, the agent
does it. Before every agent run, write_packet() rebuilds `<workspace>/work/`:

- one JSON file per section the run needs, each made by an existing service (SECTIONS,
  name -> producer); lists capped at MAX_ITEMS, texts at MAX_TEXT, recipe blobs and file
  paths dropped;
- `manifest.json`, written last: {schema, playbook, run_kind, created_at,
  sections: {name: {file, count, sha256}}};
- every file is validated against `agent/schemas/<name>.schema.json` before anything is
  written, then written atomically (tmp + replace). A producer error or an invalid
  section raises PacketError: the run fails before Claude starts.

Run kinds are playbook names (RUNS): `daily-produce` (night) needs every section, the light
afternoon run is a second playbook, `daily-revise` (revisions + feedback), scheduled like
any other: `AGENT_SCHEDULE=daily-produce@03:00,daily-revise@14:00`. A playbook not in the
table gets every section.

A run whose sections all count 0 is skipped (no Claude launch). brief and quotas always
count 1, so a run that needs them (making the batch, the daily report) never is.
After the run, gaps() looks the packet's revision and feedback ids up again.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from jsonschema import Draft202012Validator
from jsonschema.exceptions import best_match

from ..config import InstagramMCPSettings
from ..learning.brief import creative_brief
from ..learning.facts import facts_for
from ..learning.learnings import get_feedback, list_revision_requests
from ..learning.quotas import todays_quotas
from ..store import CampaignStore, to_iso, utcnow
from ..studio.seed import local_today

SCHEMAS = Path(__file__).resolve().parents[2] / "agent" / "schemas"
SCHEMA_VERSION = 1
MAX_ITEMS = 50
MAX_TEXT = 8000  # the brief's bible cut (brief.BIBLE_CHARS)
DROP_KEYS = {"recipe", "props", "file_path"}
SKIPPED = "skipped: nothing to do"

Producer = Callable[[CampaignStore, InstagramMCPSettings, datetime], Tuple[Any, int]]


class PacketError(RuntimeError):
    """A section could not be made or is invalid: the run must not start."""


class NothingToDo(Exception):
    """Every section the run needs is empty."""


def _brief(store: CampaignStore, settings: InstagramMCPSettings, now: datetime):
    return creative_brief(store, settings, now), 1


def _feedback(store: CampaignStore, settings: InstagramMCPSettings, now: datetime):
    rows = get_feedback(store, limit=MAX_ITEMS)
    return rows, len(rows)


def _revisions(store: CampaignStore, settings: InstagramMCPSettings, now: datetime):
    # A request whose new version is still rendering is being handled: not work again.
    with store._tx() as c:
        pending = {r[0] for r in c.execute(
            "SELECT parent_asset_id FROM assets WHERE status = 'rendering'"
            " AND parent_asset_id IS NOT NULL")}
    rows = [r for r in list_revision_requests(store)
            if r["asset"]["id"] not in pending][:MAX_ITEMS]
    return rows, len(rows)


def _facts(store: CampaignStore, settings: InstagramMCPSettings, now: datetime):
    # No Graph client: audience comments only when the worker already stored them.
    facts = asyncio.run(facts_for(store, settings, now=now))
    day = facts["yesterday"]
    return facts, day["published"]["count"] + day["matured"]["count"]


def _quotas(store: CampaignStore, settings: InstagramMCPSettings, now: datetime):
    return todays_quotas(store, settings, local_today(settings.timezone, now), now), 1


# 113 registers dm_picks here (and in RUNS for daily-produce / daily-revise).
SECTIONS: Dict[str, Producer] = {"brief": _brief, "feedback": _feedback,
                                 "revisions": _revisions, "facts": _facts,
                                 "quotas": _quotas}
# playbook -> (run_kind, sections); None = every section.
RUNS: Dict[str, Tuple[str, Optional[Tuple[str, ...]]]] = {
    "daily-produce": ("produce", None),
    "daily-revise": ("light", ("revisions", "feedback")),
    "daily-learn": ("learn", ("facts", "brief")),
}


def _compact(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _compact(v) for k, v in value.items() if k not in DROP_KEYS}
    if isinstance(value, (list, tuple)):
        return [_compact(v) for v in value[:MAX_ITEMS]]
    if isinstance(value, str) and len(value) > MAX_TEXT:
        return value[:MAX_TEXT] + "…"
    return value


def encode(data: Any, schema: str, schemas: Path = SCHEMAS) -> bytes:
    """Validate against `<schema>.schema.json`, then the bytes to write (indented: the Read
    tool cuts very long lines). PacketError says where it is invalid."""
    spec = json.loads((schemas / f"{schema}.schema.json").read_text(encoding="utf-8"))
    error = best_match(Draft202012Validator(spec).iter_errors(data))
    if error is not None:
        where = "/".join(map(str, error.absolute_path)) or "top level"
        raise PacketError(f"work packet: {schema} is invalid at {where}: "
                          f"{error.message[:200]}")
    return json.dumps(data, ensure_ascii=False, indent=1).encode("utf-8")


def _write_atomic(path: Path, raw: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_bytes(raw)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def write_packet(store: CampaignStore, settings: InstagramMCPSettings, playbook: str,
                 ws: Path, *, now: Optional[datetime] = None,
                 schemas: Path = SCHEMAS) -> Dict[str, Any]:
    """Rebuild `<ws>/work` for `playbook` (see the module docstring). Returns {manifest,
    skip, ids: {feedback: [...], revisions: [asset ids]}}. Raises PacketError."""
    now = now or utcnow()
    kind, names = RUNS.get(playbook, ("custom", None))
    work = ws / "work"
    shutil.rmtree(work, ignore_errors=True)  # a failed build leaves no stale packet
    files: Dict[str, Tuple[bytes, int]] = {}
    ids: Dict[str, List[int]] = {}
    for name in names or SECTIONS:
        try:
            data, count = SECTIONS[name](store, settings, now)
            data = _compact(data)
            files[name] = encode(data, name, schemas), count
        except PacketError:
            raise
        except Exception as e:  # noqa: BLE001 - a broken pipeline must fail the run loudly
            raise PacketError(f"work packet: section {name} failed: {e!r}") from e
        if name == "feedback":
            ids[name] = [f["id"] for f in data]
        elif name == "revisions":
            ids[name] = [r["asset"]["id"] for r in data]
    manifest = {"schema": SCHEMA_VERSION, "playbook": playbook, "run_kind": kind,
                "created_at": to_iso(now),
                "sections": {name: {"file": f"{name}.json", "count": count,
                                    "sha256": hashlib.sha256(raw).hexdigest()}
                             for name, (raw, count) in files.items()}}
    raw_manifest = encode(manifest, "manifest", schemas)
    work.mkdir(parents=True)
    for name, (raw, _) in files.items():
        _write_atomic(work / f"{name}.json", raw)
    _write_atomic(work / "manifest.json", raw_manifest)
    return {"manifest": manifest, "ids": ids,
            "skip": not any(count for _, count in files.values())}


_OPEN_REVISIONS = (
    "SELECT a.id FROM assets a WHERE a.id IN ({}) AND a.status = 'revision_requested'"
    " AND NOT EXISTS (SELECT 1 FROM assets c WHERE c.parent_asset_id = a.id"
    " AND c.created_at >= ?) ORDER BY a.id")
_UNDIGESTED = "SELECT id FROM feedback WHERE id IN ({}) AND digested_at IS NULL ORDER BY id"


def gaps(store: CampaignStore, packet: Dict[str, Any]) -> str:
    """The packet's items still not handled after the run, e.g. "2 of 5 revisions not
    handled: #12, #14". A revision is handled when it left `revision_requested` or got a new
    version during the run; feedback when it is digested (or deleted). "" when none."""
    out = []
    for name, sql, args, what in (
            ("revisions", _OPEN_REVISIONS, (packet["manifest"]["created_at"],),
             "revisions not handled"),
            ("feedback", _UNDIGESTED, (), "feedback comments not digested")):
        ids = packet["ids"].get(name)
        if not ids:
            continue
        with store._tx() as c:
            left = [r[0] for r in c.execute(sql.format(",".join("?" * len(ids))),
                                            (*ids, *args))]
        if left:
            out.append(f"{len(left)} of {len(ids)} {what}: "
                       + ", ".join(f"#{i}" for i in left))
    return "; ".join(out)
