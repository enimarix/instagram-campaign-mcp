"""
The check run (step 188c): a finished render is checked before the owner sees it.

The night run no longer waits for its renders. A video waits for its check once its render
finished (in the last HORIZON): `ready`, not judged, never submitted, or `failed`; never a
Lemo film (the film runner checks its own film: lemo-film.md, today's path), never one the
check dropped, never one with a newer version (its re-render took over), never the owner's
own re-render of a submitted video (next reaction piece, fixed transcript: today's path).
The light check run (agent/playbooks/check-renders.md, started by schedule.check_run) looks
at each one: frames and QC, a re-render (at most MAX_RERENDERS per video: the render jobs of
the idea's versions nobody submitted or judged, minus the first), drop() with the reason, or
submit_asset. Each comes with its render_args (step 191): what render_motion / render_remix
takes again, so a fix changes what the check found and keeps the rest. Every video gets a
decision; one a run left anyway is offered again CHECK_RECHECK_HOURS after that run
(schedule.check_wait, 193): never parked.

The Inbox hides a `ready` video waiting for its check (flag), unless its render finished
more than CHECK_INBOX_GRACE_HOURS ago or the check run cannot run (failing()): then it shows
as before, so nothing is lost. An unsubmitted one a newer version replaces is hidden for
good (193): the newer version carries on.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from ..config import InstagramMCPSettings
from ..store import CampaignStore, parse_iso, to_iso, utcnow
from . import dm_picks, motion, remix, sitcom, work_orders
from .production import qc_summary

PLAYBOOK = "check-renders"
PREFLIGHT_KEY = "check_preflight_failed_at"  # worker_state, set by schedule.check_run
MAX_RERENDERS = 2
HORIZON = timedelta(hours=24)  # renders older than this stay the owner's, as before 188c
WHY_MAX = 300
FAILURE_MAX = 300  # the failed job's reason in the packet
PROPS_MAX = 20_000  # characters of one video's props in the packet; past it they are left out
_FINISHED = ("COALESCE((SELECT MAX(j.finished_at) FROM render_jobs j"
             " WHERE j.asset_id = a.id), a.updated_at)")
_OPEN = "a.verdict = 'none' AND a.self_score_reason IS NULL"  # nobody submitted or judged it
_HAS_CHILD = "EXISTS (SELECT 1 FROM assets c WHERE c.parent_asset_id = a.id)"
_WAITING = (
    "SELECT a.id, a.idea_id, a.parent_asset_id, a.status, a.caption, a.description, a.qc,"
    " a.recipe, json_extract(a.recipe, '$.template') AS template, i.track, i.hook, i.style,"
    f" i.source_id, {_FINISHED} AS finished_at,"
    # the last job's reason when it failed: a render crash (a QC fail has none)
    " (SELECT CASE WHEN j.state = 'failed' THEN j.failure END FROM render_jobs j"
    "  WHERE j.asset_id = a.id ORDER BY j.id DESC LIMIT 1) AS failure,"
    " (SELECT w.id FROM work_orders w WHERE w.idea_id = a.idea_id ORDER BY w.id DESC LIMIT 1)"
    " AS work_order_id,"
    " (SELECT d.sender_username FROM dm_picks d WHERE d.source_id = i.source_id"
    "  ORDER BY d.id LIMIT 1) AS dm_pick_sender"
    " FROM assets a JOIN ideas i ON i.id = a.idea_id"
    f" WHERE a.status IN ('ready', 'failed') AND {_OPEN}"
    " AND substr(COALESCE(i.style, ''), 1, 5) <> 'lemo:'"
    " AND COALESCE(json_extract(a.agent_decision, '$.kind'), '') <> 'dropped'"
    f" AND NOT {_HAS_CHILD}"
    " AND NOT EXISTS (SELECT 1 FROM assets p WHERE p.id = a.parent_asset_id"
    "  AND p.status = 'ready' AND p.self_score_reason IS NOT NULL)"  # the owner's re-render
    f" AND {_FINISHED} >= ? ORDER BY finished_at, a.id")
# ready, unsubmitted, and a newer version of it exists (the check re-rendered it): for good
_REPLACED = f"SELECT a.id FROM assets a WHERE a.status = 'ready' AND {_OPEN} AND {_HAS_CHILD}"
# the render jobs of the idea's versions nobody submitted or judged: the first render and
# the re-renders (in place, a child or a new remix); a version sent back for changes, or
# submitted, starts the count again; a job re-queued for the same recipe counts each time
_JOBS = ("SELECT COALESCE(SUM(1 + j.requeues), 0) FROM render_jobs j"
         " JOIN assets a ON a.id = j.asset_id"
         f" WHERE a.idea_id = ? AND a.status IN ('rendering', 'ready', 'failed') AND {_OPEN}")


def waiting(store: CampaignStore, now: datetime) -> List[Dict[str, Any]]:
    """The videos waiting for their check (module doc), oldest render first."""
    with store._tx() as c:
        rows = [dict(r) for r in c.execute(_WAITING, (to_iso(now - HORIZON),))]
        for r in rows:
            r["rerenders"] = max(0, c.execute(_JOBS, (r["idea_id"],)).fetchone()[0] - 1)
    return rows


def newest(store: CampaignStore, now: datetime) -> Optional[datetime]:
    """When the newest render waiting for its check finished; None when none waits."""
    times = [r["finished_at"] for r in waiting(store, now)]
    return parse_iso(max(times)) if times else None


def for_agent(store: CampaignStore, now: datetime) -> Dict[str, Any]:
    """The check run's packet section: {max_rerenders, renders [{asset_id, status, idea_id,
    track, hook, template, style, caption, description, qc, failure, finished_at,
    rerenders_left, work_order_id, dm_pick_sender, version_of, render_args}]}. caption and
    description are what the producing run stored (data written by us; a remix caption holds
    the creator's credit); failure: the failed job's reason (a render crash, not a QC fail)."""
    out = []
    for r in waiting(store, now):
        failure = " ".join((r["failure"] or "").split())
        out.append({"asset_id": r["id"], "status": r["status"], "idea_id": r["idea_id"],
                    "track": r["track"], "hook": r["hook"], "template": r["template"],
                    "style": r["style"], "caption": r["caption"],
                    "description": r["description"],
                    "qc": qc_summary(json.loads(r["qc"]) if r["qc"] else None),
                    "failure": failure[:FAILURE_MAX] or None,
                    "finished_at": r["finished_at"],
                    "rerenders_left": max(0, MAX_RERENDERS - r["rerenders"]),
                    "work_order_id": r["work_order_id"], "dm_pick_sender": r["dm_pick_sender"],
                    "version_of": r["parent_asset_id"],
                    "render_args": render_args(
                        json.loads(r["recipe"]) if r["recipe"] else None,
                        store.get_source(r["source_id"]) if r["source_id"] is not None
                        else None)})
    return {"max_rerenders": MAX_RERENDERS, "renders": out}


def render_args(env: Optional[Dict[str, Any]], source: Optional[Dict[str, Any]]
                ) -> Optional[Dict[str, Any]]:
    """What render_motion / render_remix takes again to re-render the recipe `env`: motion
    {tool, template, template_props (the props as the agent gave them: editable_props),
    voice, music_audio_id (an Instagram track) or music (the template's bed)}; a reaction
    remix {tool, source_id, hook, script, trim_start_s, trim_end_s, layout, captions (only
    written ones: from the transcript they are null, so a changed trim derives them again,
    193), voice, music (a bed or `none`)} of the idea's `source`. The voice and the script
    come from `voice_todo`, or `voiced_with` once voiced: a recipe voiced before step 191
    has none (null: the default voice; a remix must write its script again). None when there is no recipe (a remix that failed before it had one).
    The keys avoid `props` and `recipe`: the packet drops those (packet.DROP_KEYS)."""
    if not env:
        return None
    todo = env.get("voice_todo") or env.get("voiced_with") or {}
    if env["kind"] == "motion":
        props = editable_props(env["template"], env["props"])
        args = {"tool": "render_motion", "template": env["template"], "template_props": props,
                "voice": todo.get("voice"),
                "music_audio_id": (todo.get("music_audio_id")
                                   or (env.get("ig_audio") or {}).get("audio_id")),
                "music": props.get("music")}
        size = len(json.dumps(props, ensure_ascii=False))
        if size > PROPS_MAX:
            args.update(template_props=None,
                        note=f"props too large for the packet ({size} characters)")
        return args
    if "reaction" not in env["inputs"]:  # not a reaction remix (none is made since 069)
        return None
    # ponytail: the packet keeps 50 caption lines (packet.MAX_ITEMS); a remix is at most
    # REMIX_MAX_CLIP_S long, far fewer lines. Cap here like the props if that ever bites.
    params = remix.remix_params(env)
    if source:
        params["captions"] = remix.written_captions(env, source)
    start, end = params.pop("trim")
    return {"tool": "render_remix", "source_id": source and source["id"], **params,
            "trim_start_s": start, "trim_end_s": end}


def editable_props(template: str, props: Dict[str, Any]) -> Dict[str, Any]:
    """`props` as render_motion takes them: the voice the job filled taken out (`voice`, a
    SitcomSkit character line's `seconds` and `audioSrc`), so a re-render voices the lines
    it says now (the voice service's cache answers a text it already made)."""
    if template not in motion.SCRIPTS:
        return props
    props = {k: v for k, v in props.items() if k != "voice"}
    if template == sitcom.TEMPLATE:
        props["scenes"] = [{**sc, "beats": [_unsaid(b) for b in sc["beats"]]}
                           for sc in props["scenes"]]
    return props


def _unsaid(beat: Dict[str, Any]) -> Dict[str, Any]:
    if not beat.get("say"):
        return beat
    return {**beat, "say": {k: v for k, v in beat["say"].items()
                            if k not in ("seconds", "audioSrc")}}


def failing(store: CampaignStore) -> bool:
    """The check run cannot run: its agent preflight fails, or its last run failed."""
    last = store.list_agent_runs(PLAYBOOK, limit=1)
    return bool(store.get_state(PREFLIGHT_KEY)) or bool(last and last[0]["status"] == "failed")


def flag(store: CampaignStore, settings: InstagramMCPSettings, rows: List[Dict[str, Any]],
         now: datetime) -> List[Dict[str, Any]]:
    """The Inbox's asset rows with awaiting_check (while the check run can run: a `ready`
    video waiting for its check whose render finished less than CHECK_INBOX_GRACE_HOURS
    ago) and replaced (an unsubmitted `ready` one a newer version replaces: for good)."""
    hidden = set()
    if not failing(store):
        since = to_iso(now - timedelta(hours=settings.check_inbox_grace_hours))
        hidden = {r["id"] for r in waiting(store, now)
                  if r["status"] == "ready" and r["finished_at"] >= since}
    with store._tx() as c:
        replaced = {r[0] for r in c.execute(_REPLACED)}
    return [{**r, "awaiting_check": r["id"] in hidden, "replaced": r["id"] in replaced}
            for r in rows]


def drop(store: CampaignStore, asset_id: int, why: str) -> Dict[str, Any]:
    """The check run drops a video it will not submit: its reason is stored as the video's
    agent_decision (kind `dropped`: the Inbox lists « Écartée par l'IA : <why> »), the video
    leaves the check list and the feed (it stays `ready` or `failed`: only the owner archives);
    the work order it was made for is skipped with the reason (Mes envois, a DM order's pick
    too), else an older DM pick of the idea's source; neither while another version of the
    idea lives (not archived, failed or dropped: a fix's new version carries them on)."""
    why = " ".join((why or "").split())[:WHY_MAX]
    if not why:
        raise ValueError("say why the video is dropped, in one line")
    asset = store.get_asset(asset_id)
    if asset["status"] not in ("ready", "failed") or asset["verdict"] != "none" \
            or asset["self_score_reason"] is not None:
        raise ValueError(f"video {asset_id} is not waiting for its check (status"
                         f" {asset['status']}): only an unsubmitted ready or failed one is dropped")
    decision = {"kind": "dropped", "text": f"Écartée par l'IA : {why}", "why": why,
                "style": None, "order_id": None, "request_id": None, "at": to_iso(utcnow())}
    asset = store.update_asset(asset_id, agent_decision=decision)
    idea = store.get_idea(asset["idea_id"])
    with store._tx() as c:
        # another version of the idea lives (a fix's new version): its order and pick go on
        alive = c.execute(
            "SELECT 1 FROM assets WHERE idea_id = ? AND id <> ?"
            " AND status NOT IN ('archived', 'failed')"
            " AND COALESCE(json_extract(agent_decision, '$.kind'), '') <> 'dropped'",
            (idea["id"], asset_id)).fetchone()
        orders = [] if alive else [r[0] for r in c.execute(
            "SELECT id FROM work_orders WHERE idea_id = ? AND status = 'in_production'",
            (idea["id"],))]
        picks = [r[0] for r in c.execute(
            "SELECT id FROM dm_picks WHERE source_id = ? AND status = 'in_production'",
            (idea["source_id"],))] if idea["source_id"] is not None and not (
                alive or orders) else []
    for order_id in orders:
        work_orders.skip_order(store, order_id, why)
    for pick_id in picks:
        dm_picks.mark_pick(store, pick_id, "skipped", why)
    return asset
