"""
Feedback digest and learnings (step 054, GOAL.md §3.5): what the agent reads from the
owner's comments and the lessons it keeps.

The rules that protect the owner's voice live here, not in the prompt:
- a learning cites its evidence: feedback ids for `taste`, evidence dicts otherwise;
- drawn from one comment, it is a `hypothesis` at `low` confidence, whatever was asked;
- an explicit owner instruction (one comment with text) is stored at confidence `owner`;
- the agent never sets `owner` or `high` (high is for audience-backed rules, later), and
  never changes or retires a learning at confidence `owner`.
Every function takes `actor` ("agent" by default): the owner's Learnings page (084) calls
the same functions with actor="owner", which lifts the agent's limits. Owner edits win: a
learning the owner edits or confirms is set to confidence `owner`, which the agent and the
evidence engine never change.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Sequence

from ..config import InstagramMCPSettings, get_settings
from ..store import CampaignStore, utcnow
from ..studio.media import media_url
from ..studio.production import MAX_LIST, compact_asset
from ..taxonomy import load_taxonomy
from .analytics import studio_side
from .evidence import evaluate_learning, predicate

Actor = Literal["agent", "owner"]
KINDS = ("do", "dont", "hypothesis")
CONFIDENCES = ("low", "medium", "high", "owner")
AGENT_CONFIDENCES = ("low", "medium")
ORIGINS = ("taste", "audience", "ads")
STATUSES = ("active", "retired", "contradicted")
OWNER_ONLY = "only the owner can change this"


def _one_of(name: str, value: str, allowed: Sequence[str]) -> str:
    if value not in allowed:
        raise ValueError(f"{name} must be one of {', '.join(allowed)}, not {value!r}")
    return value


def _limit(limit: int) -> int:
    return max(1, min(limit, MAX_LIST))


def asset_context(store: CampaignStore, asset: Dict[str, Any]) -> Dict[str, Any]:
    """compact_asset plus the idea's hook, pillar, hook_type and track."""
    idea = store.get_idea(asset["idea_id"])
    return {**compact_asset(asset),
            **{k: idea[k] for k in ("hook", "pillar", "hook_type", "track")}}


def _comment(fb: Dict[str, Any], labels: Dict[str, str]) -> Dict[str, Any]:
    return {"id": fb["id"], "asset_id": fb["asset_id"], "text": fb["text"],
            "reasons": [{"code": c, "label": labels.get(c, c)} for c in fb["reason_codes"]],
            "video_time_s": fb["video_time_s"], "wants_changes": bool(fb["wants_changes"]),
            "digested_at": fb["digested_at"], "created_at": fb["created_at"]}


def _labels() -> Dict[str, str]:
    return {r["id"]: r["label"] for r in load_taxonomy()["feedback_reasons"]["values"]}


def change_outcome(store: CampaignStore, revised: Dict[str, Any],
                   labels: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """A revised video (step 133): the version the owner sent back (before), what they
    asked (its wants-changes comments), what the agent says it changed (the new version's
    submit note, stored in self_score_reason; None when it left none), and the owner's
    decision on the new version: approved, declined (with its motives), sent_back
    (asked_again: more changes), archived or pending."""
    labels = labels or _labels()
    before = revised["parent_asset_id"]

    def comments(asset_id: int, wants: bool) -> List[Dict[str, Any]]:
        return [{"feedback_id": fb["id"], "text": fb["text"],
                 "reasons": [labels.get(c, c) for c in fb["reason_codes"]]}
                for fb in store.list_feedback(asset_id=asset_id, limit=MAX_LIST)
                if bool(fb["wants_changes"]) == wants]

    sent_back = comments(revised["id"], True)
    outcome = ("approved" if revised["approved_at"]
               else "declined" if revised["verdict"] == "disliked"
               else "sent_back" if sent_back
               else "archived" if revised["status"] == "archived" else "pending")
    return {"before_asset_id": before, "after_asset_id": revised["id"],
            "asked": comments(before, True), "changed": revised["self_score_reason"] or None,
            "outcome": outcome,
            "decline_motives": comments(revised["id"], False) if outcome == "declined" else [],
            "asked_again": sent_back}


def _change_for(store: CampaignStore, fb: Dict[str, Any], asset: Dict[str, Any],
                labels: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """The change a comment belongs to: a comment on a revised video, or a change request
    whose new version exists (the newest one). None for any other comment."""
    if asset["parent_asset_id"]:
        return change_outcome(store, asset, labels)
    if fb["wants_changes"]:
        child = store._select("SELECT * FROM assets", {"parent_asset_id": asset["id"]},
                              "id DESC", 1)
        return change_outcome(store, child[0], labels) if child else None
    return None


def get_feedback(store: CampaignStore, *, undigested: bool = True,
                 limit: int = 50) -> List[Dict[str, Any]]:
    """Owner comments, oldest first (undigested=False: read ones too), each with its
    reason labels, its asset's context and `change` (change_outcome, or None). A change
    request comes back undigested when the owner decides on its new version (step 133)."""
    rows = store.list_feedback(undigested=True if undigested else None, limit=_limit(limit))
    labels, assets = _labels(), {}
    out = []
    for fb in rows:
        asset = store.get_asset(fb["asset_id"])
        if fb["asset_id"] not in assets:
            assets[fb["asset_id"]] = asset_context(store, asset)
        out.append({**_comment(fb, labels), "asset": assets[fb["asset_id"]],
                    "change": _change_for(store, fb, asset, labels)})
    return out


def owner_decisions(store: CampaignStore, *, limit: int = 20) -> Dict[str, Any]:
    """What the owner turned down and which changes they approved, newest first, read or
    not (step 133): the creative brief lists these first so the next batch avoids the
    motives and repeats what worked."""
    labels, limit = _labels(), _limit(limit)
    with store._tx() as c:
        motive_ids = [r[0] for r in c.execute(
            "SELECT f.id FROM feedback f JOIN assets a ON a.id = f.asset_id"
            " WHERE a.verdict = 'disliked' AND f.wants_changes = 0"
            " ORDER BY f.id DESC LIMIT ?", (limit,))]
    motives = []
    for i in motive_ids:
        fb = store.get_feedback(i)
        asset = store.get_asset(fb["asset_id"])
        motives.append({**_comment(fb, labels), "asset": asset_context(store, asset),
                        "change": _change_for(store, fb, asset, labels)})
    approved = store._select("SELECT * FROM assets WHERE parent_asset_id IS NOT NULL"
                             " AND approved_at IS NOT NULL", {}, "approved_at DESC", limit)
    return {"decline_motives": motives,
            "approved_changes": [change_outcome(store, a, labels) for a in approved]}


def mark_feedback_digested(store: CampaignStore, ids: Sequence[int]) -> Dict[str, int]:
    """Mark comments as read by the agent; counts only those not read before."""
    return {"digested": store.mark_feedback_digested(ids)}


def list_revision_requests(store: CampaignStore) -> List[Dict[str, Any]]:
    """Assets the owner sent back (`revision_requested`) with their wanting-changes
    comments, newest first: re-render each with render_motion(asset_id=...). A request whose
    new version is still rendering is being handled: left out."""
    with store._tx() as c:
        pending = {r[0] for r in c.execute(
            "SELECT parent_asset_id FROM assets WHERE status = 'rendering'"
            " AND parent_asset_id IS NOT NULL")}
    labels = _labels()
    out = []
    for asset in store.list_assets(status="revision_requested", limit=MAX_LIST):
        if asset["id"] in pending:
            continue
        comments = [_comment(fb, labels) for fb in store.list_feedback(asset_id=asset["id"],
                                                                       limit=MAX_LIST)
                    if fb["wants_changes"]]
        out.append({"asset": asset_context(store, asset), "comments": comments[::-1]})
    return out


def _feedback_evidence(store: CampaignStore, ids: Sequence[int]) -> List[Dict[str, int]]:
    """[{feedback_id}] for existing comments, duplicates dropped; KeyError names a bad id."""
    ids = list(dict.fromkeys(ids))
    for i in ids:
        store.get_feedback(i)
    return [{"feedback_id": i} for i in ids]


def _check_confidence(confidence: str) -> None:
    if confidence not in AGENT_CONFIDENCES:
        raise ValueError(f"confidence {confidence!r} is not for the agent: use low or medium")


def _sources(evidence: Sequence[Any]) -> int:
    """How many distinct comments, posts, ad tests or work orders the evidence cites: two
    metrics of one Reel are one Reel (an item naming none, e.g. the engine's, is its own)."""
    keys = ("feedback_id", *ANCHORS)
    return len({tuple(str(e.get(k)) for k in keys)
                if any(e.get(k) is not None for k in keys) else repr(e) for e in evidence})


def _check_caps(kind: str, confidence: str, evidence: Sequence[Any]) -> None:
    """The agent's limits: no owner/high confidence; do/dont/medium need >= 2 sources."""
    _check_confidence(confidence)
    if _sources(evidence) < 2 and (kind != "hypothesis" or confidence != "low"):
        raise ValueError("one piece of evidence makes a low-confidence hypothesis only:"
                         " do/dont or medium needs at least 2")


def _check_scope(scope: Any) -> None:
    if scope is not None and not isinstance(scope, dict):
        raise ValueError("scope must be an object of tags")
    predicate(scope)  # ValueError: an unknown tag or value


# evidence dict key -> (table, column) it must exist in
ANCHORS = {"media_id": ("insight_snapshots", "media_id"), "test_id": ("ad_tests", "id"),
           "work_order_id": ("work_orders", "id")}


def _check_evidence(store: CampaignStore, origin: str, evidence: Optional[Sequence[Any]],
                    actor: Actor, known: Sequence[Any] = ()) -> List[Dict[str, Any]]:
    """Audience/ads evidence dicts, duplicates (and ones already in `known`) dropped. The
    agent's each name a post with insights (media_id), an ad test or a work order: KeyError
    when it does not exist, so no claim rests on a number the studio never saw."""
    if not evidence:
        return []
    if origin == "taste" or not all(isinstance(e, dict) and e for e in evidence):
        raise ValueError("evidence dicts are for audience/ads learnings;"
                         " taste cites evidence_feedback_ids")
    out: List[Dict[str, Any]] = []
    for e in evidence:
        if e in out or e in known:
            continue
        out.append(e)
        if actor == "owner":
            continue
        keys = [k for k in ANCHORS if e.get(k) is not None]
        if not keys:
            raise ValueError("each evidence dict names its media_id (a post with insights),"
                             " test_id or work_order_id")
        for k in keys:
            table, col = ANCHORS[k]
            with store._tx() as c:
                if not c.execute(f"SELECT 1 FROM {table} WHERE {col} = ? LIMIT 1",
                                 (str(e[k]) if k == "media_id" else e[k],)).fetchone():
                    raise KeyError(f"no {k} {e[k]!r}: cite what the studio measured")
    return out


def _check_owner_scope(store: CampaignStore, scope: Any, feedback: Dict[str, Any]) -> None:
    """An owner instruction the agent stores binds every later batch (mix, check_template):
    its predicate must be what the commented video is (e.g. template=DialogStory on a
    DialogStory video), not a wider rule the agent read into the comment."""
    pred = predicate(scope)
    if pred is None:
        return
    tags = studio_side(store, feedback["asset_id"])["tags"] or {}
    if tags.get(pred[0]) != pred[1]:
        raise ValueError(f"an owner instruction's scope must match the commented video:"
                         f" video {feedback['asset_id']} has {pred[0]}={tags.get(pred[0])!r},"
                         f" not {pred[1]!r}")


def add_learning(store: CampaignStore, statement: str, kind: str, origin: str,
                 evidence_feedback_ids: Sequence[int] = (), *,
                 evidence: Optional[List[Dict[str, Any]]] = None,
                 scope: Optional[Dict[str, Any]] = None, confidence: Optional[str] = None,
                 owner_instruction: bool = False,
                 actor: Actor = "agent") -> Dict[str, Any]:
    """Store a learning -> {learning, note}. note says when the kind or confidence was
    forced. Everything is checked before anything is written; ValueError/KeyError say why."""
    statement = (statement or "").strip()
    if not statement:
        raise ValueError("a statement is required")
    _one_of("kind", kind, KINDS)
    _one_of("origin", origin, ORIGINS)
    _check_scope(scope)
    items = (_feedback_evidence(store, evidence_feedback_ids)
             + _check_evidence(store, origin, evidence, actor))
    note = None
    if owner_instruction:
        if origin != "taste" or kind not in ("do", "dont") or len(items) != 1:
            raise ValueError("an owner instruction is a taste do/dont citing exactly one"
                             " feedback id")
        fb = store.get_feedback(items[0]["feedback_id"])
        if not (fb["text"] or "").strip():
            raise ValueError("an owner instruction needs a comment with text, not chips only")
        if actor != "owner":
            _check_owner_scope(store, scope, fb)
        confidence = "owner"
    elif actor == "owner":
        confidence = _one_of("confidence", confidence or "owner", CONFIDENCES)
    else:
        if not items:
            raise ValueError("cite evidence: feedback ids for taste, evidence dicts otherwise")
        confidence = confidence or "low"
        _check_confidence(confidence)  # owner/high are refused, never silently forced
        if _sources(items) == 1 and (kind, confidence) != ("hypothesis", "low"):
            note = (f"one piece of evidence: stored as a low-confidence hypothesis"
                    f" (asked {kind}/{confidence})")
            kind, confidence = "hypothesis", "low"
    row = store.add_learning(statement, kind, origin, scope=scope or {}, evidence=items,
                             confidence=confidence)
    return {"learning": row, "note": note}


def update_learning(store: CampaignStore, learning_id: int, *,
                    statement: Optional[str] = None, kind: Optional[str] = None,
                    confidence: Optional[str] = None, status: Optional[str] = None,
                    evidence_feedback_ids_to_add: Sequence[int] = (),
                    evidence_to_add: Optional[List[Dict[str, Any]]] = None,
                    scope: Optional[Dict[str, Any]] = None, evaluate: bool = False,
                    settings: Optional[InstagramMCPSettings] = None,
                    now: Optional[datetime] = None,
                    actor: Actor = "agent") -> Dict[str, Any]:
    """Edit, re-rate, retire or add evidence to a learning; the agent may never touch one
    at confidence `owner`. Everything is checked before anything is written. A learning
    with a tag predicate is re-checked against the numbers (evidence.evaluate_learning)
    after a statement, kind or scope change, or when `evaluate` is set."""
    current = store.get_learning(learning_id)
    if actor != "owner" and current["confidence"] == "owner":
        raise ValueError(f"learning {learning_id} is the owner's rule: {OWNER_ONLY}")
    fields: Dict[str, Any] = {}
    if statement is not None:
        if not statement.strip():
            raise ValueError("the statement cannot be empty")
        fields["statement"] = statement.strip()
    if kind is not None:
        fields["kind"] = _one_of("kind", kind, KINDS)
    if confidence is not None:
        fields["confidence"] = _one_of("confidence", confidence, CONFIDENCES)
    if status is not None:
        fields["status"] = _one_of("status", status, STATUSES)
    if scope is not None:
        _check_scope(scope)
        fields["scope"] = scope
    if evidence_feedback_ids_to_add:
        known = {e.get("feedback_id") for e in current["evidence"]}
        fields["evidence"] = current["evidence"] + [
            e for e in _feedback_evidence(store, evidence_feedback_ids_to_add)
            if e["feedback_id"] not in known]
    if evidence_to_add:
        fields["evidence"] = fields.get("evidence", current["evidence"]) + _check_evidence(
            store, current["origin"], evidence_to_add, actor, known=current["evidence"])
    if actor != "owner" and fields.keys() & {"statement", "kind", "scope"}:
        # a changed claim is a new claim: it starts low unless re-rated within the caps,
        # and the re-check below lifts it when the numbers back it
        fields.setdefault("confidence", "low")
    if actor != "owner" and (kind is not None or confidence is not None):
        _check_caps(fields.get("kind", current["kind"]),
                    fields.get("confidence", current["confidence"]),
                    fields.get("evidence", current["evidence"]))
    if actor == "owner" and fields.keys() & {"statement", "kind", "scope"}:
        fields["confidence"] = "owner"  # owner edits win over the agent and the numbers
    recheck = ((evaluate or fields.keys() & {"statement", "kind", "scope"})
               and predicate(fields.get("scope", current["scope"])))  # ValueError before writing
    row = store.update_learning(learning_id, **fields)
    if recheck:
        row = evaluate_learning(store, settings or get_settings(), row, now=now or utcnow())
    return row


def list_learnings(store: CampaignStore, *, kind: Optional[str] = None,
                   status: Optional[str] = "active", origin: Optional[str] = None,
                   confidence: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    """Learnings, strongest first (owner > high > medium > low, then newest)."""
    if confidence is None:
        return store.list_learnings(kind=kind, status=status, origin=origin,
                                    limit=_limit(limit))
    _one_of("confidence", confidence, CONFIDENCES)
    # ponytail: filtered after one full read (the store has no confidence filter)
    rows = store.list_learnings(kind=kind, status=status, origin=origin, limit=1_000_000)
    return [r for r in rows if r["confidence"] == confidence][:_limit(limit)]


def _linked(store: CampaignStore, item: Dict[str, Any]) -> Dict[str, Any]:
    """A feedback evidence item plus the comment's text and its asset (a deleted comment
    stays a bare id)."""
    if "feedback_id" not in item:
        return item
    try:
        fb = store.get_feedback(item["feedback_id"])
    except KeyError:
        return item
    asset = store.get_asset(fb["asset_id"])
    return {**item, "text": fb["text"], "asset_id": asset["id"],
            "thumbnail_url": media_url(asset.get("thumbnail_path"))}


def learnings_page(store: CampaignStore, *, kind: Optional[str] = None,
                   status: Optional[str] = None, origin: Optional[str] = None,
                   confidence: Optional[str] = None) -> List[Dict[str, Any]]:
    """The owner's Learnings page (084): every learning matching the filters (any status by
    default), its feedback evidence linked to the comment and the video."""
    rows = list_learnings(store, kind=kind, status=status, origin=origin,
                          confidence=confidence, limit=MAX_LIST)
    return [{**r, "evidence": [_linked(store, e) for e in r["evidence"]]} for r in rows]
