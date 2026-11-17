"""Dev seed (`ig-campaign dev seed`): fake demo batches, reached through legal moves only."""

import random
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from src import scheduler
from src.config import InstagramMCPSettings
from src.store import CampaignStore
from src.studio import assets as lifecycle
from src.studio import seed as seed_mod
from src.studio.seed import local_today, refusal, seed

TODAY = date(2026, 11, 17)


def _all(store):
    return store.list_assets(limit=1000)


def test_seed_batches_statuses_files_and_legal_moves(tmp_path, monkeypatch):
    moves = []
    real = lifecycle.transition

    def spy(store, asset_id, to, *, actor):
        moves.append((store.get_asset(asset_id)["status"], to, actor))
        return real(store, asset_id, to, actor=actor)

    monkeypatch.setattr(seed_mod, "transition", spy)
    store = CampaignStore(str(tmp_path / "s.db"))
    try:
        summary = seed(store, tmp_path / "media", 3, random.Random(1), TODAY)
        rows = _all(store)
        assert list(summary) == ["2026-11-15", "2026-11-16", "2026-11-17"]
        for day, counts in summary.items():
            n = sum(counts["status"].values())
            assert 9 <= n <= 13  # 8 planned + new version + 0-4 extras
            assert n == sum(counts["verdict"].values())
            assert n == len([r for r in rows if r["batch_date"] == day])
        statuses = Counter(r["status"] for r in rows)
        for s in ("ready", "approved", "archived", "revision_requested", "needs_reaction",
                  "failed", "rendering"):
            assert statuses[s] >= 1, s
        assert {"liked", "disliked", "none"} <= {r["verdict"] for r in rows}
        # every move went through transition() and is in the lifecycle table
        assert moves and all(actor in lifecycle.MOVES[(f, t)] for f, t, actor in moves)
        assert ("revision_requested", "archived", "system") in moves
        # a revision_requested asset has a newer version linked to it
        rev = [r for r in rows if r["status"] == "revision_requested"]
        assert all(any(c["parent_asset_id"] == r["id"] for c in rows) for r in rev)
        assert all(r["qc"]["reason"] for r in rows if r["status"] == "failed")
        assert all(1 <= r["self_score"] <= 10 and r["caption"].startswith("[demo]")
                   for r in rows)
        assert any(r["best_before"] < TODAY.isoformat() for r in rows
                   if r["status"] == "ready" and r["verdict"] == "liked")  # expired bench
        ideas = store.list_ideas(limit=1000)
        assert any(i["strategy"] == "explore" and i["hypothesis"] for i in ideas)
        assert any(i["citations"] for i in ideas)
        assert {"remix", "motion"} == {i["track"] for i in ideas}
        for i in ideas:
            if i["track"] == "remix":
                assert store.get_source(i["source_id"])["rights_basis"] in ("own", "licensed")
        assert all(r["recipe"].get("template") for r in store.list_assets(track="motion",
                                                                         limit=1000))
        feedback = store.list_feedback(limit=1000)
        assert any(f["wants_changes"] for f in feedback)
        assert any(f["reason_codes"] for f in feedback)
        with_files = [r for r in rows if r["file_path"]]
        assert with_files
        for r in with_files:
            for p in (Path(r["file_path"]), Path(r["preview_path"])):
                assert p.is_file() and p.stat().st_size < 50_000
                assert p.parent == tmp_path / "media" / r["batch_date"] / str(r["id"])
    finally:
        store.close()


def test_seed_is_deterministic(tmp_path):
    def run(name):
        store = CampaignStore(":memory:")
        try:
            seed(store, tmp_path / name, 2, random.Random(7), TODAY)
            return [(r["status"], r["verdict"], r["caption"], r["self_score"], r["recipe"])
                    for r in _all(store)]
        finally:
            store.close()

    assert run("a") == run("b")


def test_local_today_uses_the_owner_timezone():
    near_midnight = datetime(2026, 11, 16, 23, 30, tzinfo=timezone.utc)
    assert local_today("Europe/Paris", near_midnight) == date(2026, 11, 17)
    assert local_today("UTC", near_midnight) == date(2026, 11, 16)


def test_refusal(store):
    assert refusal(store, production_live=False) is None
    assert "production" in refusal(store, production_live=True)
    idea = store.add_idea("motion")
    store.add_asset(idea["id"])
    assert "already has assets" in refusal(store, production_live=False)


@pytest.fixture
def cli(tmp_path, monkeypatch):
    prod = tmp_path / "prod.db"
    settings = InstagramMCPSettings(_env_file=None, instagram_access_token="t",
                                    instagram_business_account_id="1",
                                    database_path=str(prod), timezone="Europe/Paris")
    monkeypatch.setattr(scheduler, "get_settings", lambda: settings)

    def run(*argv):
        with pytest.raises(SystemExit) as e:
            scheduler.main(["dev", "seed", "--seed", "3", *argv])
        return e.value.code

    return run, prod, settings


def test_cli_refuses_non_empty_db_without_force(cli, tmp_path, capsys):
    run, _, _ = cli
    db = str(tmp_path / "dev.db")
    assert run("--db", db, "--days", "1") == 0
    assert '"status"' in capsys.readouterr().out  # the summary
    first = len(_assets_in(db))
    assert run("--db", db) == 1
    assert "--force" in capsys.readouterr().err
    assert len(_assets_in(db)) == first
    assert run("--db", db, "--days", "1", "--force") == 0
    assert len(_assets_in(db)) > first


def test_cli_refuses_live_production_db(cli, capsys):
    run, prod, settings = cli
    assert settings.instagram_configured
    assert run() == 1
    assert "production" in capsys.readouterr().err
    assert _assets_in(str(prod)) == []
    assert run("--force", "--days", "1") == 0
    assert _assets_in(str(prod))
    assert (prod.parent / "media").is_dir()


def _assets_in(db):
    s = CampaignStore(db)
    try:
        return _all(s)
    finally:
        s.close()
