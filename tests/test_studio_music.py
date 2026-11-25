"""Step 178: Instagram trending music, the voice on the beat, the track attached at publish.
No ffmpeg here: band energies are synthetic, `measure` is replaced where a file is fetched."""

import json
from pathlib import Path

import pytest
import respx

from src.store import utcnow
from src.studio import music
from src.studio.publish import queue_asset
from src.studio.render import validate_recipe

from .conftest import API
from .test_client import _body
from .test_studio_publish import LATER, _asset, cfg  # noqa: F401 - fixture

CDN = "https://scontent-cdg4-3.xx.fbcdn.net/o1/track.m4a?sig=abc"


def _song(bpm=120.0, seconds=30.0, drop_s=17.0):
    """Five band energies: a kick on every beat (accented on the bar's first, from 2 beats
    in), hats on every beat, the kick 4x louder from `drop_s`."""
    n = int(seconds * music.FPS)
    bands = [[1e-4] * n for _ in music.BANDS]
    period = 60 / bpm
    for k in range(int(seconds / period)):
        t = 1.0 + k * period
        f = round(t * music.FPS)
        if f >= n:
            break
        loud = 4.0 if t >= drop_s else 1.0
        bands[0][f] = loud * (1.0 if k % 4 == 0 else 0.3)
        bands[4][f] = 0.2
    return bands


def test_beat_map_finds_tempo_downbeats_and_drop():
    m = music.beat_map(_song())
    assert abs(m["bpm"] - 120) < 4
    assert len(m["beats"]) > 50
    gaps = [b - a for a, b in zip(m["beats"], m["beats"][1:])]
    assert all(abs(g - 0.5) < 0.06 for g in gaps)
    # bars start on the accented beats: 1.0 s + n * 2 s
    assert all(abs((d - 1.0) / 2 - round((d - 1.0) / 2)) < 0.05 for d in m["downbeats"])
    assert m["drop_s"] is not None and abs(m["drop_s"] - 17.0) < 0.1  # the loud bars start


def test_silence_has_no_beat():
    m = music.beat_map([[0.0] * 2000 for _ in music.BANDS])
    assert m == {"bpm": None, "beats": [], "downbeats": [], "drop_s": None}


def test_beat_this_grid_is_used_and_the_drop_still_found():
    given = {"beats": [1.0 + k * 0.5 for k in range(56)],
             "downbeats": [1.0 + k * 2.0 for k in range(14)]}
    m = music.beat_map(_song(), given)
    assert abs(m["bpm"] - 120) < 3
    assert m["beats"][:3] == [round(round(t * music.FPS) / music.FPS, 3) for t in (1.0, 1.5, 2.0)]
    assert len(m["downbeats"]) == 14 and abs(m["drop_s"] - 17.0) < 0.1


def test_beat_this_missing_or_failing_falls_back(monkeypatch, tmp_path):
    monkeypatch.setattr(music, "beats_python", lambda: None)
    assert music.beat_this(tmp_path / "t.m4a") is None
    monkeypatch.setattr(music, "beats_python", lambda: "py")
    monkeypatch.setattr(music.ffmpeg, "run", lambda *a, **k: None)
    calls = []

    class Done:
        returncode, stderr = 0, ""
        stdout = 'loading\n{"beats": [0.5, 1.0], "downbeats": [0.5]}\n'

    def run(cmd, **kw):
        calls.append((cmd, kw["env"]))
        return Done

    monkeypatch.setattr(music.guard, "run", run)
    assert music.beat_this(tmp_path / "t.m4a") == {"beats": [0.5, 1.0], "downbeats": [0.5]}
    cmd, env = calls[0]
    assert cmd[:3] == ["py", "-I", str(music.RUNNER)] and cmd[3].endswith("track.wav")
    assert env["CUDA_VISIBLE_DEVICES"] == "" and env["OMP_NUM_THREADS"].isdigit()  # CPU only
    Done.returncode, Done.stderr = 1, "boom"
    assert music.beat_this(tmp_path / "t.m4a") is None


GRID = {"bpm": 120.0, "beats": [i * 0.5 for i in range(80)],
        "downbeats": [i * 2.0 for i in range(20)], "drop_s": 8.0}


def test_lines_move_onto_downbeats_beats_and_the_drop():
    lines = [{"text": "hook", "start_s": 0.1, "end_s": 1.5},
             {"text": "a", "start_s": 1.7, "end_s": 2.9},  # earliest 1.65: downbeat 2.0
             {"text": "b", "start_s": 3.0, "end_s": 3.4},  # earliest 3.35: no downbeat by 3.95
             {"text": "c", "start_s": 3.6, "end_s": 5.0},  # earliest 4.05: beat 4.5
             {"text": "d", "start_s": 5.2, "end_s": 6.0}]  # earliest 6.05: the drop (8.0)
    out = music.on_beats(lines, GRID)
    starts = [x["start_s"] for x in out]
    assert starts[0] == 0.1  # the hook stays
    assert starts[1] == 2.0  # downbeat
    assert starts[2] == 3.5  # next beat
    assert starts[3] == 4.5  # the downbeat 4.0 is before it, 6.0 too far: next beat
    assert starts[4] == 8.0  # the drop is within a bar
    assert [round(x["end_s"] - x["start_s"], 3) for x in out] == [1.4, 1.2, 0.4, 1.4, 0.8]
    for a, b in zip(out, out[1:]):
        assert b["start_s"] >= a["end_s"] + music.LINE_GAP_S - 1e-9
    assert out[1]["text"] == "a"


def test_a_line_takes_the_drop_when_it_is_within_a_bar():
    lines = [{"text": "hook", "start_s": 0.0, "end_s": 6.5},
             {"text": "payoff", "start_s": 6.8, "end_s": 8.0}]
    # earliest 6.65: downbeat 8.0 is 1.35 s away (past the wait) but it is the drop
    assert music.on_beats(lines, GRID)[1]["start_s"] == 8.0


def _fetched(root: Path, audio_id="1508891487055373", lufs=-10.0, duration=60.0):
    folder = music.music_dir(root)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{audio_id}.m4a").write_bytes(b"aac")
    meta = {"audio_id": audio_id, "title": "Belleza", "artist": "PiNKSHGRFNGR",
            "track": f"music/{audio_id}.m4a", "lufs": lufs, "duration_s": duration, **GRID}
    (folder / f"{audio_id}.json").write_text(json.dumps(meta), "utf-8")
    return audio_id


def _voiced(root: Path, lines):
    (root / "voice").mkdir(exist_ok=True)
    (root / "voice" / "v.wav").write_bytes(b"wav")
    return {"music": "music-dusk", "voice": {"audioSrc": "voice/v.wav", "lines": lines}}


def test_apply_moves_the_voice_and_sets_instagram_volumes(tmp_path, monkeypatch):
    moves = []

    def retime(src, old, new, dest):  # ffmpeg-free stand-in
        moves.append((src.name, [x["start_s"] for x in old], [x["start_s"] for x in new]))
        (dest / "v.beat.wav").write_bytes(b"wav")
        return dest / "v.beat.wav"

    monkeypatch.setattr(music, "retime_voice", retime)
    aid = _fetched(tmp_path)
    props = _voiced(tmp_path, [{"text": "h", "start_s": 0.0, "end_s": 1.0},
                               {"text": "x", "start_s": 1.2, "end_s": 2.0}])
    out, ig = music.apply(props, tmp_path, aid)
    assert out["music"] == "none"
    assert out["voice"]["lines"][1]["start_s"] == 1.5
    assert out["voice"]["audioSrc"] == "voice/v.beat.wav"
    assert moves == [("v.wav", [0.0, 1.2], [0.0, 1.5])]
    # the voice ends at -14 LUFS, the track 15 LU under it: -10 -> -29 = 10^(-19/20) = 11 %
    assert ig == {"audio_id": aid, "title": "Belleza", "artist": "PiNKSHGRFNGR",
                  "track": f"music/{aid}.m4a", "audio_volume": 11, "video_volume": 100}
    validate_recipe({"kind": "motion", "template": "Cutaway", "props": out, "ig_audio": ig},
                    tmp_path)


def test_apply_refuses_a_missing_or_short_track_and_a_silent_video(tmp_path):
    with pytest.raises(ValueError, match="fetch_music first"):
        music.apply({}, tmp_path, "1234567890")
    aid = _fetched(tmp_path, duration=6.0)
    props = _voiced(tmp_path, [{"text": "h", "start_s": 0.0, "end_s": 3.0}])
    with pytest.raises(ValueError, match="shorter than the video"):
        music.apply(props, tmp_path, aid)
    with pytest.raises(ValueError, match="not an Instagram audio id"):
        music.apply({}, tmp_path, "../x")
    no_voice = {"voice": {"lines": [{"text": "h", "start_s": 0.0, "end_s": 1.0}]}}
    with pytest.raises(ValueError, match="needs a voiced video"):
        music.apply(no_voice, tmp_path, aid)
    meta = music.music_dir(tmp_path) / f"{aid}.json"  # a chart hit, as an original sound
    meta.write_text(json.dumps({**json.loads(meta.read_text("utf-8")),
                                "type": "original_sound"}), "utf-8")
    with pytest.raises(ValueError, match="original sound"):
        music.apply(props, tmp_path, aid)


def test_a_quiet_break_keeps_the_beat_going():
    bands = _song(seconds=40.0, drop_s=99.0)
    for b in bands:  # silence from 14 s to 20 s
        b[round(14 * music.FPS):round(20 * music.FPS)] = [0.0] * (
            round(20 * music.FPS) - round(14 * music.FPS))
    m = music.beat_map(bands)
    assert m["beats"][0] < 2.0 and m["beats"][-1] > 38.0  # one chain, start to end


def test_preview_mix_follows_instagram_volumes():
    args = music.preview_args({"audio_volume": 20, "video_volume": 100})
    graph = args[args.index("-filter_complex") + 1]
    assert "[1:a]volume=0.200" in graph and "[0:a]volume=1.000" in graph and "amix" in graph


@respx.mock
async def test_trending_and_fetch(client, tmp_path, monkeypatch):
    trend = respx.get(f"{API}/ig_audio").respond(json={"audio": [
        {"audio_id": "1508891487055373", "title": "Belleza", "display_artist": "PiNKSHGRFNGR",
         "audio_type": "music", "duration_in_ms": 179066, "download_url": CDN}], "paging": {}})
    tracks = await music.trending(client, "gym")
    assert tracks == [{"audio_id": "1508891487055373", "title": "Belleza",
                       "artist": "PiNKSHGRFNGR", "type": "music", "duration_s": 179}]
    q = trend.calls.last.request.url.params
    assert q["audio_type"] == "music" and q["user_id"] == "1789" and q["search_query"] == "gym"

    respx.get(f"{API}/1508891487055373").respond(json={
        "audio_id": "1508891487055373", "title": "Belleza", "audio_type": "music",
        "duration_in_ms": 179066, "download_url": CDN})
    cdn = respx.get(CDN).respond(content=b"aac-bytes")
    monkeypatch.setattr(music, "measure", lambda p: {"duration_s": 179.0, "lufs": -12.0, **GRID})
    meta = await music.fetch(client, tmp_path, "1508891487055373")
    assert meta["bpm"] == 120.0 and meta["track"] == "music/1508891487055373.m4a"
    assert (tmp_path / "music" / "1508891487055373.m4a").read_bytes() == b"aac-bytes"
    assert "authorization" not in cdn.calls.last.request.headers  # never our token on a CDN
    await music.fetch(client, tmp_path, "1508891487055373")  # cached: no second download
    assert cdn.call_count == 1


@respx.mock
async def test_fetch_refuses_a_link_off_instagram_and_a_redirect(client, tmp_path):
    respx.get(f"{API}/1234567890").respond(json={"download_url": "https://evil.example/x"})
    with pytest.raises(ValueError, match="no Instagram download link"):
        await music.fetch(client, tmp_path, "1234567890")
    respx.get(f"{API}/1234567891").respond(json={"download_url": CDN})
    respx.get(CDN).respond(302, headers={"Location": "https://evil.example/x"})
    evil = respx.get("https://evil.example/x").respond(content=b"x")
    with pytest.raises(ValueError, match="download failed"):
        await music.fetch(client, tmp_path, "1234567891")
    assert not evil.called and not (tmp_path / "music" / "1234567891.json").exists()


def test_publish_attaches_the_track_instead_of_audio_name(store, cfg):  # noqa: F811
    ig = {"audio_id": "1508891487055373", "track": "music/x.m4a", "audio_volume": 12,
          "video_volume": 100, "title": "Belleza"}
    a = _asset(store, cfg, audio_name="Original", recipe={"kind": "motion", "ig_audio": ig})
    post = queue_asset(store, cfg, a["id"], utcnow() + LATER)
    assert "audio_name" not in post["payload"]
    assert post["payload"]["audio_configuration"] == {
        "audio_id": "1508891487055373", "audio_volume": 12, "video_volume": 100}


@respx.mock
async def test_reel_container_carries_audio_configuration(client):
    create = respx.post(f"{API}/1789/media").respond(json={"id": "C1"})
    respx.get(f"{API}/C1").respond(json={"status_code": "FINISHED"})
    respx.post(f"{API}/1789/media_publish").respond(json={"id": "M1"})
    respx.get(f"{API}/M1").respond(json={"id": "M1"})
    conf = {"audio_id": "1508891487055373", "audio_volume": 12, "video_volume": 100}
    await client.publish_reel(video_url="https://cdn.example/v.mp4", audio_name="Tune",
                              audio_configuration=conf)
    body = _body(create.calls.last)
    assert body["audio_configuration"] == conf and "audio_name" not in body


def test_queue_motion_render_cuts_on_the_track_and_stores_ig_audio(store, tmp_path, monkeypatch):
    from src.studio import motion

    from .test_studio_motion import VALID, _settings

    monkeypatch.setattr(motion, "validate_props", lambda t, p: {**VALID, "props": p})
    monkeypatch.setattr(motion, "list_templates", lambda: [{"id": "Hello", "style": "pixel"}])
    lines = [{"text": "h", "start_s": 0.0, "end_s": 1.0}, {"text": "x", "start_s": 1.2, "end_s": 2.0}]
    voiced = _voiced(tmp_path, lines)
    monkeypatch.setattr(motion, "build_props", lambda t, p, s, v=None, cast=None, *a: {**p, **voiced})
    monkeypatch.setattr(music, "retime_voice", lambda src, old, new, dest: src)
    aid = _fetched(tmp_path)
    s = _settings(tmp_path)
    idea = store.add_idea("motion")
    out = motion.queue_motion_render(store, s, template="Hello", props={"title": "Hi"},
                                     idea_id=idea["id"], music_audio_id=aid)
    recipe = out["asset"]["recipe"]
    assert recipe["ig_audio"]["audio_id"] == aid and recipe["props"]["music"] == "none"
    assert recipe["props"]["voice"]["lines"][1]["start_s"] == 1.5  # on the beat
    for blender in ("CinematicSkit", "SitcomSkit"):
        with pytest.raises(ValueError, match="cannot take an Instagram track"):
            motion.queue_motion_render(store, s, template=blender, props={},
                                       idea_id=idea["id"], music_audio_id=aid)
