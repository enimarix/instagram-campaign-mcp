"""Step 175: `up` rebuilds web/dist when a source is newer (src/studio/website.py). Fake mtimes
and a fake npm: never a real build."""

import os
import subprocess
from pathlib import Path

import pytest

from src import scheduler
from src.studio import alerts, website


@pytest.fixture
def web(tmp_path, settings, monkeypatch):
    """A web/ folder built at t=1000: sources at t=900, an old dist, node_modules."""
    root = tmp_path / "web"
    for rel in ("src/pages/Create.tsx", "index.html", "package.json", "dist/index.html"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("old", encoding="utf-8")
    (root / "node_modules").mkdir()
    for p in root.rglob("*"):
        os.utime(p, (900, 900))
    os.utime(root / "dist" / "index.html", (1000, 1000))
    monkeypatch.setattr(website.shutil, "which", lambda name: "npm")
    return root, settings.model_copy(update={"web_dist": str(root / "dist"),
                                             "database_path": str(tmp_path / "studio.db")})


def fake_npm(monkeypatch, code=0, out="vite v8 building"):
    """guard.run stand-in: writes the build into --outDir when it 'works'."""
    calls = []

    def run(cmd, **kw):
        calls.append((cmd, kw))
        outdir = Path(cmd[cmd.index("--outDir") + 1])
        if not code:
            outdir.mkdir(parents=True, exist_ok=True)
            (outdir / "index.html").write_text("new", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, code, out, "error TS2304: Cannot find name"
                                           if code else "")

    monkeypatch.setattr(website.guard, "run", run)
    return calls


def test_stale_when_a_source_is_newer_than_the_build(web):
    root, settings = web
    assert not website.stale(settings)
    os.utime(root / "src" / "pages" / "Create.tsx", (1100, 1100))  # a merge touched it
    assert website.stale(settings)
    os.utime(root / "src" / "pages" / "Create.tsx", (900, 900))
    os.utime(root / "package.json", (1100, 1100))
    assert website.stale(settings)
    (root / "dist" / "index.html").unlink()  # never built
    os.utime(root / "package.json", (900, 900))
    assert website.stale(settings)


def test_no_web_folder_means_nothing_to_build(tmp_path, settings):
    assert not website.stale(settings.model_copy(update={"web_dist": str(tmp_path / "dist")}))


def test_a_stale_site_is_rebuilt_at_low_priority_and_swapped_in(web, monkeypatch):
    root, settings = web
    calls = fake_npm(monkeypatch)
    os.utime(root / "index.html", (1100, 1100))
    scheduler._rebuild_website(settings)
    assert (root / "dist" / "index.html").read_text() == "new"
    cmd, kw = calls[0]
    assert cmd[:3] == ["npm", "run", "build"] and kw["cwd"] == root
    assert not (root / "dist.new").exists() and not (root / "dist.old").exists()
    store = scheduler.CampaignStore(settings.database_path)
    try:
        assert store.get_state(website.STATE_KEY)["ok"] is True
        assert alerts._website(store) == []
    finally:
        store.close()
    calls.clear()
    scheduler._rebuild_website(settings)  # fresh now: no build
    assert calls == []


def test_a_failed_build_keeps_the_old_site_and_raises_an_alert(web, monkeypatch, capsys):
    root, settings = web
    fake_npm(monkeypatch, code=2)
    os.utime(root / "src" / "pages" / "Create.tsx", (1100, 1100))
    scheduler._rebuild_website(settings)
    assert (root / "dist" / "index.html").read_text() == "old"
    assert not (root / "dist.new").exists()
    assert "the site could not be rebuilt" in capsys.readouterr().err
    store = scheduler.CampaignStore(settings.database_path)
    try:
        [a] = alerts._website(store)
        assert a["title"] == "The site could not be rebuilt"
        assert "exited 2" in a["detail"] and "TS2304" in a["detail"]
        # someone built it by hand: the next start finds it fresh and clears the alert
        os.utime(root / "dist" / "index.html", (1200, 1200))
        website.rebuild_if_stale(settings, store)
        assert alerts._website(store) == []
    finally:
        store.close()


def test_node_missing_is_the_same_alert(web, monkeypatch):
    root, settings = web
    monkeypatch.setattr(website.shutil, "which", lambda name: None)
    monkeypatch.setattr(website.guard, "run", lambda *a, **k: pytest.fail("no npm to run"))
    result = website.build(settings)
    assert result["ok"] is False and "npm not found" in result["error"]
    assert (root / "dist" / "index.html").read_text() == "old"


def test_cli_web_build_builds_whatever_its_age(web, monkeypatch, capsys):
    root, settings = web
    calls = fake_npm(monkeypatch)
    monkeypatch.setattr(scheduler, "get_settings", lambda: settings)
    monkeypatch.setattr(scheduler, "configure_logging", lambda *a: None)  # keeps capsys' file
    with pytest.raises(SystemExit) as e:
        scheduler.main(["web", "build"])
    assert e.value.code == 0 and len(calls) == 1
    assert (root / "dist" / "index.html").read_text() == "new"
    assert '"ok": true' in capsys.readouterr().out
