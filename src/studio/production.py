"""
Production tools (step 053): what the agent calls to run a batch through MCP.

create ideas -> queue renders (render_motion, src/studio/motion.py) -> wait_for_renders as
they land -> submit_asset each QC-passed one with a self-score, caption and best_before.
There is no "submitted" status: the worker already moved a QC-passed asset to `ready`;
submit_asset attaches the agent's score and caption while the owner has not judged it.
"""

from __future__ import annotations

import asyncio
import re
import time
from datetime import date, timedelta
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Sequence, Set
from urllib.parse import urlsplit

from ..config import InstagramMCPSettings
from ..learning.experiments import check_idea
from ..learning.quotas import flagged_pillars, todays_quotas
from ..store import CampaignStore
from ..taxonomy import load_taxonomy, validate
from .assets import edit_asset
from .render import auto_description
from .rights import caption_credit_problem
from .seed import local_today

FINISHED = ("done", "failed")
MAX_LIST = 100
REASON_CHARS = 200
EXCERPT_CHARS = 80
_JOBS = ("SELECT j.id AS job_id, j.asset_id, j.state, j.progress, j.failure, a.status, a.qc"
         " FROM render_jobs j JOIN assets a ON a.id = j.asset_id")


def create_idea(store: CampaignStore, settings: InstagramMCPSettings, track: str,
                **fields: Any) -> Dict[str, Any]:
    """Store an idea in today's batch (owner-local date); None fields are left unset.
    Everything is checked before writing; the ValueError says what to change: unknown tags
    (TaxonomyError lists the valid ones), today's quotas (src/learning/quotas.py; a DM
    pick's remix may pass a full batch, _dm_pick_extra), a near-duplicate of a recent
    idea, a fact pillar without citations, an experiment that is not an open one's variant
    (src/learning/experiments.py check_idea, which may fill in the idea's tag)."""
    fields = {k: v for k, v in fields.items() if v is not None}
    check_idea(store, track, fields)
    fields.setdefault("batch_date", local_today(settings.timezone))
    validate("tracks", track)
    pillar = fields.get("pillar") and validate("pillars", fields["pillar"])
    _check_citations(pillar, fields.get("citations"))
    q = todays_quotas(store, settings, fields["batch_date"])
    _check_quotas(q, track, pillar, fields.get("strategy"),
                  extra=_dm_pick_extra(store, settings, q, track, fields.get("source_id")))
    _check_duplicates(store, settings, fields)
    return store.add_idea(track, **fields)


def _check_citations(pillar: Optional[str], citations: Any) -> None:
    """Any citations must be [{url (http/https), title?}]; fact pillars need at least one.
    Only the URL's shape is checked (no network)."""
    if not citations:
        if pillar in flagged_pillars("needs_citations"):
            raise ValueError(f"fact pillar '{pillar}' needs citations: add [{{url, title}}]")
        return
    if not isinstance(citations, list):
        raise ValueError("citations must be a list of {url, title}")
    for c in citations:
        url = c.get("url") if isinstance(c, dict) else None
        parts = urlsplit(url) if isinstance(url, str) else None
        if not parts or parts.scheme not in ("http", "https") or not parts.netloc:
            raise ValueError(f"citation {c!r} needs an http(s) url: {{url, title}}")


def _dm_pick_extra(store: CampaignStore, settings: InstagramMCPSettings, q: Dict[str, Any],
                   track: str, source_id: Optional[int]) -> bool:
    """A remix of a DM pick being made may go past a full batch, up to
    MAX_DM_PICK_EXTRAS_PER_DAY (DECISIONS 2026-11-18). Every idea over the cap is such an
    extra, so the ones already made are counts - limits.
    ponytail: a bench that grows during the day lowers limits.ideas and eats into it."""
    if track != "remix" or source_id is None:
        return False
    if q["counts"]["ideas"] - q["limits"]["ideas"] >= settings.max_dm_pick_extras_per_day:
        return False
    with store._tx() as c:
        return c.execute("SELECT 1 FROM dm_picks WHERE source_id = ?"
                         " AND status IN ('downloaded','in_production')",
                         (source_id,)).fetchone() is not None


def _check_quotas(q: Dict[str, Any], track: str, pillar: Optional[str],
                  strategy: Optional[str], *, extra: bool = False) -> None:
    """extra: a DM-pick remix that may go past a full batch; it is outside the batch's
    humour / informative split, the explore and reaction quotas still apply."""
    limits, counts = q["limits"], q["counts"]
    full = counts["ideas"] >= limits["ideas"]
    if full and not extra:
        raise ValueError(f"batch full: {counts['ideas']}/{limits['ideas']} ideas today")
    if strategy == "explore" and counts["explore"] >= limits["explore"]:
        raise ValueError(f"explore quota used: {counts['explore']}/{limits['explore']};"
                         " make it exploit")
    if pillar in flagged_pillars("humour"):
        kind, other = "humour", "pick an informative pillar"
    else:
        kind, other = "informative", "pick a humour pillar"
    if not full and counts[kind] >= limits[kind]:
        raise ValueError(f"{kind} {counts[kind] + 1}/{limits[kind]}: {other}")
    if track == "remix" and counts["reactions"] >= limits["reactions"]:
        raise ValueError(f"reaction quota used: {counts['reactions']}/{limits['reactions']}"
                         f" ({q['clips_available']} downloaded clips left); make it motion")


def _normalise(text: Optional[str]) -> str:
    return " ".join(re.sub(r"[^\w\s]|_", " ", (text or "").lower()).split())


def _texts(idea: Dict[str, Any]) -> Set[str]:
    """Normalised hook and first sentence of the script, without empties."""
    first = re.split(r"[.!?\n]", (idea.get("script") or "").strip(), maxsplit=1)[0]
    return {t for t in (_normalise(idea.get("hook")), _normalise(first)) if t}


def _check_duplicates(store: CampaignStore, settings: InstagramMCPSettings,
                      fields: Dict[str, Any]) -> None:
    """Refuse an idea whose hook or opening line is close to one of the last dedupe_days.
    ponytail: O(n) scan with difflib, fine at ~25 ideas a day."""
    new = _texts(fields)
    if not new:
        return
    day = date.fromisoformat(str(fields["batch_date"]))
    since = (day - timedelta(days=settings.dedupe_days)).isoformat()
    with store._tx() as c:
        recent = c.execute("SELECT id, hook, script, batch_date FROM ideas"
                           " WHERE batch_date >= ? ORDER BY id DESC", (since,)).fetchall()
    for old in recent:
        for a in new:
            for b in _texts(dict(old)):
                if SequenceMatcher(None, a, b).ratio() >= settings.dedupe_threshold:
                    raise ValueError(f"near-duplicate of idea {old['id']} ({old['batch_date']}):"
                                     f" {old['hook']!r}; change the angle")


def qc_summary(qc: Optional[Dict[str, Any]]) -> Optional[str]:
    """"passed", or "failed: <reasons>", or None before the first render finished."""
    if not qc:
        return None
    if qc.get("passed"):
        return "passed"
    return "failed: " + ("; ".join(qc.get("reasons") or []) or qc.get("reason") or "unknown")


def _excerpt(text: Optional[str]) -> str:
    text = text or ""
    return text[:EXCERPT_CHARS] + ("…" if len(text) > EXCERPT_CHARS else "")


def compact_asset(asset: Dict[str, Any]) -> Dict[str, Any]:
    """The row the agent needs: no recipe props or timeline, media paths relative."""
    return {
        "id": asset["id"], "idea_id": asset["idea_id"], "batch_date": asset["batch_date"],
        "status": asset["status"], "verdict": asset["verdict"],
        "template": (asset.get("recipe") or {}).get("template"),
        "caption": _excerpt(asset.get("caption")),
        "description": _excerpt(asset.get("description")),
        "self_score": asset["self_score"], "qc": qc_summary(asset["qc"]),
        "best_before": asset["best_before"], "file_path": asset["file_path"],
    }


def list_assets(store: CampaignStore, *, status: Optional[str] = None,
                batch_date: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    """Compact asset rows, best self-score first."""
    rows = store.list_assets(batch_date=batch_date, status=status,
                             limit=max(1, min(limit, MAX_LIST)))
    return [compact_asset(a) for a in rows]


def render_status(store: CampaignStore, *, job_id: Optional[int] = None,
                  asset_id: Optional[int] = None) -> Dict[str, Any]:
    """{asset, job} for a job, or for an asset and its latest job (None if never queued)."""
    if (job_id is None) == (asset_id is None):
        raise ValueError("give exactly one of job_id or asset_id")
    if job_id is not None:
        job: Optional[Dict[str, Any]] = store.get_render_job(job_id)
        asset_id = job["asset_id"]
    else:
        job = next(iter(store.list_render_jobs(asset_id=asset_id, limit=1)), None)
    out_job = job and {k: job[k] for k in ("id", "state", "progress", "attempts", "failure")}
    return {"asset": compact_asset(store.get_asset(asset_id)), "job": out_job}


def _jobs(store: CampaignStore, batch_date: Optional[str],
          job_ids: Optional[Sequence[int]]) -> List[Dict[str, Any]]:
    if job_ids:
        rows = []
        for jid in dict.fromkeys(job_ids):
            found = store._select(_JOBS, {"j.id": jid}, "j.id", 1)
            if not found:
                raise ValueError(f"no render job {jid}")
            rows += found
        return rows
    rows = store._select(_JOBS, {"a.batch_date": batch_date}, "j.id", 10_000)
    # An asset re-rendered after a failure has an older finished job: keep its latest only.
    return list({r["asset_id"]: r for r in rows}.values())


def _job_row(r: Dict[str, Any]) -> Dict[str, Any]:
    row = {"job_id": r["job_id"], "asset_id": r["asset_id"], "state": r["state"]}
    if r["state"] in FINISHED:
        row.update(status=r["status"], qc=qc_summary(r["qc"]))
        if r["failure"]:
            row["failure"] = r["failure"][:300]
    else:
        row["progress"] = r["progress"]
    return row


async def wait_for_renders(store: CampaignStore, settings: InstagramMCPSettings, *,
                           batch_date: Optional[str] = None,
                           job_ids: Optional[Sequence[int]] = None,
                           timeout_s: Optional[float] = None,
                           poll_s: float = 2.0) -> Dict[str, Any]:
    """Wait until a render job finishes, then return {finished, pending, timed_out}.

    Watches the jobs of `batch_date` (latest per asset) or the given `job_ids`. Returns as
    soon as a job finishes during the wait (with job_ids, one already finished counts too:
    the caller is waiting on exactly those), when nothing is pending, or at the timeout
    (capped by the wait_for_renders_max_s setting). Finished rows carry the asset status and
    the QC summary, whose reasons tell the agent what to fix before a re-render.
    """
    if (batch_date is None) == (not job_ids):
        raise ValueError("give exactly one of batch_date or job_ids")
    cap = settings.wait_for_renders_max_s
    timeout_s = cap if timeout_s is None else max(0.0, min(timeout_s, cap))
    deadline = time.monotonic() + timeout_s
    rows = await asyncio.to_thread(_jobs, store, batch_date, job_ids)
    seen = set() if job_ids else {r["job_id"] for r in rows if r["state"] in FINISHED}
    while True:
        finished = [r for r in rows if r["state"] in FINISHED]
        pending = [r for r in rows if r["state"] not in FINISHED]
        left = deadline - time.monotonic()
        if not pending or {r["job_id"] for r in finished} - seen or left <= 0:
            return {"finished": [_job_row(r) for r in finished],
                    "pending": [_job_row(r) for r in pending],
                    "timed_out": bool(pending) and left <= 0}
        await asyncio.sleep(min(poll_s, left))
        rows = await asyncio.to_thread(_jobs, store, batch_date, job_ids)


def default_best_before(store: CampaignStore, settings: InstagramMCPSettings,
                        asset: Dict[str, Any]) -> str:
    """The idea's batch date + its pillar's shelf_days (brand/taxonomy.json), or + the
    best_before_default_days setting when the pillar sets none."""
    idea = store.get_idea(asset["idea_id"])
    pillars = {p["id"]: p for p in load_taxonomy()["pillars"]["values"]}
    days = pillars.get(idea["pillar"], {}).get("shelf_days") or settings.best_before_default_days
    return (date.fromisoformat(idea["batch_date"]) + timedelta(days=days)).isoformat()


def submit_asset(store: CampaignStore, settings: InstagramMCPSettings, asset_id: int, *,
                 self_score: int, self_score_reason: str, caption: str,
                 best_before: Optional[str] = None,
                 description: Optional[str] = None) -> Dict[str, Any]:
    """Attach the agent's self-score (1-10, one line on why), caption, best_before and
    description (2-3 plain sentences: what happens, the hook, the payoff; default: the one
    already stored, else an automatic one) to a QC-passed (`ready`) asset the owner has not
    judged yet. Re-submitting overwrites. Everything is checked before anything is written;
    ValueError names the problem."""
    asset = store.get_asset(asset_id)
    status = asset["status"]
    if status == "rendering":
        raise ValueError(f"asset {asset_id} is still rendering: wait_for_renders first")
    if status == "failed":
        raise ValueError(f"asset {asset_id}: QC {qc_summary(asset['qc']) or 'failed'}"
                         " (re-render it, or drop it)")
    if status != "ready":
        raise ValueError(f"asset {asset_id} is {status}: only ready assets can be submitted")
    if asset["verdict"] != "none":
        raise ValueError(f"asset {asset_id}: the owner already judged it ({asset['verdict']})")
    if isinstance(self_score, bool) or not isinstance(self_score, int) \
            or not 1 <= self_score <= 10:
        raise ValueError(f"self_score must be a whole number 1-10, not {self_score!r}")
    reason = (self_score_reason or "").strip()
    if not reason or "\n" in reason or "\r" in reason or len(reason) > REASON_CHARS:
        raise ValueError(f"self_score_reason must be one line of 1-{REASON_CHARS} characters")
    if not (caption or "").strip():
        raise ValueError("a caption is required")
    source_id = store.get_idea(asset["idea_id"])["source_id"]
    problem = source_id is not None and caption_credit_problem(store.get_source(source_id),
                                                                caption)
    if problem:
        raise ValueError(problem)
    if best_before is None:
        best_before = default_best_before(store, settings, asset)
    if description is None:
        description = asset["description"] or auto_description(
            store.get_idea(asset["idea_id"]), asset)
    edit_asset(store, asset_id, caption=caption, best_before=best_before,  # checks them
               description=description)
    return compact_asset(store.update_asset(asset_id, self_score=self_score,
                                            self_score_reason=reason))
