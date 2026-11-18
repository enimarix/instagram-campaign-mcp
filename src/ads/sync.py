"""Ad results (step 095): the worker's `ads_sync` job keeps running tests honest.

Hourly while a test runs or still holds a reservation, or the kill switch is on; daily
otherwise (`period`). One `sync()`:
1. Kill enforcement (killed at the start): pause the ledger's campaigns
   (`budget.paused_ids_needed`) and every campaign, ad set and ad of the account that is
   not paused, since ads made outside the studio count too. Audited; a failed pause or
   listing raises an alert.
2. Review: an ad of a running test that Meta rejects or limits (`effective_status`
   DISAPPROVED / WITH_ISSUES, `ad_review_feedback`, `issues_info`) gets its reason stored
   in the test's results and an alert.
3. Per test, insights per variant (ad set) from its start to today: the snapshot goes to
   `ad_tests.result` (impressions, clicks, results, spend, days, `abtest.evaluate`).
   The spend reconciles the ledger (`budget.report_spend`: the increase as `reported`
   rows). Meta reporting more than an ad set's authorization: alert and kill (then step 1
   runs again).
4. Stop rules (`abtest.should_stop`, or the test's end date passed): pause the test's ads,
   mark it finished with the evaluation, release what is still reserved, audit.
5. Near a cap: daily, lifetime or a running test's usage at NEAR_CAP or more raises one
   alert per scope per owner-local day.
Tests no longer running stay reconciled for LATE_SPEND (Meta reports spend late); a
cancelled test's reservations are released once its objects are paused.
The only writes are pauses (`AdsWriter.pause`, @pauses): nothing here spends.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import structlog

from ..config import InstagramMCPSettings
from ..instagram_client import NotConfigured
from ..store import CampaignStore, parse_dt, to_iso, utcnow
from ..studio.alerts import raise_alert
from . import abtest, budget
from .budget import ZERO, audit, open_authorizations, release
from .tests import _entities, _pause_active, _set_status, _shown
from .writer import PAUSED, AdsWriter

logger = structlog.get_logger(__name__)

HOURLY, DAILY = timedelta(hours=1), timedelta(days=1)
LATE_SPEND = timedelta(days=3)
NEAR_CAP = Decimal("0.8")
REJECTED = {"DISAPPROVED", "WITH_ISSUES"}
# The result an objective optimizes for. ponytail: awareness = reach, engagement on video
# = the video_view action; H6 checks them against Ads Manager's Results column.
RESULT_ACTION = {"OUTCOME_AWARENESS": "reach", "OUTCOME_ENGAGEMENT": "video_view"}
LINK = "/ads"


def period(store: CampaignStore) -> timedelta:
    with store.immediate() as c:
        busy = budget._kill_state(c)["killed"] or c.execute(
            "SELECT 1 FROM ad_tests WHERE status IN ('approved','running') UNION ALL"
            " SELECT 1 FROM ad_spend_ledger a WHERE a.kind='authorized' AND a.test_id IS NOT"
            " NULL AND NOT EXISTS (SELECT 1 FROM ad_spend_ledger r WHERE r.kind='released'"
            " AND r.authorization_id=a.id) LIMIT 1").fetchone()
    return HOURLY if busy else DAILY


def _pause_alert(store: CampaignStore, subject: Any, failed: List[str], now: datetime) -> None:
    raise_alert(store, "ads_pause_failed", subject, "error", "Ads could not be paused",
                f"Meta did not pause {', '.join(failed)}. Pause them in Ads Manager; the "
                "studio retries every hour.", LINK, now, renew=True)


async def enforce_kill(store: CampaignStore, w: AdsWriter, now: datetime) -> Dict[str, Any]:
    """Pause every object that may still spend: campaigns first, then ad sets, then ads."""
    ledger, listed, seen = budget.paused_ids_needed(store), [], {}
    error = None
    try:
        for lister in (w.list_campaigns, w.list_ad_sets, w.list_ads):
            for o in await lister():
                seen[o["id"]] = o.get("status")
                listed.append(o["id"])
    except Exception as e:  # pause what we know anyway
        logger.exception("ads_kill_listing_failed")
        error = repr(e)
    # Meta's list edges leave out archived and deleted objects unless asked ("A request
    # with no filters returns only campaigns that were not archived or deleted"): every
    # listed object not PAUSED may deliver.
    todo = [i for i in dict.fromkeys(ledger + listed) if seen.get(i) != PAUSED]
    paused, failed = [], []
    for meta_id in todo:
        try:
            await w.pause(meta_id)
            paused.append(meta_id)
        except Exception:  # keep pausing the others
            logger.exception("ads_kill_pause_failed", meta_id=meta_id)
            failed.append(meta_id)
    if paused:
        with store.immediate() as c:
            c.executemany("UPDATE ad_entities SET status=?, updated_at=? WHERE meta_id=?",
                          [(PAUSED, to_iso(now), i) for i in paused])
    if paused or failed or error:
        audit(store, "kill_enforced", actor="system", paused=paused, failed=failed,
              list_error=error)
    if failed or error:
        _pause_alert(store, "kill", failed or [f"the objects Meta would not list ({error})"],
                     now)
    return {"paused": paused, "failed": failed, "list_error": error}


def _review_reason(ad: Dict[str, Any]) -> Optional[str]:
    parts = [f"{k}: {v}" for scope in (ad.get("ad_review_feedback") or {}).values()
             if isinstance(scope, dict) for k, v in scope.items()]
    parts += [str(i.get("error_summary") or i.get("error_message") or i.get("error_code"))
              for i in ad.get("issues_info") or []]
    if not parts and ad.get("effective_status") not in REJECTED:
        return None
    return "; ".join(parts) or ad["effective_status"]


async def _review(store: CampaignStore, w: AdsWriter, test_ids: set,
                  now: datetime) -> Dict[int, List[Dict[str, Any]]]:
    ours = {r["meta_id"]: r for r in store._select("SELECT * FROM ad_entities",
                                                   {"kind": "ad"}, "id", 100000)
            if r["test_id"] in test_ids}
    out: Dict[int, List[Dict[str, Any]]] = {}
    for ad in await w.list_ads():
        row, reason = ours.get(ad.get("id")), _review_reason(ad)
        if row is None or reason is None:
            continue
        status = ad.get("effective_status")
        out.setdefault(row["test_id"], []).append(
            {"ad_id": ad["id"], "media_id": row["media_id"], "effective_status": status,
             "reason": reason})
        raise_alert(store, "ads_review", ad["id"], "error" if status == "DISAPPROVED"
                    else "warn", f"Meta {'rejected' if status == 'DISAPPROVED' else 'limits'}"
                    f" an ad of test {row['test_id']}", reason, LINK, now)
    return out


def _variants(store: CampaignStore, test: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The test's ad sets in creation order (= its variants, A, B, ...) with the ledger
    authorization of each (held under its campaign's id, 092)."""
    adsets = store._select("SELECT * FROM ad_entities", {"test_id": test["id"],
                                                         "kind": "adset"}, "id", 10)
    out = []
    with store.immediate() as c:
        for name, a, v in zip("ABCD", adsets, test["variants"]):
            auth = c.execute(
                "SELECT l.id FROM ad_spend_ledger l JOIN ad_entities e ON e.meta_id ="
                " l.ad_entity_id WHERE l.kind='authorized' AND l.test_id=? AND e.id=?"
                " ORDER BY l.id DESC LIMIT 1", (test["id"], a["parent_id"])).fetchone()
            out.append({"name": name, **v, "adset_id": a["meta_id"],
                        "authorization_id": auth and auth[0]})
    return out


def _metrics(rows: List[Dict[str, Any]], objective: str) -> Dict[str, Any]:
    action = RESULT_ACTION[objective]
    m: Dict[str, Any] = {"impressions": 0, "clicks": 0, "results": 0, "spend": ZERO}
    for r in rows:
        m["impressions"] += int(r.get("impressions") or 0)
        m["clicks"] += int(r.get("clicks") or 0)
        m["spend"] += Decimal(str(r.get("spend") or 0))  # account currency, not cents
        m["results"] += int(r.get(action) or 0) + sum(
            int(a.get("value") or 0) for a in r.get("actions") or []
            if a.get("action_type") == action)
    return m


async def _sync_test(store: CampaignStore, settings: InstagramMCPSettings, w: AdsWriter,
                     test: Dict[str, Any], review: List[Dict[str, Any]], today: date,
                     now: datetime) -> Dict[str, Any]:
    start = parse_dt(test["approved_at"]).astimezone(ZoneInfo(settings.timezone)).date()
    variants, spent = {}, ZERO
    for v in _variants(store, test):
        m = _metrics(await w.get_insights(v["adset_id"], since=start.isoformat(),
                                          until=max(today, start).isoformat()),
                     settings.ads_objective)
        spent += m["spend"]
        variants[v["name"]] = {**v, **m, "spend": str(m["spend"]),
                               "days": (today - start).days + 1}
        if v["authorization_id"] is None:
            continue
        rep = budget.report_spend(store, settings, v["authorization_id"], m["spend"],
                                  ad_entity_id=v["adset_id"], now=now)
        if rep["over"]:
            raise_alert(store, "ads_overspend", v["authorization_id"], "error",
                        "Meta spent more than was authorized",
                        f"Test {test['id']} variant {v['name']}: Meta reports "
                        f"{rep['reported']} {settings.ads_currency}, {rep['authorized']} "
                        "authorized. The kill switch is on.", LINK, now)
            if not budget.is_killed(store):
                budget.kill(store, f"test {test['id']}: Meta spent {rep['reported']}, "
                            f"authorized {rep['authorized']}", now, actor="system")
    out: Dict[str, Any] = {"spent": str(spent)}
    if test["status"] != "running":  # finished or cancelled: reconcile, then release
        if open_authorizations(store, test["id"]):
            failed = await _pause_active(store, settings, test["id"])
            if failed:
                _pause_alert(store, test["id"], failed, now)
                return {**out, "pause_failed": failed}
            for auth_id in open_authorizations(store, test["id"]):
                release(store, auth_id, reason=f"test {test['id']} {test['status']}")
            audit(store, "release", actor="system", test_id=test["id"], spent=str(spent))
        return out

    spec = abtest.TestSpec(**test["spec"])
    try:
        evaluation = abtest.evaluate(spec, variants)
        stop = abtest.should_stop(spec, variants, float(spent), float(test["budget_total"]))
    except ValueError as e:  # e.g. a variant missing: keep it running, show why
        evaluation, stop = {"status": "error", "error": str(e)}, None
    if stop is None and test["end_date"] and today > date.fromisoformat(test["end_date"]):
        stop = "end_date"
    result = {"synced_at": to_iso(now), "days": (today - start).days + 1, "spent": str(spent),
              "variants": variants, "evaluation": evaluation, "review": review, "stop": stop}
    store._update("ad_tests", ("result",), test["id"], {"result": result})
    if stop:
        failed = await _pause_active(store, settings, test["id"])
        if failed:
            _pause_alert(store, test["id"], failed, now)
            audit(store, "finish_failed", actor="system", test_id=test["id"], stop=stop,
                  pause_failed=failed)
            return {**out, "stop": stop, "pause_failed": failed}
        _set_status(store, test["id"], "finished", expect=("running",), reason=stop,
                    finished_at=to_iso(now))
        for auth_id in open_authorizations(store, test["id"]):
            release(store, auth_id, reason=f"test {test['id']} finished: {stop}")
        audit(store, "finish", actor="system", test_id=test["id"], stop=stop,
              winner=evaluation.get("winner"), spent=str(spent))
    return {**out, "status": evaluation["status"], "stop": stop}


def near_caps(st: Dict[str, Any]) -> Dict[str, Any]:
    """Scopes at NEAR_CAP of their cap or more (a 0 cap allows nothing: never 'near')."""
    def near(s: Dict[str, str]) -> bool:
        cap = Decimal(s["cap"])
        return cap > 0 and Decimal(s["used"]) >= cap * NEAR_CAP

    return {"daily": near(st["daily"]), "lifetime": near(st["lifetime"]),
            "tests": [t["test_id"] for t in st["tests"] if near(t)]}


def _near_cap_alerts(store: CampaignStore, settings: InstagramMCPSettings, running: set,
                     now: datetime) -> List[str]:
    st = budget.status(store, settings, now)
    near = near_caps(st)
    scopes = [(s, st[s]) for s in ("daily", "lifetime") if near[s]]
    scopes += [(f"test {t['test_id']}", t) for t in st["tests"]
               if t["test_id"] in near["tests"] and t["test_id"] in running]
    for scope, used in scopes:
        raise_alert(store, "ads_near_cap", f"{scope}:{st['day']}", "warn",
                    f"Ad spend is near the {scope} cap",
                    f"{used['used']} of {used['cap']} {st['currency']} used.", LINK, now)
    return [s for s, _ in scopes]


async def sync(store: CampaignStore, settings: InstagramMCPSettings,
               now: Optional[datetime] = None) -> Dict[str, Any]:
    """One ads_sync pass (see the module docstring). A failing test is reported in
    `errors` and never stops the others or the kill enforcement."""
    now = now or utcnow()
    today = now.astimezone(ZoneInfo(settings.timezone)).date()
    # 'approved' is the approval in progress (another process): never touched here.
    tests = [t for t in store._select(
        "SELECT * FROM ad_tests WHERE approved_at IS NOT NULL AND status IN"
        " ('running','finished','cancelled')", {}, "id", 1000)
        if t["status"] == "running" or open_authorizations(store, t["id"])
        or (t["finished_at"] and now - parse_dt(t["finished_at"]) < LATE_SPEND)]
    running = {t["id"] for t in tests if t["status"] == "running"}
    out: Dict[str, Any] = {"tests": {}, "errors": []}
    try:
        w = AdsWriter(settings, store=store)
    except NotConfigured:
        return {"skipped": "ads not configured"}
    async with w:
        killed = budget.is_killed(store)
        if killed:
            out["kill"] = await enforce_kill(store, w, now)
        review: Dict[int, List[Dict[str, Any]]] = {}
        if running:
            try:
                review = await _review(store, w, running, now)
            except Exception as e:
                logger.exception("ads_review_failed")
                out["errors"].append(f"review: {e!r}")
        for t in tests:
            try:
                out["tests"][t["id"]] = await _sync_test(store, settings, w, t,
                                                         review.get(t["id"], []), today, now)
            except Exception as e:
                logger.exception("ads_sync_test_failed", test_id=t["id"])
                out["errors"].append(f"test {t['id']}: {e!r}")
        if not killed and budget.is_killed(store):  # an over-spend just killed
            out["kill"] = await enforce_kill(store, w, now)
    out["near_cap"] = _near_cap_alerts(store, settings, running, now)
    return out


def results(store: CampaignStore, settings: InstagramMCPSettings,
            test_id: int) -> Dict[str, Any]:
    """A test with its latest snapshot (`result`: per-variant metrics, evaluation with
    p-values, winner and lift, days, review issues), its spend against its budget and the
    near-cap flags. KeyError when missing."""
    test = _shown(store, settings, store._get("ad_tests", test_id))
    st = budget.status(store, settings)
    near = near_caps(st)
    spec = test["spec"]
    return {**test, "entities": _entities(store, test_id),
            "min_days": spec["min_days"], "max_days": spec["max_days"],
            "spend": {"reported": (test["result"] or {}).get("spent"),
                      "counted": next((t["used"] for t in st["tests"]
                                       if t["test_id"] == test_id), "0"),
                      "budget": test["budget_total"], "currency": test["currency"]},
            "near_cap": {"daily": near["daily"], "lifetime": near["lifetime"],
                         "test": test_id in near["tests"]}}
