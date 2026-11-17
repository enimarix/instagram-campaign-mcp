"""Studio tables (sources, ideas, assets) and the asset lifecycle."""

import sqlite3
from datetime import date

import pytest

from src.store import MIGRATIONS, SCHEMA, CampaignStore
from src.studio.assets import ALLOWED, MOVES, InvalidTransition, set_verdict, transition
from src.taxonomy import TaxonomyError

# Shortest path of (to, actor) moves from 'rendering' to each status.
PATH = {
    "rendering": [],
    "ready": [("ready", "worker")],
    "failed": [("failed", "worker")],
    "revision_requested": [("ready", "worker"), ("revision_requested", "owner")],
    "archived": [("ready", "worker"), ("archived", "owner")],
    "approved": [("ready", "worker"), ("approved", "owner")],
    "scheduled": [("ready", "worker"), ("approved", "owner"), ("scheduled", "system")],
    "publish_check": [("ready", "worker"), ("approved", "owner"), ("scheduled", "system"),
                      ("publish_check", "worker")],
    "published": [("ready", "worker"), ("approved", "owner"), ("scheduled", "system"),
                  ("published", "worker")],
}
# One move per status that the table forbids for every actor.
FORBIDDEN = {
    "rendering": "approved", "ready": "published", "failed": "ready",
    "needs_reaction": "ready", "revision_requested": "ready", "approved": "published",
    "scheduled": "ready", "publish_check": "scheduled", "published": "approved",
    "archived": "ready",
}


def _asset_in(store, status, **fields):
    idea = store.add_idea("motion", pillar="myths", hook_type="pov")
    if status == "needs_reaction":
        return store.add_asset(idea["id"], status="needs_reaction", **fields)
    asset = store.add_asset(idea["id"], **fields)
    for to, actor in PATH[status]:
        asset = transition(store, asset["id"], to, actor=actor)
    assert asset["status"] == status
    return asset


def test_migration_1_database_upgrades_to_2_keeping_data(tmp_path):
    db = str(tmp_path / "v1.db")
    conn = sqlite3.connect(db)
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO post_labels (media_id, campaign, created_at)"
                 " VALUES ('m1', 'launch', '2026-01-01T00:00:00+00:00')")
    conn.execute("PRAGMA user_version=1")
    conn.commit()
    conn.close()
    s = CampaignStore(db)
    try:
        assert s.get_label("m1")["campaign"] == "launch"
        assert s.list_assets() == []
    finally:
        s.close()
    conn = sqlite3.connect(db)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
    conn.close()


def test_create_get_list_and_json_columns(store):
    src = store.add_source("instagram", url="https://x/r/1", author="alice",
                           stats={"views": 1200}, rights_basis="commentary")
    store.add_source("pexels", rights_basis="licensed")
    assert store.get_source(src["id"])["stats"] == {"views": 1200}
    assert [s["provider"] for s in store.list_sources(rights_basis="commentary")] == ["instagram"]
    assert [s["provider"] for s in store.list_sources(provider="pexels")] == ["pexels"]

    idea = store.add_idea("remix", source_id=src["id"], citations=[{"url": "https://w"}],
                          batch_date=date(2026, 11, 17))
    store.add_idea("motion", batch_date="2026-11-18")
    assert store.get_idea(idea["id"])["citations"] == [{"url": "https://w"}]
    remix_17 = store.list_ideas(track="remix", batch_date=date(2026, 11, 17))
    assert [i["id"] for i in remix_17] == [idea["id"]]

    a = store.add_asset(idea["id"], recipe={"template": "FactQuest"}, batch_date="2026-11-17")
    assert a["status"] == "rendering" and a["verdict"] == "none"
    assert store.get_asset(a["id"])["recipe"] == {"template": "FactQuest"}
    with pytest.raises(KeyError):
        store.get_asset(999)
    with pytest.raises(TypeError, match="bogus"):
        store.add_source("x", bogus=1)


def test_list_assets_filters_and_order(store):
    remix = store.add_idea("remix")
    motion = store.add_idea("motion")
    low = store.add_asset(remix["id"], self_score=3, batch_date="2026-11-17")
    unscored = store.add_asset(remix["id"], batch_date="2026-11-17")
    high = store.add_asset(motion["id"], self_score=9, batch_date="2026-11-17")
    store.add_asset(motion["id"], self_score=10, batch_date="2026-11-16")
    ids = lambda rows: [r["id"] for r in rows]  # noqa: E731
    day = "2026-11-17"
    assert ids(store.list_assets(batch_date=day)) == [high["id"], low["id"], unscored["id"]]
    assert ids(store.list_assets(batch_date=day, track="remix")) == [low["id"], unscored["id"]]
    transition(store, low["id"], "ready", actor="worker")
    set_verdict(store, low["id"], "liked")
    assert ids(store.list_assets(status="ready", verdict="liked")) == [low["id"]]


def test_check_constraints(store):
    idea = store.add_idea("motion")
    with pytest.raises(sqlite3.IntegrityError):
        store.add_asset(idea["id"], self_score=11)
    with pytest.raises(sqlite3.IntegrityError):
        store.add_source("x", rights_basis="probably_fine")


def test_bad_idea_id_violates_foreign_key(store):
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        store.add_asset(12345)


def test_unknown_taxonomy_tag_is_rejected_with_valid_list(store):
    with pytest.raises(TaxonomyError, match="valid: remix, motion"):
        store.add_idea("vlog")
    with pytest.raises(TaxonomyError, match="fun_facts"):
        store.add_idea("motion", pillar="cooking")
    with pytest.raises(TaxonomyError, match="bold_claim"):
        store.add_idea("motion", hook_type="clickbait")


def test_new_asset_starts_rendering_or_needs_reaction_only(store):
    idea = store.add_idea("remix")
    assert store.add_asset(idea["id"], status="needs_reaction")["status"] == "needs_reaction"
    with pytest.raises(ValueError, match="starts as"):
        store.add_asset(idea["id"], status="approved")


def test_status_cannot_be_written_through_update_asset(store):
    a = _asset_in(store, "ready")
    with pytest.raises(ValueError, match="transition"):
        store.update_asset(a["id"], status="approved")
    with pytest.raises(TypeError):
        store.update_asset(a["id"], approved_at="2026-01-01")
    assert store.update_asset(a["id"], caption="hi")["caption"] == "hi"
    assert store.get_asset(a["id"])["status"] == "ready"


@pytest.mark.parametrize("frm,to", sorted(MOVES))
def test_every_allowed_move_succeeds_for_each_listed_actor(store, frm, to):
    for actor in sorted(MOVES[(frm, to)]):
        a = _asset_in(store, frm)
        assert transition(store, a["id"], to, actor=actor)["status"] == to


@pytest.mark.parametrize("frm,to", sorted(FORBIDDEN.items()))
def test_one_forbidden_move_per_status(store, frm, to):
    assert to not in ALLOWED.get(frm, set())
    a = _asset_in(store, frm)
    for actor in ("owner", "agent", "worker", "system"):
        with pytest.raises(InvalidTransition, match=f"{frm} -> {to}"):
            transition(store, a["id"], to, actor=actor)
    assert store.get_asset(a["id"])["status"] == frm


def test_forbidden_table_covers_every_status():
    statuses = {s for move in MOVES for s in move}
    assert set(FORBIDDEN) == statuses == set(PATH) | {"needs_reaction"}


@pytest.mark.parametrize("frm,to,actor", [
    ("ready", "approved", "agent"),
    ("ready", "approved", "worker"),
    ("publish_check", "approved", "worker"),
    ("approved", "scheduled", "owner"),
    ("rendering", "ready", "owner"),
])
def test_wrong_actor_on_allowed_move_is_rejected(store, frm, to, actor):
    a = _asset_in(store, frm)
    with pytest.raises(InvalidTransition, match=f"not allowed for {actor}"):
        transition(store, a["id"], to, actor=actor)
    assert store.get_asset(a["id"])["status"] == frm


def test_unknown_actor_is_rejected(store):
    a = _asset_in(store, "ready")
    with pytest.raises(ValueError, match="actor"):
        transition(store, a["id"], "approved", actor="intern")


def test_stale_from_status_fails_compare_and_set(store, monkeypatch):
    a = _asset_in(store, "ready")
    assert store._set_asset_status(a["id"], "rendering", "failed") is False
    # transition() read 'ready', then someone archived it before the write
    stale = dict(a)
    transition(store, a["id"], "archived", actor="owner")
    monkeypatch.setattr(store, "get_asset", lambda _id: stale)
    with pytest.raises(InvalidTransition, match="no longer ready"):
        transition(store, a["id"], "approved", actor="owner")
    monkeypatch.undo()
    assert store.get_asset(a["id"])["status"] == "archived"


def test_approved_at_set_on_approve_kept_on_return_cleared_on_unapprove(store):
    a = _asset_in(store, "approved")
    stamp = a["approved_at"]
    assert stamp
    transition(store, a["id"], "scheduled", actor="system")
    assert transition(store, a["id"], "approved", actor="owner")["approved_at"] == stamp
    assert transition(store, a["id"], "ready", actor="owner")["approved_at"] is None


def test_verdict_never_moves_status(store):
    a = _asset_in(store, "approved")
    for v in ("liked", "disliked", "none", "liked"):
        out = set_verdict(store, a["id"], v)
        assert (out["verdict"], out["status"]) == (v, "approved")
    with pytest.raises(ValueError, match="verdict"):
        set_verdict(store, a["id"], "love")
