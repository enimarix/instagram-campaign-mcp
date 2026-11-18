"""
Ad budget guard (step 091): nothing spends ad money without passing `authorize_spend()`.

- Caps in settings (`ADS_DAILY_CAP`, `ADS_TEST_CAP`, `ADS_LIFETIME_CAP`, in `ADS_CURRENCY`);
  0, the default, allows no spend at all.
- The ledger (`ad_spend_ledger`) counts what is used: every `authorized` row not yet
  `released`, plus every `reported` row (Meta's spend, step 095). The daily cap counts rows
  created on the owner-local day (`settings.timezone`), or a row's `daily_amount` on every
  day from its creation to its `daily_until` (an ad set's lifetime budget spread over its
  days, 092); the test cap, rows of that test.
  ponytail: while a test runs, its authorization and its reported spend both count, so the
  guard over-counts (the safe side) until 095 reconciles.
- One `BEGIN IMMEDIATE` transaction reads the kill switch and the ledger and writes the
  authorization, so two processes can never both pass the same cap.
- The kill switch blocks every new authorization. 095's worker pauses ads while it is on.
- Functions that can spend are marked `@spends`; tests/test_ads_budget.py fails when an
  src/ads module sends a write request outside one, or a `@spends` function skips
  `authorize_spend()`.

Local caps are not the only line: 092 creates every ad set with a lifetime budget and an
end date and every campaign with a spend cap, so Meta stops spending too (GOAL.md §5.4).
"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Dict, List, Optional, Tuple, TypeVar
from zoneinfo import ZoneInfo

import structlog

from ..config import InstagramMCPSettings
from ..store import CampaignStore, to_iso, utcnow

logger = structlog.get_logger(__name__)

KILL_KEY = "ads_kill"  # worker_state row
ZERO = Decimal(0)
F = TypeVar("F", bound=Callable[..., Any])


class BudgetRefused(Exception):
    """code: killed | daily_cap | test_cap | lifetime_cap | invalid."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def spends(fn: F) -> F:
    """Marks a function that can spend ad money: it must call authorize_spend() before
    its request (enforced by tests/test_ads_budget.py)."""
    fn.__spends__ = True
    return fn


def _amount(value: Any) -> Decimal:
    # Floats are refused: money is a Decimal, an int or a decimal string.
    if isinstance(value, bool) or not isinstance(value, (Decimal, int, str)):
        raise BudgetRefused("invalid", "amount must be a Decimal, an int or a string")
    try:
        amount = Decimal(value)
    except InvalidOperation:
        raise BudgetRefused("invalid", f"amount is not a number: {value!r}") from None
    if not amount.is_finite() or amount <= 0:
        raise BudgetRefused("invalid", "amount must be above 0")
    return amount


def _day_bounds(tz: str, now: datetime) -> Tuple[str, str, str]:
    """[start, end) of the owner-local day of `now`, as stored ISO UTC strings, and the
    day itself (YYYY-MM-DD)."""
    zone = ZoneInfo(tz)
    day = now.astimezone(zone).date()
    return (to_iso(datetime.combine(day, time(), tzinfo=zone)),
            to_iso(datetime.combine(day + timedelta(days=1), time(), tzinfo=zone)),
            day.isoformat())


def _kill_state(c) -> Dict[str, Any]:
    row = c.execute("SELECT value FROM worker_state WHERE key=?", (KILL_KEY,)).fetchone()
    return json.loads(row[0]) if row else {"killed": False, "killed_at": None,
                                           "killed_reason": None}


def _usage(c, settings: InstagramMCPSettings, now: datetime) -> Dict[str, Any]:
    # ponytail: sums the whole ledger in Python (exact Decimal); fine for thousands of rows.
    rows = c.execute("SELECT * FROM ad_spend_ledger").fetchall()
    released = {r["authorization_id"] for r in rows if r["kind"] == "released"}
    start, end, today = _day_bounds(settings.timezone, now)
    usage: Dict[str, Any] = {"daily": ZERO, "lifetime": ZERO, "tests": {}, "currencies": set()}
    for r in rows:
        if r["kind"] == "released" or r["id"] in released:
            continue
        amount = Decimal(r["amount"])
        usage["currencies"].add(r["currency"])
        usage["lifetime"] += amount
        if r["daily_amount"] is not None:
            # Spread rows count on every day of their span. A later day is never fuller
            # than today (every span covering it covers today too), so checking today is
            # enough.
            if r["created_at"] < end and r["daily_until"] >= today:
                usage["daily"] += Decimal(r["daily_amount"])
        elif start <= r["created_at"] < end:
            usage["daily"] += amount
        if r["test_id"] is not None:
            usage["tests"][r["test_id"]] = usage["tests"].get(r["test_id"], ZERO) + amount
    return usage


def authorize_spend(
    store: CampaignStore,
    settings: InstagramMCPSettings,
    amount: Any,
    *,
    test_id: Optional[int] = None,
    ad_entity_id: Optional[str] = None,
    reason: str,
    daily_amount: Any = None,
    daily_until: Optional[date] = None,
    check_only: bool = False,
    now: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    """Reserve `amount` (account currency) or raise BudgetRefused. Returns the ledger row.

    Without a test_id the amount alone must still fit under the test cap.
    `daily_amount` + `daily_until` (owner-local last day): the daily cap counts
    `daily_amount` on each day until then instead of `amount` today (a lifetime budget).
    `check_only`: run every check (kill switch, caps) but reserve nothing and return None;
    `amount` may then be 0 (a write that cannot spend by itself, like a paused ad).
    """
    if check_only and not isinstance(amount, bool) and amount in (0, "0"):
        amount = ZERO
    else:
        amount = _amount(amount)
    if (daily_amount is None) != (daily_until is None):
        raise BudgetRefused("invalid", "give daily_amount and daily_until together")
    if daily_amount is not None:
        daily_amount = _amount(daily_amount)
        if (daily_amount > amount or isinstance(daily_until, datetime)
                or not isinstance(daily_until, date)):
            raise BudgetRefused("invalid", "daily_amount must be at most amount, daily_until"
                                " a date")
    if not isinstance(reason, str) or not reason.strip():
        raise BudgetRefused("invalid", "a reason is required")
    if test_id is not None and (isinstance(test_id, bool) or not isinstance(test_id, int)):
        raise BudgetRefused("invalid", "test_id must be an int")
    if ad_entity_id is not None and not isinstance(ad_entity_id, str):
        raise BudgetRefused("invalid", "ad_entity_id must be a string")
    now = now or utcnow()
    currency = settings.ads_currency
    with store.immediate() as c:
        if _kill_state(c)["killed"]:
            raise BudgetRefused("killed", "the ads kill switch is on: no new spend")
        usage = _usage(c, settings, now)
        if usage["currencies"] - {currency}:
            raise BudgetRefused("invalid", f"the ledger holds spend in "
                                f"{sorted(usage['currencies'])}, not only {currency}")
        test_used = usage["tests"].get(test_id, ZERO) if test_id is not None else ZERO
        daily = amount if daily_amount is None else daily_amount
        for code, used, ask, cap in (
                ("daily_cap", usage["daily"], daily, settings.ads_daily_cap),
                ("test_cap", test_used, amount, settings.ads_test_cap),
                ("lifetime_cap", usage["lifetime"], amount, settings.ads_lifetime_cap)):
            if used + ask > cap:
                raise BudgetRefused(code, f"{ask} {currency} would bring {code[:-4]} spend "
                                    f"to {used + ask}, above the cap of {cap}")
        if check_only:
            return None
        cur = c.execute(
            "INSERT INTO ad_spend_ledger (kind, amount, currency, test_id, ad_entity_id,"
            " reason, daily_amount, daily_until, created_at)"
            " VALUES ('authorized',?,?,?,?,?,?,?,?)",
            (str(amount), currency, test_id, ad_entity_id, reason.strip(),
             None if daily_amount is None else str(daily_amount),
             None if daily_until is None else daily_until.isoformat(), to_iso(now)))
        row = dict(c.execute("SELECT * FROM ad_spend_ledger WHERE id=?",
                             (cur.lastrowid,)).fetchone())
    logger.info("ad_spend_authorized", id=row["id"], amount=row["amount"], currency=currency,
                test_id=test_id)
    return row


def release(store: CampaignStore, authorization_id: int, *, reason: str = "released",
            now: Optional[datetime] = None) -> Dict[str, Any]:
    """Free an authorization in full (a test stopped under budget; what it did spend comes
    back as `reported` rows in 095). KeyError if missing, ValueError if not releasable."""
    with store.immediate() as c:
        row = c.execute("SELECT * FROM ad_spend_ledger WHERE id=?",
                        (authorization_id,)).fetchone()
        if row is None:
            raise KeyError(f"No authorization with id {authorization_id}")
        if row["kind"] != "authorized":
            raise ValueError(f"ledger row {authorization_id} is {row['kind']}, not authorized")
        if c.execute("SELECT 1 FROM ad_spend_ledger WHERE kind='released' AND"
                     " authorization_id=?", (authorization_id,)).fetchone():
            raise ValueError(f"authorization {authorization_id} is already released")
        cur = c.execute(
            "INSERT INTO ad_spend_ledger (kind, amount, currency, test_id, ad_entity_id,"
            " authorization_id, reason, created_at) VALUES ('released',?,?,?,?,?,?,?)",
            (row["amount"], row["currency"], row["test_id"], row["ad_entity_id"],
             authorization_id, reason, to_iso(now or utcnow())))
        out = dict(c.execute("SELECT * FROM ad_spend_ledger WHERE id=?",
                             (cur.lastrowid,)).fetchone())
    logger.info("ad_spend_released", authorization_id=authorization_id, amount=out["amount"])
    return out


def kill(store: CampaignStore, reason: str = "kill switch",
         now: Optional[datetime] = None) -> None:
    """Block every new authorization; 095's worker pauses the ads (paused_ids_needed)."""
    store.set_state(KILL_KEY, {"killed": True, "killed_at": to_iso(now or utcnow()),
                               "killed_reason": reason})
    logger.warning("ads_killed", reason=reason)


def unkill(store: CampaignStore) -> None:
    """Allow spend again. The API asks the website password first."""
    store.set_state(KILL_KEY, {"killed": False, "killed_at": None, "killed_reason": None})
    logger.warning("ads_unkilled")


def paused_ids_needed(store: CampaignStore) -> List[str]:
    """While killed: the ad ids of open authorizations, which 092/095 must pause on Meta.
    Empty when not killed. ponytail: ledger ids only; 095 also pauses every other ACTIVE
    ad of the account it lists, since ads made outside the studio are not in the ledger."""
    with store.immediate() as c:
        if not _kill_state(c)["killed"]:
            return []
        rows = c.execute(
            "SELECT DISTINCT a.ad_entity_id FROM ad_spend_ledger a WHERE a.kind='authorized'"
            " AND a.ad_entity_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM ad_spend_ledger r"
            " WHERE r.kind='released' AND r.authorization_id=a.id) ORDER BY 1").fetchall()
    return [r[0] for r in rows]


def status(store: CampaignStore, settings: InstagramMCPSettings,
           now: Optional[datetime] = None) -> Dict[str, Any]:
    """Caps, used and remaining per scope (money as strings), and the kill switch."""
    now = now or utcnow()
    with store.immediate() as c:
        killed = _kill_state(c)
        usage = _usage(c, settings, now)

    def scope(cap: Decimal, used: Decimal) -> Dict[str, str]:
        return {"cap": str(cap), "used": str(used), "remaining": str(max(cap - used, ZERO))}

    return {
        **killed,
        "currency": settings.ads_currency,
        "day": now.astimezone(ZoneInfo(settings.timezone)).date().isoformat(),
        "daily": scope(settings.ads_daily_cap, usage["daily"]),
        "lifetime": scope(settings.ads_lifetime_cap, usage["lifetime"]),
        "test_cap": str(settings.ads_test_cap),
        "tests": [{"test_id": t, **scope(settings.ads_test_cap, used)}
                  for t, used in sorted(usage["tests"].items())],
        "currency_conflict": sorted(usage["currencies"] - {settings.ads_currency}),
    }
