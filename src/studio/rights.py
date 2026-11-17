"""
Rights rules (GOAL.md §5.1) as pure functions over a `sources` row.

This is an engineering rule, not legal advice.

Every function takes a plain dict (a `get_source()` result) and does no I/O. A
missing or unrecognised `rights_basis` is treated as `unknown`, never as permissive.

Facts the `sources` table has no column for yet are passed explicitly, falling back
to a key of the same name on the dict so a later column needs no caller change:
- `licence` (str): the CC licence of a `cc` source, e.g. "CC BY-SA 4.0". Only
  CC BY and CC BY-SA are accepted (case/format-insensitive, optional version).
- `ads_allowed` (bool): the licence (`licensed`) or the creator in writing
  (`permission`) allows paid ads.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

# Must equal the CHECK constraint on sources.rights_basis in src/store.py (tested).
RIGHTS_BASES = ("own", "licensed", "public_domain", "cc", "permission", "commentary", "unknown")

# Bases whose organic post must carry a credit, so they need an author to credit.
CREDIT_REQUIRED = ("cc", "permission", "commentary")

# Normalised licence: "CC BY", "CC BY SA", optionally followed by a version like "4.0".
_CC_OK = re.compile(r"^CC BY( SA)?( \d+(?:\.\d+)?)?$")
_ATTRIBUTION_NOTE = re.compile(r"\battribution required\b|\brequires attribution\b", re.I)


@dataclass(frozen=True)
class Decision:
    """A yes/no with a reason the UI or the agent can show. Truthy when allowed."""

    allowed: bool
    reason: str

    def __bool__(self) -> bool:
        return self.allowed


def basis(source: Optional[Dict[str, Any]]) -> str:
    """The source's rights_basis; None, missing or unrecognised values become `unknown`."""
    value = (source or {}).get("rights_basis")
    return value if value in RIGHTS_BASES else "unknown"


def cc_licence(licence: Optional[str]) -> Optional[str]:
    """Canonical "CC BY[-SA][ <version>]" when `licence` is an accepted CC licence, else None.

    NC and ND variants, CC0 and anything malformed return None.
    """
    if not licence:
        return None
    norm = " ".join(re.sub(r"[^A-Z0-9.]+", " ", licence.upper()).split())
    m = _CC_OK.match(norm)
    if not m:
        return None
    return "CC BY" + ("-SA" if m.group(1) else "") + (m.group(2) or "")


def _cc_refusal(licence: Optional[str]) -> str:
    if not licence:
        return "cc: licence not recorded"
    tokens = set(re.sub(r"[^A-Z0-9]+", " ", licence.upper()).split())
    if tokens & {"NC", "ND"}:
        return (f"cc: {licence!r} refused: NC/ND variants are not allowed "
                "(a brand account is commercial use and a remix is a derivative)")
    return f"cc: {licence!r} is not CC BY or CC BY-SA"


def can_publish(
    source: Optional[Dict[str, Any]], confirmed: bool = False, *, licence: Optional[str] = None
) -> Decision:
    """May this source appear in an organic post? `confirmed` is the owner's per-video
    confirmation, required for `commentary`."""
    b = basis(source)
    src = source or {}
    if b == "unknown":
        return Decision(False, "unknown: rights not recorded; reference only, never published")
    if b in CREDIT_REQUIRED and not (src.get("author") or "").strip():
        return Decision(False, f"{b}: no author recorded, so the required credit cannot be given")
    if b == "cc":
        lic = licence if licence is not None else src.get("licence")
        canonical = cc_licence(lic)
        if not canonical:
            return Decision(False, _cc_refusal(lic))
        return Decision(True, f"cc: {canonical}, with attribution")
    if b == "commentary":
        if not confirmed:
            return Decision(False, "commentary: needs the owner's confirmation for this video")
        return Decision(True, "commentary: confirmed by the owner, with visible credit")
    if b == "permission":
        return Decision(True, "permission: with credit to the creator")
    return Decision(True, f"{b}: allowed")


def can_advertise(
    source: Optional[Dict[str, Any]], *, ads_allowed: Optional[bool] = None
) -> Decision:
    """May this source be used in a paid ad?"""
    b = basis(source)
    if b in ("own", "public_domain"):
        return Decision(True, f"{b}: allowed in ads")
    if b in ("licensed", "permission"):
        allowed = ads_allowed if ads_allowed is not None else (source or {}).get("ads_allowed")
        if allowed in (True, 1):  # SQLite stores booleans as 0/1
            return Decision(True, f"{b}: ads allowed")
        who = "the licence" if b == "licensed" else "the creator in writing"
        return Decision(False, f"{b}: ads not allowed unless {who} allows advertising")
    if b == "cc":
        return Decision(False, "cc: never used in ads")
    if b == "commentary":
        return Decision(False, "commentary: never used in ads")
    return Decision(False, "unknown: never used in ads")


def attribution(source: Optional[Dict[str, Any]], *, licence: Optional[str] = None) -> Optional[str]:
    """The credit text a post of this source must carry, or None when none is required.

    - cc: "<author>, <url>, <licence>" (url left out when missing).
    - permission: "Credit: <author>".
    - commentary: "@<creator>", shown on screen; step 069 also puts it in the caption.
    - own / public_domain / licensed: None, unless `rights_note` says "attribution
      required" or "requires attribution", then "Credit: <author or url>".
    - unknown: None (never published).
    """
    b = basis(source)
    src = source or {}
    author = (src.get("author") or "").strip()
    url = (src.get("url") or "").strip()
    if b == "cc":
        lic = licence if licence is not None else src.get("licence")
        return ", ".join(p for p in (author, url, cc_licence(lic) or (lic or "").strip()) if p)
    if b == "permission":
        return f"Credit: {author}" if author else None
    if b == "commentary":
        return "@" + author.lstrip("@") if author.lstrip("@") else None
    if b in ("own", "public_domain", "licensed"):
        if _ATTRIBUTION_NOTE.search(src.get("rights_note") or "") and (author or url):
            return f"Credit: {author or url}"
    return None
