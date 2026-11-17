"""Rights rules (GOAL.md §5.1): every row of the table, both columns."""

import re

import pytest

from src.store import STUDIO_SCHEMA
from src.studio.rights import (
    RIGHTS_BASES,
    attribution,
    basis,
    can_advertise,
    can_publish,
    cc_licence,
)


def src(rights_basis, **fields):
    row = {"rights_basis": rights_basis, "author": "jane", "url": "https://x.test/r/1",
           "rights_note": None}
    row.update(fields)
    return row


def test_rights_bases_match_store_check_constraint():
    m = re.search(r"rights_basis IN\s*\(([^)]*)\)", STUDIO_SCHEMA)
    in_store = {v.strip().strip("'") for v in m.group(1).split(",")}
    assert set(RIGHTS_BASES) == in_store


# --- Organic post column -------------------------------------------------------

@pytest.mark.parametrize("b", ["own", "licensed", "public_domain", "permission"])
def test_publish_yes(b):
    assert can_publish(src(b))


def test_publish_cc_by_and_by_sa_only():
    assert can_publish(src("cc"), licence="CC BY 4.0")
    assert can_publish(src("cc", licence="cc-by-sa-4.0"))
    assert can_publish(src("cc"), licence="CC_BY_SA").reason == "cc: CC BY-SA, with attribution"


@pytest.mark.parametrize("lic", ["CC BY-NC 4.0", "cc by-nc-sa", "CC-BY-ND-4.0",
                                 "cc by nc nd 3.0", "CC0", "CC BY 4.0 NC"])
def test_publish_cc_refused_variants(lic):
    d = can_publish(src("cc"), licence=lic)
    assert not d and "cc:" in d.reason


@pytest.mark.parametrize("lic", [None, "", "BY 4.0", "MIT", "CC BY BY", "CC BY-SA 4.0 or later"])
def test_publish_cc_malformed_or_missing_licence(lic):
    assert not can_publish(src("cc"), licence=lic)


def test_publish_cc_nc_reason_names_the_variant():
    assert "NC/ND" in can_publish(src("cc"), licence="CC BY-NC 4.0").reason


def test_publish_commentary_needs_confirmation():
    assert not can_publish(src("commentary"))
    assert can_publish(src("commentary"), confirmed=True)


def test_publish_unknown_never_even_confirmed():
    assert not can_publish(src("unknown"), confirmed=True)


@pytest.mark.parametrize("row", [None, {}, {"rights_basis": None}, {"rights_basis": "OWN"},
                                 {"rights_basis": "anything"}])
def test_missing_or_bad_basis_is_unknown(row):
    assert basis(row) == "unknown"
    assert not can_publish(row, confirmed=True)
    assert not can_advertise(row, ads_allowed=True)


@pytest.mark.parametrize("b", ["cc", "permission", "commentary"])
def test_publish_credit_bases_need_an_author(b):
    assert not can_publish(src(b, author="  "), True, licence="CC BY")


# --- Paid ad column ------------------------------------------------------------

@pytest.mark.parametrize("b", ["own", "public_domain"])
def test_ads_yes(b):
    assert can_advertise(src(b))


@pytest.mark.parametrize("b", ["licensed", "permission"])
def test_ads_only_when_allowed(b):
    assert not can_advertise(src(b))
    assert not can_advertise(src(b), ads_allowed=False)
    assert can_advertise(src(b), ads_allowed=True)
    assert can_advertise(src(b, ads_allowed=True))
    assert not can_advertise(src(b, ads_allowed=True), ads_allowed=False)


@pytest.mark.parametrize("b", ["cc", "commentary", "unknown"])
def test_ads_never(b):
    assert not can_advertise(src(b, licence="CC BY 4.0"), ads_allowed=True)


# --- Attribution ----------------------------------------------------------------

def test_attribution_cc():
    assert attribution(src("cc"), licence="cc by-sa 4.0") == "jane, https://x.test/r/1, CC BY-SA 4.0"
    assert attribution(src("cc", url=None, licence="CC BY")) == "jane, CC BY"


def test_attribution_permission_and_commentary():
    assert attribution(src("permission")) == "Credit: jane"
    assert attribution(src("commentary")) == "@jane"
    assert attribution(src("commentary", author="@jane")) == "@jane"
    assert attribution(src("commentary", author=None)) is None


@pytest.mark.parametrize("b", ["own", "public_domain", "licensed"])
def test_attribution_none_unless_note_requires_it(b):
    assert attribution(src(b)) is None
    assert attribution(src(b, rights_note="Pexels licence, no attribution needed")) is None
    assert attribution(src(b, rights_note="Attribution required by the licence")) == "Credit: jane"


def test_attribution_unknown_none():
    assert attribution(src("unknown")) is None
    assert cc_licence("CC BY-NC") is None
