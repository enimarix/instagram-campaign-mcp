"""Step 035: quality check after every render (lavfi clips, same skip/CI rule as 031)."""

import pytest

from src.config import InstagramMCPSettings
from src.studio import ffmpeg, qc, render
from tests.test_studio_ffmpeg import needs_ffmpeg
from tests.test_studio_render import _asset, _claim

BLACK = ",drawbox=t=fill:c=black:enable='between(t,1,4)'"  # 3 s of black
TAGS6 = "Tip " + " ".join(f"#t{i}" for i in range(6))


def _settings(**kw):
    return InstagramMCPSettings(_env_file=None, instagram_access_token=None, **kw)


def make(path, *, size="1080x1920", rate=30, duration=6, vf="", audio="tone", still=0):
    """A clip near the output spec: moving test pattern (then `still` s of its last frame),
    a 440 Hz tone at about -14 LUFS."""
    if still:
        vf += f",tpad=stop_mode=clone:stop_duration={still}"
    args = ["-f", "lavfi", "-i", f"testsrc2=size={size}:rate={rate}:duration={duration}{vf}"]
    total = duration + still
    if audio:
        src = (f"sine=frequency=440:duration={total},volume=7.8dB" if audio == "tone"
               else f"anullsrc=r=48000:cl=mono:d={total}")
        args += ["-f", "lavfi", "-i", src, "-c:a", "aac"]
    ffmpeg.run([*args, "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                path], timeout_s=120)
    return path


def check(tmp_path, name="clip.mp4", *, caption="Fun fact #8bit", idea=None, settings=None,
          kind="ffmpeg", **clip):
    make(tmp_path / name, **clip)
    asset = {"caption": caption, "recipe": {"kind": kind}}
    return qc.run_qc(asset, idea, name, tmp_path, settings or _settings())


def failed(result):
    return sorted(c["name"] for c in result["checks"] if not c["ok"])


@needs_ffmpeg
def test_good_clip_passes(tmp_path):
    r = check(tmp_path)
    assert r["passed"] and r["reasons"] == [] and r["warnings"] == []
    assert [c["name"] for c in r["checks"]] == ["spec", "duration", "audio", "loudness",
                                                 "black", "freeze", "caption"]
    assert r["loudness_lufs"] == pytest.approx(-14, abs=1)


@needs_ffmpeg
@pytest.mark.parametrize("clip, settings, names", [
    ({"size": "720x1280"}, {}, ["spec"]),
    ({"rate": 25}, {}, ["spec"]),
    ({"duration": 3}, {}, ["duration"]),
    ({}, {"qc_max_duration_s": 5}, ["duration"]),  # too long, without encoding 90 s
    ({"audio": None}, {}, ["audio", "loudness"]),
    ({"audio": "silence"}, {}, ["loudness"]),
    # 3 s of black is also 3 s frozen
    ({"vf": BLACK}, {}, ["black", "freeze"]),
    ({"duration": 2, "still": 4}, {}, ["freeze"]),
    ({"caption": TAGS6}, {}, ["caption"]),
])
def test_failing_checks(tmp_path, clip, settings, names):
    r = check(tmp_path, settings=_settings(**settings), **clip)
    assert not r["passed"] and failed(r) == names
    assert r["reasons"] == [c["detail"] for c in r["checks"] if not c["ok"]]


@needs_ffmpeg
@pytest.mark.parametrize("kind, clip, names", [
    # Motion title cards hold still on purpose: 5 s passes there (limit 8 s), not elsewhere.
    ("motion", {"duration": 2, "still": 5}, []),
    ("ffmpeg", {"duration": 2, "still": 5}, ["freeze"]),
    ("motion", {"vf": BLACK}, ["black"]),  # black still fails (ffmpeg: test_failing_checks)
])
def test_motion_freeze_limit(tmp_path, kind, clip, names):
    r = check(tmp_path, kind=kind, **clip)
    assert failed(r) == names and r["passed"] == (not names)


@needs_ffmpeg
def test_claims_warn_but_pass(tmp_path):
    r = check(tmp_path, caption="Lose 5 kg in a week, guaranteed!",
              idea={"hook": "Le remède miracle", "script": "Ça guérit tout."})
    assert r["passed"]
    assert r["warnings"] == ["weight-loss promise: 'Lose 5 kg'", "guarantee: 'guaranteed'",
                             "miracle claim: 'miracle'", "medical promise: 'guérit'"]


def test_claim_warnings_patterns():
    assert qc.claim_warnings("This cures colds", "Gagnez 3000 € par mois", None) == [
        "medical promise: 'cures'", "income promise: 'Gagnez 3000 €'"]
    assert qc.claim_warnings("Make $500 a day") == ["income promise: 'Make $500'"]
    assert qc.claim_warnings("Perdez 2 kilos", "garantie 100 %") == [
        "weight-loss promise: 'Perdez 2 kilos'", "guarantee: 'garantie'"]
    # ordinary wording stays quiet
    assert qc.claim_warnings("A secure way to make 5 videos", "Curious? lose the habit") == []


def test_max_hashtags_setting_drives_caption_problem(monkeypatch):
    from src import instagram_client

    assert "at most 5 hashtags" in instagram_client.caption_problem(TAGS6)
    assert instagram_client.caption_problem(TAGS6, 6) is None
    monkeypatch.setattr(instagram_client, "get_settings", lambda: _settings(max_hashtags=10))
    assert instagram_client.caption_problem(TAGS6) is None


@needs_ffmpeg
def test_render_job_moves_failing_asset_to_failed(store, tmp_path):
    a = _asset(store)
    render.enqueue_render(store, a["id"])

    def short_render(asset, media_root, progress):
        return ffmpeg.probe(make(media_root / "video.mp4", duration=3)), {"file_path": "video.mp4"}

    job = render.run_job(store, tmp_path, _claim(store), render_fn=short_render,
                         settings=_settings())
    a = store.get_asset(a["id"])
    assert job["state"] == "done" and a["status"] == "failed"
    assert a["qc"]["passed"] is False and a["qc"]["reasons"] == ["3.0 s (want 5-90 s)"]
