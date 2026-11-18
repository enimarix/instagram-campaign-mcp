"""Reaction remixes (069): src/studio/remix.py, its MCP doors and the @creator caption rule."""

import json
from pathlib import Path

import pytest
from mcp.server.mcpserver.exceptions import ToolError

import src.instagram_mcp_server as srv
from src.studio import ffmpeg, production, recipe, remix
from src.studio.assets import transition
from src.studio.recipe import Recipe, Trim, recipe_timeline, render
from src.studio.render import FfmpegRecipe
from src.studio.tts import LineTiming, Synthesis
from tests.test_api_media import _settings
from tests.test_studio_ffmpeg import needs_ffmpeg
from tests.test_studio_recipe import assert_spec, make_clip

SCRIPT = "Watch his face at second three.\nThat is why this one works."
LINES = [{"start_s": 1.0, "end_s": 3.0, "text": "before the trim"},
         {"start_s": 9.0, "end_s": 11.0, "text": "across the start"},
         {"start_s": 12.0, "end_s": 14.0, "text": "inside"},
         {"start_s": 39.0, "end_s": 42.0, "text": "across the end"}]


def _source(store, **kw):
    fields = dict(role="clip", author="creator", rights_basis="commentary",
                  rights_note="Public Reel by @creator, commentary use only",
                  audio_rights="not_covered", local_path="sources/1/clip.mp4",
                  stats={"duration_s": 60.0, "transcript": {"provider": "x", "lines": LINES}})
    return store.add_source("reel_downloader", **{**fields, **kw})


def _ops(r):
    return [op.op for op in r.ops]


def build(source, **kw):
    return remix.build_remix(source, **{"hook": "Wait for it", "script": SCRIPT, **kw})


def test_not_covered_mutes_adds_music_and_transcript_captions(store):
    r = build(_source(store), trim=(10, 40), music=True)
    assert _ops(r) == ["trim", "mute_original", "reaction_collage", "voice_over", "music",
                       "hook_text", "captions", "credit", "logo"]
    captions = next(op for op in r.ops if op.op == "captions")
    # Only the trimmed span, in the trimmed clip's seconds.
    assert [(c.start_s, c.end_s, c.text) for c in captions.lines] == [
        (0.0, 1.0, "across the start"), (2.0, 4.0, "inside"), (29.0, 30.0, "across the end")]
    credit = next(op for op in r.ops if op.op == "credit")
    assert credit.text == "@creator"
    logo, collage = r.ops[-1], r.ops[2]
    assert logo.position != collage.pip_corner


def test_covered_keeps_the_clip_audio_ducked(store):
    r = build(_source(store, audio_rights="covered"), music=True)
    assert "mute_original" not in _ops(r) and "music" not in _ops(r)
    collage = next(op for op in r.ops if op.op == "reaction_collage")
    assert collage.clip_gain_db < 0 and "voice_over" in _ops(r)


def test_trim_within_bounds_and_capped(store):
    s = _source(store)
    assert r_trim(build(s)) == (0, 45)  # whole clip, capped at max_clip_s
    assert r_trim(build(s, trim=(5, 60), max_clip_s=20)) == (5, 25)
    assert r_trim(build(s, trim=(50, None))) == (50, 60)
    for bad in ((-1, 10), (10, 5), (10, 61), (60, None)):
        with pytest.raises(ValueError, match="trim"):
            build(s, trim=bad)


def r_trim(r):
    op = r.ops[0]
    assert isinstance(op, Trim)
    return op.start_s, op.end_s


def test_commentary_needs_a_script(store):
    for script in ("", "   ", None):
        with pytest.raises(ValueError, match="voice-over script"):
            build(_source(store), script=script)
    own = build(_source(store, rights_basis="own"), script=None)
    assert "voice_over" not in _ops(own) and "reaction_collage" in _ops(own)


def test_credit_is_mandatory(store):
    for basis in ("commentary", "permission", "cc"):
        with pytest.raises(ValueError, match="author"):
            build(_source(store, rights_basis=basis, author=None))
    with pytest.raises(ValueError, match="credit must name"):
        build(_source(store), credit="Clip: someone else")
    r = build(_source(store), credit="Reacting to @Creator")
    assert next(op for op in r.ops if op.op == "credit").text == "Reacting to @Creator"


def test_unknown_rights_are_never_rendered(store):
    with pytest.raises(ValueError, match="rights_basis"):
        build(_source(store, rights_basis="unknown"))


def test_recipe_validates_and_the_timeline_describes_it(store):
    r = build(_source(store), trim=(10, 30))
    again = Recipe.model_validate(r.model_dump(mode="json"))
    assert again == r
    events = " | ".join(e["e"] for e in recipe_timeline(again, 20.0))
    for part in ("hook text: 'Wait for it'", "caption: 'inside'", "reaction pip",
                 "credit: '@creator'", "voice-over", "original sound muted"):
        assert part in events, part


# --- render_remix -------------------------------------------------------------------------

class FakeTTS:
    def __init__(self, audio, duration_s=5.0):
        self.audio, self.duration_s, self.said = audio, duration_s, []

    def synthesize(self, text, voice=None):
        self.said.append(text)
        return Synthesis(self.audio, self.duration_s,
                         [LineTiming(t, 0, 1) for t in text.splitlines()], None, "fake")


@pytest.fixture
def root(tmp_path):
    return tmp_path / "media"


@pytest.fixture
def cfg(root):
    return _settings(root, tts_provider="http", tts_http_url="http://127.0.0.1:1/tts")


@pytest.fixture
def tts(tmp_path, monkeypatch):
    audio = tmp_path / "voice-abc.wav"
    audio.write_bytes(b"RIFF")
    fake = FakeTTS(audio)
    monkeypatch.setattr(remix, "get_provider", lambda s: fake)
    return fake


@pytest.fixture
def reel(store, monkeypatch):
    def fake_cut(args, **kw):  # the piece cut: write the output file, no ffmpeg
        Path(args[-1]).write_bytes(b"piece")

    monkeypatch.setattr(ffmpeg, "run", fake_cut)
    r = store.add_reaction_reel(".mp4", 600.0, True, [])
    return store.activate_reaction_reel(r["id"])


def _idea(store, source):
    return store.add_idea("remix", hook="Wait for it", source_id=source["id"],
                          batch_date="2026-11-18")


def go(store, cfg, source, **kw):
    return remix.render_remix(store, cfg, _idea(store, source)["id"], source["id"],
                              **{"hook": "Wait for it", "script": SCRIPT, **kw})


def test_render_remix_claims_the_piece_with_the_asset_id(store, cfg, root, tts, reel):
    s = _source(store)
    out = go(store, cfg, s, trim=(10, 30), caption="Wow @creator")
    asset = store.get_asset(out["asset"]["id"])
    assert out["job"]["state"] == "queued" and asset["status"] == "rendering"
    piece = store.get_reaction_reel(reel["id"])
    assert piece["cursor_s"] == pytest.approx(20)  # the trimmed length
    with store._tx() as c:
        row = c.execute("SELECT asset_id, start_s, end_s FROM reaction_pieces").fetchone()
    assert tuple(row) == (asset["id"], 0, 20)
    env = asset["recipe"]
    assert env["kind"] == "ffmpeg" and env["inputs"]["reaction"] == out["piece"]["path"]
    assert env["inputs"]["source"] == s["local_path"]
    assert env["inputs"]["voice"] == "voice/voice-abc.wav"
    assert env["inputs"]["music"] == "music/music-overworld.wav"
    for rel in ("voice/voice-abc.wav", "music/music-overworld.wav", out["piece"]["path"]):
        assert (root / rel).is_file(), rel
    assert tts.said == [SCRIPT]
    assert out["warnings"] == []
    assert Recipe.model_validate(env["recipe"]).ops[0] == Trim(start_s=10, end_s=30)


def test_muted_speech_without_captions_is_a_warning(store, cfg, tts, reel):
    out = go(store, cfg, _source(store, stats={"duration_s": 60.0}))  # no transcript
    assert out["warnings"] == ["the clip's speech is muted and has no captions"
                               " (STT not set up)"]
    for quiet in (dict(audio_rights="no_audio"), dict(audio_rights="covered")):
        assert go(store, cfg, _source(store, stats={"duration_s": 60.0}, **quiet))[
            "warnings"] == []


def test_no_reaction_reel_is_refused_before_any_asset(store, cfg, tts):
    with pytest.raises(ValueError, match="upload a reaction reel in Settings"):
        go(store, cfg, _source(store))
    assert store.list_assets() == []


def test_no_tts_engine_is_refused(store, root, reel):
    with pytest.raises(ValueError, match="TTS"):
        go(store, _settings(root), _source(store))
    assert store.list_assets() == [] and store.get_reaction_reel(reel["id"])["cursor_s"] == 0


def test_voice_longer_than_the_clip_is_refused(store, cfg, tts, reel):
    tts.duration_s = 30.0
    with pytest.raises(ValueError, match="shorten the script"):
        go(store, cfg, _source(store), trim=(0, 10))


def test_idea_must_be_a_remix_of_that_source(store, cfg, tts, reel):
    s = _source(store)
    idea = store.add_idea("motion", hook="x", batch_date="2026-11-18")
    with pytest.raises(ValueError, match="remix idea"):
        remix.render_remix(store, cfg, idea["id"], s["id"], hook="h", script=SCRIPT)


def test_a_failed_piece_cut_leaves_the_asset_failed(store, cfg, tts, reel, monkeypatch):
    def broken(*a, **kw):
        raise ffmpeg.FFmpegError("cut failed")

    monkeypatch.setattr(ffmpeg, "run", broken)
    with pytest.raises(ffmpeg.FFmpegError):
        go(store, cfg, _source(store))
    (asset,) = store.list_assets()
    assert asset["status"] == "failed" and "cut failed" in asset["qc"]["reason"]


def test_list_sources_only_publishable_clips(store):
    good = _source(store)
    _source(store, rights_basis="unknown")
    _source(store, local_path=None)
    _source(store, role="reference")
    rows = remix.list_sources(store)
    assert [r["id"] for r in rows] == [good["id"]]
    assert rows[0]["attribution"] == "@creator" and rows[0]["duration_s"] == 60.0
    assert rows[0]["transcript"].startswith("before the trim across the start")
    assert rows[0]["used"] is False
    _idea(store, good)
    assert remix.list_sources(store)[0]["used"] is True


# --- @creator caption at submit -----------------------------------------------------------

def test_submit_needs_the_creator_in_the_caption_for_commentary(store, settings):
    s = _source(store)
    asset = store.add_asset(_idea(store, s)["id"], batch_date="2026-11-18",
                            qc={"passed": True}, file_path="2026-11-18/1/video.mp4")
    transition(store, asset["id"], "ready", actor="worker")
    args = dict(self_score=7, self_score_reason="funny", best_before="2026-12-01")
    for caption in ("So good", "So good @creatorx"):
        with pytest.raises(ValueError, match="add @creator"):
            production.submit_asset(store, settings, asset["id"], caption=caption, **args)
    row = production.submit_asset(store, settings, asset["id"], caption="So good @Creator.",
                                  **args)
    assert row["self_score"] == 7


# --- MCP doors ----------------------------------------------------------------------------

async def test_mcp_tools_call_the_services(monkeypatch):
    calls = {}

    def queue(store, settings, idea_id, source_id, **kw):
        calls.update(kw, idea_id=idea_id, source_id=source_id)
        return {"asset": {"id": 7}, "job": {"id": 3, "state": "queued"},
                "piece": {"piece_id": 2, "path": "reactions/1/pieces/2.mp4", "start_s": 0,
                          "end_s": 20}, "warnings": ["w"]}

    monkeypatch.setattr(remix, "render_remix", queue)
    monkeypatch.setattr(remix, "list_sources", lambda store, role, limit: [{"id": 1}])
    monkeypatch.setattr(srv, "store", lambda: None)
    assert await srv.list_sources() == {"sources": [{"id": 1}]}
    assert await srv.render_remix(1, 2, "hook", SCRIPT, trim_start_s=10) == {
        "asset_id": 7, "job_id": 3, "state": "queued",
        "reaction_piece": {"piece_id": 2, "start_s": 0, "end_s": 20}, "warnings": ["w"]}
    assert calls["trim"] == (10, None) and calls["layout"] == "pip"

    def refused(*a, **kw):
        raise ValueError("commentary needs a voice-over script")

    monkeypatch.setattr(remix, "render_remix", refused)
    with pytest.raises(ToolError, match="voice-over script"):
        await srv.render_remix(1, 2, "hook", "")


# --- real ffmpeg ----------------------------------------------------------------------------

@needs_ffmpeg
def test_trim_op_cuts_the_clip(tmp_path):
    clip = make_clip(tmp_path / "in.mp4", "320x568", duration=3)
    info = render(Recipe(ops=[Trim(start_s=0.5, end_s=2.0), recipe.FitVertical()]),
                  {"source": clip}, tmp_path / "out.mp4", timeout_s=120, preset="ultrafast")
    assert_spec(info, 1.5)


@needs_ffmpeg
def test_a_built_remix_renders(store, tmp_path):
    clip = make_clip(tmp_path / "clip.mp4", "320x568", duration=3)
    reaction = make_clip(tmp_path / "reaction.mp4", "480x640", duration=2)
    voice = make_clip(tmp_path / "voice.mp4", "160x120", duration=1)
    r = build(_source(store, stats={"duration_s": 3.0}), trim=(0.5, 2.5),
              captions=[{"start_s": 0.2, "end_s": 1.0, "text": "hello"}], music=True)
    info = render(r, {"source": clip, "reaction": reaction, "voice": voice,
                      "music": remix.MUSIC_DIR / "music-overworld.wav"},
                  tmp_path / "out.mp4", timeout_s=180, preset="ultrafast")
    assert_spec(info, 2.0)


# --- 072: the owner's review of a remix -----------------------------------------------------

@pytest.fixture
def tc(store, cfg):
    from fastapi.testclient import TestClient

    from src.api.app import create_app
    from tests.conftest import LOCAL
    with TestClient(create_app(cfg, store=store), base_url=LOCAL,
                    headers={"Origin": LOCAL}) as c:
        yield c


def _remix_asset(store, cfg, status="ready"):
    out = go(store, cfg, _source(store), trim=(10, 30), caption="Wow @creator")
    a = out["asset"]
    if status != "rendering":
        transition(store, a["id"], status if status == "failed" else "ready", actor="worker")
    return store.get_asset(a["id"]), out["piece"]


def test_reaction_endpoint(tc, store, cfg, tts, reel):
    a, piece = _remix_asset(store, cfg)
    r = tc.get(f"/api/assets/{a['id']}/reaction")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["piece"] == {"id": piece["piece_id"], "start_s": 0, "end_s": 20,
                             "url": f"/api/media/{piece['path']}"}
    assert body["reel"]["id"] == reel["id"] and body["reel"]["duration_s"] == 600
    assert body["source"]["attribution"] == "@creator"
    assert body["source"]["rights_basis"] == "commentary"
    assert body["trim"] == {"start_s": 10, "end_s": 30}
    assert [(x["index"], x["text"]) for x in body["transcript"]] == [
        (1, "across the start"), (2, "inside")]
    motion = store.add_asset(store.add_idea("motion")["id"],
                             recipe={"kind": "motion", "template": "Hello", "props": {}})
    assert tc.get(f"/api/assets/{motion['id']}/reaction").status_code == 422
    assert tc.get("/api/assets/999/reaction").status_code == 404


def _pieces(store):
    with store._tx() as c:
        return [tuple(r) for r in c.execute("SELECT id, asset_id, start_s FROM reaction_pieces")]


def test_next_piece_makes_a_child_of_a_ready_remix(tc, store, cfg, tts, reel):
    a, first = _remix_asset(store, cfg)
    r = tc.post(f"/api/assets/{a['id']}/next-piece")
    assert r.status_code == 200, r.text
    child = r.json()["asset"]
    assert child["parent_asset_id"] == a["id"] and child["status"] == "rendering"
    assert store.get_asset(a["id"])["status"] == "ready"
    new = r.json()["piece"]
    assert new["piece_id"] != first["piece_id"] and new["start_s"] == 20  # the next 20 s
    assert child["recipe"]["inputs"]["reaction"] == new["path"]
    assert child["recipe"]["recipe"] == a["recipe"]["recipe"]
    assert _pieces(store) == [(first["piece_id"], a["id"], 0), (new["piece_id"], child["id"], 20)]


def test_next_piece_re_renders_a_failed_remix_in_place(tc, store, cfg, tts, reel):
    a, first = _remix_asset(store, cfg, "failed")
    r = tc.post(f"/api/assets/{a['id']}/next-piece")
    assert r.status_code == 200 and r.json()["asset"]["id"] == a["id"]
    assert store.get_asset(a["id"])["status"] == "rendering"
    assert store.get_asset(a["id"])["recipe"]["inputs"]["reaction"] == r.json()["piece"]["path"]
    # A remix still rendering is refused before any piece is used.
    r = tc.post(f"/api/assets/{a['id']}/next-piece")
    assert r.status_code == 409 and len(_pieces(store)) == 2


def test_fix_transcript_validates_and_rebuilds_captions(tc, store, cfg, tts, reel):
    a, _ = _remix_asset(store, cfg)
    url = f"/api/assets/{a['id']}/transcript"
    for texts, why in ((["one"], "send 2 lines"), (["ok", "  "], "line 2 is empty"),
                       (["x" * 81, "ok"], "longer than 80"),
                       (["🙂", "ok"], "emoji are removed")):  # refused by the recipe
        r = tc.post(url, json={"texts": texts})
        assert r.status_code == 422 and why in r.json()["message"], r.text
    source_id = store.get_idea(a["idea_id"])["source_id"]
    assert store.get_source(source_id)["stats"]["transcript"]["lines"] == LINES
    r = tc.post(url, json={"texts": ["across  the START", "inside!"]})
    assert r.status_code == 200, r.text
    lines = store.get_source(source_id)["stats"]["transcript"]["lines"]
    assert [x["text"] for x in lines] == ["before the trim", "across the START", "inside!",
                                          "across the end"]
    assert [x["start_s"] for x in lines] == [x["start_s"] for x in LINES]  # same timings
    child = r.json()["asset"]
    assert child["parent_asset_id"] == a["id"]
    ops = child["recipe"]["recipe"]["ops"]
    caps = next(op for op in ops if op["op"] == "captions")
    assert [c["text"] for c in caps["lines"]] == ["across the START", "inside!"]
    assert [op["op"] for op in ops] == [op["op"] for op in a["recipe"]["recipe"]["ops"]]


# --- 119: look at a clip and store what happens in it ---------------------------------------

EVENTS = [{"t": 12.0, "d": 2.0, "e": "the dog jumps on the sofa"},
          {"t": 2.0, "d": 3.0, "e": "a man   opens the door"},  # unsorted, spaces squeezed
          {"t": 35.0, "d": 30.0, "e": "the dog falls"}]  # d cut at the clip's end


def test_set_clip_timeline_validates_compresses_and_overwrites(store, cfg):
    s = _source(store)
    out = remix.set_clip_timeline(store, cfg, s["id"], EVENTS, "  A dog fails a jump.  ")
    stored = store.get_source(s["id"])["stats"]
    assert stored["timeline"] == out["timeline"] == [
        {"t": 2.0, "d": 3.0, "e": "a man opens the door"},
        {"t": 12.0, "d": 2.0, "e": "the dog jumps on the sofa"},
        {"t": 35.0, "d": 25.0, "e": "the dog falls"}]
    assert stored["summary"] == "A dog fails a jump." and stored["transcript"]["lines"] == LINES
    many = [{"t": i, "d": 1, "e": f"beat {i} " + "x" * 60} for i in range(40)]
    capped = remix.set_clip_timeline(store, cfg, s["id"], many, "Again.")["timeline"]
    assert capped[-1]["e"].endswith("more") and len(json.dumps(capped)) <= 2000
    remix.set_clip_timeline(store, cfg, s["id"], EVENTS[:1], "Short.")  # overwrites
    assert store.get_source(s["id"])["stats"]["timeline"] == [
        {"t": 12.0, "d": 2.0, "e": "the dog jumps on the sofa"}]
    for events, summary, why in (
            ([{"t": 60, "d": 1, "e": "x"}], "ok", "event 1: t must lie within"),
            ([{"t": -1, "d": 1, "e": "x"}], "ok", "t must lie within"),
            ([{"t": 1, "d": -1, "e": "x"}], "ok", "d not negative"),
            ([{"t": 1, "e": "x"}], "ok", "needs t and d"),
            (["nope"], "ok", "needs t and d"),
            ([{"t": 1, "d": 1, "e": "x" * 81}], "ok", "1-80 characters"),
            ([{"t": 1, "d": 1, "e": "  "}], "ok", "1-80 characters"),
            ([], "ok", "1-40 events"), (many + many[:1], "ok", "1-40 events"),
            (EVENTS, " ", "summary"), (EVENTS, "x" * 401, "summary")):
        with pytest.raises(ValueError, match=why):
            remix.set_clip_timeline(store, cfg, s["id"], events, summary)
    assert store.get_source(s["id"])["stats"]["summary"] == "Short."  # refusals change nothing


def test_only_downloaded_clips(store, cfg):
    for kw in (dict(role="reference"), dict(local_path=None)):
        s = _source(store, **kw)
        with pytest.raises(ValueError, match="not a downloaded clip"):
            remix.set_clip_timeline(store, cfg, s["id"], EVENTS, "x")
        with pytest.raises(ValueError, match="not a downloaded clip"):
            remix.clip_frames(store, cfg, s["id"])


def test_clip_frames_refuses_bad_times(store, cfg):
    s = _source(store)  # 60 s, no file needed: refused before ffmpeg
    for kw, why in ((dict(times_s=[30, 61]), "within the clip"),
                    (dict(times_s=[-1]), "within the clip"),
                    (dict(times_s=list(range(13))), "at most 12"),
                    (dict(n=0), "n must be"), (dict(n=13), "n must be")):
        with pytest.raises(ValueError, match=why):
            remix.clip_frames(store, cfg, s["id"], **kw)


def _clip_file(root):
    (root / "sources" / "1").mkdir(parents=True)
    make_clip(root / "sources" / "1" / "clip.mp4", "320x568", duration=3)


@needs_ffmpeg
def test_clip_frames_at_times_and_spread(store, cfg, root, monkeypatch):
    _clip_file(root)
    s = _source(store, stats={"duration_s": 3.0, "transcript": {"lines": LINES}})
    remix.set_clip_timeline(store, cfg, s["id"], [{"t": 1, "d": 1, "e": "a wave"}], "Waves.")
    jpegs, info = remix.clip_frames(store, cfg, s["id"], n=3)
    assert info == {"source_id": s["id"], "duration_s": 3.0, "frame_times_s": [0.5, 1.5, 2.5],
                    "transcript": "before the trim across the start inside across the end",
                    "timeline": [{"t": 1.0, "d": 1.0, "e": "a wave"}], "summary": "Waves."}
    assert len(jpegs) == 3 and all(j[:2] == b"\xff\xd8" for j in jpegs)
    at, info = remix.clip_frames(store, cfg, s["id"], times_s=[0, 1.5, 3])
    assert info["frame_times_s"] == [0.0, 1.5, 2.9] and at[1] == jpegs[1]  # same cache
    monkeypatch.setattr(ffmpeg, "run", pytest.fail)  # all cached now
    assert remix.clip_frames(store, cfg, s["id"], times_s=[0, 1.5, 3])[0] == at


def test_list_sources_shows_the_summary(store, cfg):
    s = _source(store)
    row = remix.list_sources(store)[0]
    assert row["summary"] is None and row["has_timeline"] is False
    remix.set_clip_timeline(store, cfg, s["id"], EVENTS, "A dog fails a jump.")
    row = remix.list_sources(store)[0]
    assert row["summary"] == "A dog fails a jump." and row["has_timeline"] is True


def test_remix_timeline_has_the_clip_events_shifted_and_capped(store, cfg, tts, reel):
    s = _source(store)
    remix.set_clip_timeline(store, cfg, s["id"], EVENTS, "A dog fails a jump.")
    env = store.get_asset(go(store, cfg, s, trim=(10, 40))["asset"]["id"])["recipe"]
    assert env["clip_timeline"] == store.get_source(s["id"])["stats"]["timeline"]
    parsed = FfmpegRecipe.model_validate(env)  # as render_files reads it
    events = recipe_timeline(parsed.recipe, 30.0, parsed.clip_timeline)
    clip = [e for e in events if e["e"].startswith("clip:")]
    # "a man opens the door" ends before the trim; "the dog falls" is cut at its end.
    assert clip == [{"t": 2.0, "d": 2.0, "e": "clip: 'the dog jumps on the sofa'"},
                    {"t": 25.0, "d": 5.0, "e": "clip: 'the dog falls'"}]
    assert any(e["e"].startswith("hook text") for e in events)
    many = [{"t": i, "d": 1, "e": f"beat {i}"} for i in range(60)] + [{"e": "+3 more"}]
    capped = recipe_timeline(parsed.recipe, 30.0, many)
    assert len(capped) <= 41 and capped[-1]["e"].endswith("more")
    assert len(json.dumps(capped)) <= 2000
    # A source without a timeline: no envelope key.
    assert "clip_timeline" not in go(store, cfg, _source(store))["asset"]["recipe"]


@needs_ffmpeg
async def test_clip_tools_in_the_agent_profile(store, cfg, root, monkeypatch):
    _clip_file(root)
    s = _source(store, stats={"duration_s": 3.0})
    monkeypatch.setattr(srv, "store", lambda: store)
    monkeypatch.setattr(srv, "get_settings", lambda: cfg)
    agent = srv.build_server("agent")
    out = await agent.call_tool("set_clip_timeline", {
        "source_id": s["id"], "events": [{"t": 0.5, "d": 1, "e": "a wave"}], "summary": "W."})
    assert not out.is_error and "a wave" in out.content[0].text
    result = await agent.call_tool("get_clip_frames", {"source_id": s["id"], "n": 2})
    text, *images = result.content
    assert json.loads(text.text)["timeline"] == [{"t": 0.5, "d": 1.0, "e": "a wave"}]
    assert [i.mime_type for i in images] == ["image/jpeg"] * 2
    with pytest.raises(ToolError, match="at most 12"):
        await agent.call_tool("get_clip_frames", {"source_id": s["id"],
                                                  "times_s": [0.1] * 13})
