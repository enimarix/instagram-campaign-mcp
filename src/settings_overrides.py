"""
Owner-editable settings (step 124): the website overrides `.env` for the fields in EDITABLE.

- Overrides live in worker_state[KEY] = {"version": n, "values": {field: value}}; every
  write bumps the version inside one BEGIN IMMEDIATE transaction.
- Effective settings = InstagramMCPSettings(**{.env values, **overrides}): the same
  validators as `.env`, so a bad value is refused with their message and nothing is stored.
- refresh() applies a new version IN PLACE onto a process's settings object, so everything
  holding it sees the change. Called per API request (app.py), every REFRESH_EVERY s in
  the worker, per MCP tool call, by CLI commands at start and by the budget guard at every
  authorize_spend(): every process (API, worker, MCP server, agent runs) follows within
  REFRESH_EVERY s, without a restart.
- Secrets (tokens, passwords, keys) are never editable (tests/test_settings_overrides.py).
- Raising a money cap needs the website password again: update() raises PasswordNeeded
  unless `confirmed`. A currency change while a cap is above 0 counts as raising (it
  changes what every cap means). Changes to ads fields write an ads_audit row.
- Ad presets (127): a preset a running test uses can't be removed (SettingsInvalid).
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from contextlib import suppress
from decimal import Decimal
from typing import Any, Dict, Iterable, Literal, get_args, get_origin

import structlog
from pydantic import BaseModel, ValidationError

from .config import InstagramMCPSettings
from .store import CampaignStore, to_iso, utcnow

logger = structlog.get_logger(__name__)

KEY = "settings_overrides"
# field -> website section. Making a field editable is one line here; never a secret.
EDITABLE: Dict[str, str] = {
    "ads_daily_cap": "ads",
    "ads_test_cap": "ads",
    "ads_lifetime_cap": "ads",
    "ads_currency": "ads",
    "ads_objective": "ads",
    "ads_test_days": "ads",
    "ads_max_running_tests": "ads",
    "meta_ad_account_id": "ads",
    "meta_page_id": "ads",
    "ads_dsa_beneficiary": "ads",
    "ads_dsa_payor": "ads",
    "ads_presets": "ads",
    "batch_size": "studio",
    "max_posts_per_day": "studio",
    "explore_share": "studio",
    "humour_share": "studio",
}
CAPS = ("ads_daily_cap", "ads_test_cap", "ads_lifetime_cap")
REFRESH_EVERY = 30.0  # seconds, the worker's check


class SettingsInvalid(Exception):
    def __init__(self, message: str, field: Any = None):
        super().__init__(message)
        self.message = message
        self.field = field


class PasswordNeeded(Exception):
    """The change raises a money cap: ask the website password again."""


def _stored(store: CampaignStore) -> Dict[str, Any]:
    row = store.get_state(KEY) or {"version": 0, "values": {}}
    return {"version": row["version"],
            "values": {k: v for k, v in row["values"].items() if k in EDITABLE}}


def _env_values(settings: InstagramMCPSettings) -> Dict[str, Any]:
    if settings._env_values is None:  # before any override reached this object
        settings._env_values = {k: getattr(settings, k) for k in EDITABLE}
    return settings._env_values


def _effective(settings: InstagramMCPSettings, values: Dict[str, Any]) -> InstagramMCPSettings:
    try:
        return InstagramMCPSettings(**{**_env_values(settings), **values})
    except ValidationError as e:
        err = e.errors()[0]
        field = err["loc"][0] if err["loc"] else None
        where = ".".join(map(str, err["loc"]))  # e.g. ads_presets.1.countries
        raise SettingsInvalid(f"{where}: {err['msg']}" if field else err["msg"], field) from None


def _apply(settings: InstagramMCPSettings, new: InstagramMCPSettings, version: int) -> None:
    settings.__dict__.update({k: getattr(new, k) for k in EDITABLE})
    settings._overrides_version = version


def refresh(store: CampaignStore, settings: InstagramMCPSettings) -> InstagramMCPSettings:
    """Apply the stored overrides to `settings` in place when their version changed."""
    row = _stored(store)
    if row["version"] != settings._overrides_version:
        try:
            _apply(settings, _effective(settings, row["values"]), row["version"])
        except SettingsInvalid as e:  # e.g. .env changed under them: keep what we have
            settings._overrides_version = row["version"]
            logger.error("settings_overrides_invalid", message=e.message)
    return settings


async def refresh_loop(store: CampaignStore, settings: InstagramMCPSettings,
                       every: float = REFRESH_EVERY) -> None:
    """The worker's side: refresh every `every` s, until cancelled."""
    while True:
        with suppress(sqlite3.Error):
            refresh(store, settings)
        await asyncio.sleep(every)


def _json(v: Any) -> Any:
    if isinstance(v, list):
        return [_json(x) for x in v]
    if isinstance(v, BaseModel):
        return v.model_dump(mode="json")
    return str(v) if isinstance(v, Decimal) else v  # money stays exact


def _form(name: str) -> Dict[str, Any]:
    """What the website's form needs: type, choices, limits, description."""
    f = InstagramMCPSettings.model_fields[name]
    t = f.annotation
    if name == "ads_presets":  # its own editor in the website
        return {"type": "presets", "description": f.description}
    if get_origin(t) is Literal:
        out: Dict[str, Any] = {"type": "choice", "choices": list(get_args(t))}
    else:
        base = next((a for a in get_args(t) if a is not type(None)), t)  # Optional[x] -> x
        out = {"type": {Decimal: "money", int: "int", float: "float", bool: "bool"}
               .get(base, "text")}
    for m in f.metadata:
        for k in ("ge", "gt", "le", "lt", "max_length"):
            if getattr(m, k, None) is not None:
                out[k] = getattr(m, k)
    return {**out, "description": f.description}


def editable(store: CampaignStore, settings: InstagramMCPSettings) -> Dict[str, Any]:
    """Each editable field: current value, .env default, overridden?, and its form."""
    refresh(store, settings)
    overridden = _stored(store)["values"]
    env = _env_values(settings)
    return {"version": settings._overrides_version, "fields": [
        {"name": k, "section": section, "value": _json(getattr(settings, k)),
         "default": _json(env[k]), "overridden": k in overridden, **_form(k)}
        for k, section in EDITABLE.items()]}


def _raises_cap(old: Dict[str, Any], new: InstagramMCPSettings) -> bool:
    if any(getattr(new, k) > old[k] for k in CAPS):
        return True
    return new.ads_currency != old["ads_currency"] and any(getattr(new, k) > 0 for k in CAPS)


def _presets_in_use(c: sqlite3.Connection, new: InstagramMCPSettings) -> None:
    """Refuse removing a preset an approved or running test uses (its ads exist)."""
    from .ads.tests import OPEN_RUNNING  # here: ads imports this module

    ids = {p.id for p in new.ads_presets}
    for test_id, variants in c.execute(
            f"SELECT id, variants FROM ad_tests WHERE status IN {OPEN_RUNNING}"):
        used = sorted({v["preset"] for v in json.loads(variants)} - ids)
        if used:
            raise SettingsInvalid(f"preset {used[0]} is used by running test {test_id}: "
                                  "remove it once the test ends", "ads_presets")


def update(store: CampaignStore, settings: InstagramMCPSettings, values: Dict[str, Any],
           reset: Iterable[str] = (), *, confirmed: bool = False,
           actor: str = "owner") -> Dict[str, Any]:
    """Validate and store overrides (`reset`: back to the .env value), apply them to
    `settings` and return editable(). SettingsInvalid: nothing stored. PasswordNeeded: a
    cap rises and the change is not `confirmed`."""
    reset = list(reset)
    bad = sorted({*values, *reset} - set(EDITABLE))
    if bad:
        raise SettingsInvalid(f"not editable on the website: {', '.join(bad)}", bad[0])
    refresh(store, settings)
    old = {k: getattr(settings, k) for k in EDITABLE}
    with store.immediate() as c:
        row = c.execute("SELECT value FROM worker_state WHERE key=?", (KEY,)).fetchone()
        state = json.loads(row[0]) if row else {"version": 0, "values": {}}
        kept = {k: v for k, v in state["values"].items() if k in EDITABLE and k not in reset}
        new = _effective(settings, {**kept, **values})
        _presets_in_use(c, new)
        if not confirmed and _raises_cap(old, new):
            raise PasswordNeeded()
        keys = {*kept, *values}
        version = state["version"] + 1
        c.execute(
            "INSERT INTO worker_state (key, value, updated_at) VALUES (?,?,?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value,"
            " updated_at=excluded.updated_at",
            (KEY, json.dumps({"version": version,
                              "values": new.model_dump(mode="json", include=keys)}),
             to_iso(utcnow())))
    _apply(settings, new, version)
    changes = {k: [_json(old[k]), _json(getattr(new, k))] for k in EDITABLE
               if EDITABLE[k] == "ads" and old[k] != getattr(new, k)}
    if changes:
        from .ads.budget import audit  # here: budget imports this module

        audit(store, "settings", actor=actor, changes=changes)
    logger.info("settings_updated", version=version, fields=sorted(keys | set(reset)))
    return editable(store, settings)
