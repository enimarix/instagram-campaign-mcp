"""Reaction reel (071). The "reel" is lavfi video with a tone that is on for 3 s and off
for 2 s, so its silences are [3, 5], [8, 10], [13, 15], [18, 20]; it is 21 s long."""

import shutil
import threading

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.store import CampaignStore
from src.studio import ffmpeg, media, reactions
from src.studio.reactions import ReactionError, next_reaction_piece, snap
from tests.conftest import LOCAL
from tests.test_api_media import _settings
from tests.test_studio_ffmpeg import H264, needs_ffmpeg

REEL_S = 21
FRAME = 1 / 30


@pytest.fixture(scope="module")
def reel_file(tmp_path_factory):
    path = tmp_path_factory.mktemp("reel") / "reel.mp4"
    ffmpeg.run(["-f", "lavfi", "-i", f"testsrc2=size=160x284:rate=30:duration={REEL_S}",
                "-f", "lavfi", "-i",
                f"aevalsrc='if(lt(mod(t,5),3),sin(2*PI*440*t),0)':d={REEL_S}",
                *H264, "-c:a", "aac", "-shortest", path], timeout_s=120)
    return path


@pytest.fixture
def root(tmp_path):
    return tmp_path / "media"


@pytest.fixture
def reel(reel_file, root, store, tmp_path):
    copy = tmp_path / "upload.mp4"
    shutil.copy(reel_file, copy)
    return reactions.add_reel(store, _settings(root), copy)


def piece(store, root, duration_s=2.0, **kw):
    return next_reaction_piece(store, _settings(root), duration_s, preset="ultrafast", **kw)


def test_snap_moves_forward_only_into_a_near_silence():
    silences = [[3.0, 5.0], [8.0, 10.0]]
    assert snap(2.0, silences) == 3.0  # 1 s ahead
    assert snap(4.0, silences) == 4.0  # already quiet
    assert snap(5.5, silences) == 5.5  # next silence 2.5 s away
    assert snap(9.5, [[8.0, 9.0]]) == 9.5  # never back into used footage
    assert snap(1.0, []) == 1.0


@needs_ffmpeg
def test_add_reel_moves_file_finds_silences_and_activates(reel, root, store):
    assert reel["active"] and reel["cursor_s"] == 0 and reel["pieces_used"] == 0
    assert reel["path"] == f"reactions/{reel['id']}/reel.mp4"
    assert media.resolve(root, reel["path"]).is_file()
    starts = [round(a) for a, _ in store.get_reaction_reel(reel["id"])["silences"]]
    assert starts == [3, 8, 13, 18]


@needs_ffmpeg
def test_pieces_are_consecutive_snap_and_wrap(reel, root, store):
    got, cursor = [], 0.0
    for _ in range(8):
        p = piece(store, root)
        if p["start_s"] != 0 or not got:  # not the wrap
            assert cursor <= p["start_s"] <= cursor + reactions.SNAP_S
        got.append(p)
        cursor = store.get_reaction_reel(reel["id"])["cursor_s"]
        assert cursor == p["end_s"] == p["start_s"] + 2
    starts = [round(p["start_s"], 1) for p in got]
    # 0-2, then 2 snaps to the silence at 3, 5 is at a silence's end, 7 snaps to 8, ...
    assert starts == [0, 3, 5, 8, 10, 13, 15, 18]
    assert all(a["end_s"] <= b["start_s"] for a, b in zip(got, got[1:]))
    wrap = piece(store, root)  # 20 + 2 passes the end (21): start over
    assert wrap["start_s"] == 0 and wrap["end_s"] == 2
    status = reactions.list_reels(store)[0]
    assert status["cursor_s"] == 2 and status["pieces_used"] == 1
    assert len({p["piece_id"] for p in [*got, wrap]}) == 9


@needs_ffmpeg
def test_piece_file_is_exact_length(reel, root, store):
    p = piece(store, root, 3.3, asset_id=None)
    path = media.resolve(root, p["path"])
    assert path == media.resolve(root, f"reactions/{reel['id']}/pieces/{p['piece_id']}.mp4")
    info = ffmpeg.probe(path)
    assert abs(info.duration - 3.3) <= FRAME and info.has_audio and info.video_codec


@needs_ffmpeg
def test_two_threads_get_different_pieces(reel_file, tmp_path):
    root = tmp_path / "media"
    store = CampaignStore(str(tmp_path / "db.sqlite"))  # real per-thread connections
    try:
        copy = tmp_path / "upload.mp4"
        shutil.copy(reel_file, copy)
        reactions.add_reel(store, _settings(root), copy)
        out, barrier = [], threading.Barrier(2)

        def work():
            barrier.wait()
            out.append(piece(store, root, 4.0))

        threads = [threading.Thread(target=work) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        a, b = sorted(out, key=lambda p: p["start_s"])
        assert a["piece_id"] != b["piece_id"] and a["end_s"] <= b["start_s"]
        assert store.active_reaction_reel()["pieces_used"] == 2
    finally:
        store.close()


@needs_ffmpeg
def test_errors_no_reel_too_short_no_sound(reel_file, root, store, tmp_path):
    with pytest.raises(ReactionError, match="no active"):
        piece(store, root)
    silent = tmp_path / "silent.mp4"
    ffmpeg.run(["-f", "lavfi", "-i", "testsrc2=size=160x284:rate=30:duration=1", *H264,
                silent], timeout_s=60)
    with pytest.raises(ReactionError, match="video and sound"):
        reactions.add_reel(store, _settings(root), silent)
    copy = tmp_path / "upload.mp4"
    shutil.copy(reel_file, copy)
    reactions.add_reel(store, _settings(root), copy)
    with pytest.raises(ReactionError, match="shorter"):
        piece(store, root, REEL_S + 5)


@needs_ffmpeg
def test_activate_and_reset(reel, reel_file, root, store, tmp_path):
    piece(store, root)
    copy = tmp_path / "second.mov"
    shutil.copy(reel_file, copy)
    second = reactions.add_reel(store, _settings(root), copy)
    assert [r["active"] for r in reactions.list_reels(store)] == [True, False]  # newest first
    assert reactions.activate(store, reel["id"])["active"]
    assert not store.get_reaction_reel(second["id"])["active"]
    out = reactions.reset_cursor(store, reel["id"])
    assert out["cursor_s"] == 0 and out["pieces_used"] == 0 and out["used_pct"] == 0


# --- Routes -----------------------------------------------------------------

@pytest.fixture
def tc(root, store):
    with TestClient(create_app(_settings(root, reaction_upload_max_mb=3), store=store),
                    base_url=LOCAL) as c:
        yield c


def chunks(data, size=64 * 1024):
    for i in range(0, len(data), size):
        yield data[i:i + size]


def inbox_files(root):
    folder = root / "reactions" / "inbox"
    return sorted(folder.iterdir()) if folder.exists() else []


@needs_ffmpeg
def test_upload_streams_to_disk_then_activate_and_reset(tc, reel_file, root):
    data = reel_file.read_bytes()
    assert len(data) < 3_000_000  # under the test cap
    r = tc.post("/api/reactions/upload?name=My%20Reel.MP4", content=chunks(data))
    assert r.status_code == 200, r.text
    reel = r.json()
    assert reel["active"] and abs(reel["duration_s"] - REEL_S) < 0.5
    assert media.resolve(root, reel["path"]).read_bytes() == data
    assert inbox_files(root) == []
    assert [x["id"] for x in tc.get("/api/reactions").json()] == [reel["id"]]
    assert tc.post(f"/api/reactions/{reel['id']}/activate").json()["active"]
    assert tc.post(f"/api/reactions/{reel['id']}/reset").json()["cursor_s"] == 0
    assert tc.post("/api/reactions/999/activate").status_code == 404


def test_upload_size_cap_and_bad_files(tc, root):
    big = b"\0" * 3_500_000
    r = tc.post("/api/reactions/upload?name=a.mp4", content=big)  # Content-Length known
    assert r.status_code == 413 and r.json()["error"] == "too_large"
    r = tc.post("/api/reactions/upload?name=a.mp4", content=chunks(big))  # chunked: counted
    assert r.status_code == 413
    assert inbox_files(root) == []
    r = tc.post("/api/reactions/upload?name=notes.txt", content=b"hello")
    assert r.status_code == 422
    assert tc.get("/api/reactions").json() == []


@needs_ffmpeg
def test_upload_of_a_non_video_is_refused_and_removed(tc, root):
    r = tc.post("/api/reactions/upload?name=a.mp4", content=b"not a video")
    assert r.status_code == 422 and "not a video" in r.json()["message"]
    assert inbox_files(root) == []
