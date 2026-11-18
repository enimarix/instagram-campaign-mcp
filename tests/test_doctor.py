"""`ig-campaign doctor` (step 100): every check mocked, nothing real is probed."""

import pytest

from src import scheduler
from src.agent.runner import AgentError
from src.studio import doctor, downloader_service, ffmpeg, motion


def _not_found(*_a, **_k):
    raise ffmpeg.FFmpegNotFound("ffmpeg not found on PATH")


@pytest.fixture
def mocked(monkeypatch, tmp_path, settings):
    """Everything present; tests break one thing at a time."""
    web = tmp_path / "dist"
    web.mkdir()
    (web / "index.html").write_text("<html></html>")
    vendor = tmp_path / "vendor"
    (vendor / ".next").mkdir(parents=True)
    (vendor / "package.json").write_text("{}")
    (vendor / ".next" / "BUILD_ID").write_text("x")
    env = tmp_path / ".env"
    env.write_text("")
    monkeypatch.setattr(downloader_service, "VENDOR_DIR", vendor)
    monkeypatch.setattr(ffmpeg, "find_ffmpeg", lambda: "/bin/ffmpeg")
    monkeypatch.setattr(ffmpeg, "find_ffprobe", lambda: "/bin/ffprobe")
    monkeypatch.setattr(motion, "find_node", lambda: "/bin/node")
    monkeypatch.setattr(doctor, "preflight", lambda s: "/bin/claude")
    return settings.model_copy(update={"web_dist": str(web)}), env, vendor


def _by_name(results):
    return {c["name"]: c for c in results}


def test_all_present(mocked):
    settings, env, _ = mocked
    results = doctor.checks(settings, env_file=str(env))
    assert all(c["ok"] and c["fix"] == "" for c in results), results
    assert len(results) == 8


def test_failures_say_what_to_do(mocked, monkeypatch, tmp_path):
    settings, _, vendor = mocked
    (vendor / ".next" / "BUILD_ID").unlink()
    monkeypatch.setattr(ffmpeg, "find_ffprobe", _not_found)

    def no_claude(_s):
        raise AgentError("Claude Code CLI is not signed in")

    monkeypatch.setattr(doctor, "preflight", no_claude)
    settings = settings.model_copy(update={"web_dist": str(tmp_path / "missing"),
                                           "instagram_access_token": None})
    got = _by_name(doctor.checks(settings, env_file=str(tmp_path / "none.env")))
    failed = {n for n, c in got.items() if not c["ok"]}
    assert failed == {".env", "Instagram account", "ffprobe", "website build",
                      "Reel downloader", "Claude Code CLI"}
    assert got["ffmpeg"]["ok"]
    assert "npm --prefix web run build" in got["website build"]["fix"]
    assert "downloader setup" in got["Reel downloader"]["fix"]
    assert got["Reel downloader"]["detail"] == "built: no"
    assert "not signed in" in got["Claude Code CLI"]["detail"]
    assert all(got[n]["fix"] for n in failed)


def test_env_example_placeholders_are_not_a_token(mocked):
    settings, env, _ = mocked
    settings = settings.model_copy(update={"instagram_access_token":
                                           "your_long_lived_access_token"})
    got = _by_name(doctor.checks(settings, env_file=str(env)))
    assert not got["Instagram account"]["ok"]


def test_cli_exit_code(monkeypatch, capsys):
    rows = [{"name": "ffmpeg", "ok": True, "detail": "/bin/ffmpeg", "fix": ""},
            {"name": "website build", "ok": False, "detail": "web/dist", "fix": "npm ..."}]
    monkeypatch.setattr(doctor, "checks", lambda s: rows)
    with pytest.raises(SystemExit) as e:
        scheduler.main(["doctor"])
    assert e.value.code == 1
    out = capsys.readouterr().out
    assert "✔ ffmpeg" in out and "✖ website build" in out and "-> npm ..." in out
    monkeypatch.setattr(doctor, "checks", lambda s: rows[:1])
    with pytest.raises(SystemExit) as e:
        scheduler.main(["doctor"])
    assert e.value.code == 0 and "All set." in capsys.readouterr().out
