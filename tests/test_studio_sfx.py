"""Step 150: the sound-effects library (src/studio/sfx.py): Openverse search (respx, never the
network), the cache and manifest, the starter pack, find_sfx, `ov:<id>` at render, credits."""

import json
import shutil
import uuid
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
import respx

import src.instagram_mcp_server as srv
from src.agent import film
from src.config import InstagramMCPSettings
from src.store import utcnow
from src.studio import ffmpeg, lemo, motion, production, sfx
from src.studio.assets import transition
from src.studio.publish import QueueRefused, queue_asset
from tests.test_studio_ffmpeg import needs_ffmpeg
from tests.test_studio_motion import VALID
from tests.test_studio_recipe import make_clip

CDN = "https://cdn.freesound.org/previews"


def _result(licence="cc0", *, ms=1500, tags=("boing", "cartoon"), **kw):
    rid = kw.pop("id", None) or str(uuid.uuid4())
    return {"id": rid, "title": f"Boing #{rid[:4]}.wav", "creator": "InspectorJ",
            "creator_url": "https://freesound.org/people/InspectorJ",
            "license": licence, "license_version": "1.0" if licence == "cc0" else "4.0",
            "license_url": f"https://creativecommons.org/licenses/{licence}/4.0/",
            "foreign_landing_url": f"https://freesound.org/people/InspectorJ/sounds/{rid[:4]}",
            "url": f"{CDN}/{rid}.mp3", "provider": "freesound", "mature": False,
            "attribution": f'"Boing" by InspectorJ is licensed under {licence}.',
            "tags": [{"name": t, "accuracy": None} for t in tags], "duration": ms, **kw}


def _page(*results):
    return httpx.Response(200, json={"result_count": len(results), "results": list(results)})


@pytest.fixture(scope="module")
def tone(tmp_path_factory):
    """A recording as a provider serves it: 0.5 s of silence, 8 s of tone, 1 s of silence."""
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not on PATH")
    path = tmp_path_factory.mktemp("tone") / "tone.wav"
    ffmpeg.run(["-f", "lavfi", "-i", "sine=frequency=440:duration=8", "-af",
                "adelay=500,apad=pad_dur=1,volume=-12dB", path], timeout_s=60)
    return path.read_bytes()


def _downloads(tone):
    return respx.get(url__startswith=CDN).mock(return_value=httpx.Response(200, content=tone))


# --- search ------------------------------------------------------------------------------
@respx.mock
def test_search_asks_cc0_and_cc_by_sounds_and_refuses_everything_else():
    keep = [_result("cc0"), _result("by")]
    refused = [_result(lic) for lic in ("by-nc", "by-sa", "by-nd", "by-nc-sa", "pdm",
                                        "sampling+")]
    refused += [_result("cc0", ms=25_000), _result("cc0", mature=True),
                _result("cc0", url="http://insecure/x.mp3"), _result("cc0", id="../etc")]
    route = respx.get(sfx.API).mock(return_value=_page(*refused[:3], *keep, *refused[3:]))
    with sfx._client() as c:
        found = sfx.search("  boing  ", client=c)
    assert [e["id"] for e in found] == [e["id"] for e in keep]
    q = route.calls.last.request.url.params
    assert (q["q"], q["license"], q["source"], q["length"], q["page_size"]) == (
        "boing", "cc0,by", "freesound", "shortest", "20")
    assert "category" not in q  # Openverse's sound_effect category is empty today
    assert route.calls.last.request.headers["user-agent"] == sfx.USER_AGENT
    cc0, by = found
    assert cc0["credit"] is None and "#" not in cc0["title"] and not cc0["title"].endswith(".wav")
    assert by["credit"].startswith('Son : "Boing') and by["credit"].endswith("CC BY 4.0")
    assert "freesound.org/people/InspectorJ/sounds/" in by["credit"]
    assert by["tags"] == ["boing", "cartoon"] and by["source_duration_s"] == 1.5


@respx.mock
def test_search_rate_limit_and_empty_query():
    respx.get(sfx.API).mock(return_value=httpx.Response(429))
    with sfx._client() as c:
        with pytest.raises(sfx.RateLimited):
            sfx.search("pop", client=c)
        with pytest.raises(ValueError):
            sfx.search("   ", client=c)


# --- cache -------------------------------------------------------------------------------
@needs_ffmpeg
@respx.mock
def test_fetch_converts_trims_levels_and_records_the_manifest(tone):
    e = sfx._entry(_result("by"))
    dl = _downloads(tone)
    with sfx._client() as c:
        saved = sfx.fetch(e, client=c, category="boing")
        assert sfx.fetch(e, client=c) == saved and dl.call_count == 1  # cached
    out = sfx.SFX_DIR / f"{e['id']}.wav"
    info = ffmpeg.probe(out)
    assert (info.sample_rate, info.audio_codec) == (48000, "pcm_s16le")
    assert sfx.MAX_S - 0.05 <= info.duration <= sfx.MAX_S + 0.05  # 8 s of tone cut to 6
    assert abs(sfx.peak_lufs(out) - sfx.PEAK_LUFS) < 0.5 and saved["peak_lufs"] <= -19.5
    on_disk = json.loads(sfx.manifest_path().read_text("utf-8"))["sounds"][e["id"]]
    assert on_disk == saved
    for key in ("title", "creator", "licence", "licence_url", "source_url", "attribution",
                "credit", "tags", "duration_s", "peak_lufs", "file", "category"):
        assert saved[key] is not None, key
    assert not list(sfx.SFX_DIR.glob("tmp*"))  # the work folder is gone


@needs_ffmpeg
@respx.mock
def test_silence_is_trimmed_off_both_ends_and_bad_licences_refused(tmp_path, tone):
    e = sfx._entry(_result("cc0"))
    with sfx._client() as c:
        with pytest.raises(ValueError, match="CC0 and CC BY only"):
            sfx.fetch({**e, "licence": "by-nc"}, client=c)
    short = tmp_path / "short.wav"  # 0.5 s of silence, 1 s of tone, 1 s of silence
    ffmpeg.run(["-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-af",
                "adelay=500,apad=pad_dur=1", short], timeout_s=60)
    sfx.convert(short, tmp_path / "short-out.wav")
    assert abs(ffmpeg.probe(tmp_path / "short-out.wav").duration - 1.0) < 0.05
    silent = tmp_path / "silent.wav"
    ffmpeg.run(["-f", "lavfi", "-i", "anullsrc=d=1", silent], timeout_s=60)
    with pytest.raises(ValueError, match="silent"):
        sfx.convert(silent, tmp_path / "out.wav")


# --- starter pack ------------------------------------------------------------------------
@needs_ffmpeg
@respx.mock
def test_seed_prefers_cc0_skips_music_keeps_what_it_has_and_stops_on_429(tone):
    by, cc0 = _result("by"), _result("cc0")
    music = _result("cc0", tags=("music", "loop"))
    calls = []

    def answer(request):
        calls.append(request.url.params["q"])
        return {"pop": _page(music, by, cc0), "boing": _page(_result("by"), _result("cc0")),
                "ding": httpx.Response(429)}[request.url.params["q"]]

    respx.get(sfx.API).mock(side_effect=answer)
    _downloads(tone)
    out = sfx.seed(only=["pop", "boing"], pause_s=0)
    assert out == {"fetched": 4, "kept": 0, "failed": []}
    pops = {e["id"] for e in sfx.load().values() if e["category"] == "pop"}
    assert pops == {by["id"], cc0["id"]}  # the music loop is skipped
    # cached categories are not searched again; after a 429 nothing more is searched
    out = sfx.seed(only=["pop", "ding", "boing", "gasp"], pause_s=0)
    assert out["kept"] == 4 and calls == ["pop", "boing", "ding"]
    assert [f["category"] for f in out["failed"]] == ["ding", "gasp"]
    assert "rate limit" in out["failed"][1]["error"]
    with pytest.raises(ValueError, match="unknown categories"):
        sfx.seed(only=["kazoo"])
    assert sum(n for _, n in sfx.SEED.values()) >= 30


# --- find_sfx and the MCP tool -----------------------------------------------------------
@needs_ffmpeg
@respx.mock
async def test_find_sfx_cache_first_then_fetch_on_demand(tone):
    route = respx.get(sfx.API).mock(return_value=_page(_result("by", tags=("fork", "drop")),
                                                       _result("cc0", tags=("fork", "drop"))))
    _downloads(tone)
    out = await srv.find_sfx("fork drop", 5)  # nothing cached: fetched now, CC0 first
    assert out["fetched"] == 2 and route.call_count == 1
    assert [s["licence"] for s in out["sounds"]] == ["cc0", "by"]
    first = out["sounds"][0]
    assert sfx.REF.match(first["ref"]) and first["credit"] is None
    assert set(first) == {"ref", "title", "category", "duration_s", "licence", "credit",
                          "creator", "tags", "source_url"}
    again = sfx.find_sfx("drop fork")  # every word cached: no network
    assert again["fetched"] == 0 and route.call_count == 1 and len(again["sounds"]) == 2
    route.mock(return_value=httpx.Response(503))
    near = sfx.find_sfx("fork bang")  # nothing has both words, Openverse fails: closest
    assert near["sounds"] and "closest" in near["note"]
    with pytest.raises(Exception, match="say what sound"):
        await srv.find_sfx("  ")


@respx.mock
async def test_find_sfx_error_when_nothing_cached_and_openverse_down():
    respx.get(sfx.API).mock(return_value=httpx.Response(429))
    with pytest.raises(Exception, match="Openverse failed"):
        await srv.find_sfx("gasp")


# --- renders and credits -----------------------------------------------------------------
def _cache(licence="by", **kw):
    """A sound in the library without a download (manifest entry + file)."""
    e = sfx._entry(_result(licence, **kw))
    sfx.SFX_DIR.mkdir(parents=True, exist_ok=True)
    (sfx.SFX_DIR / f"{e['id']}.wav").write_bytes(b"RIFF")
    sfx._save({**e, "file": f"{e['id']}.wav", "category": None})
    return e


def test_refs_credits_and_stage(tmp_path):
    by, cc0 = _cache("by"), _cache("cc0")
    props = {"beats": [{"sfx": f"ov:{by['id']}"}, {"sfx": "hit"}, {"sfx": f"ov:{cc0['id']}"}],
             "sting": f"ov:{by['id']}", "hook": "ov:not-a-sound"}
    assert sfx.refs(props) == [by["id"], cc0["id"]]
    assert sfx.credits(props) == [by["credit"]]  # CC0 needs none
    sfx.stage(tmp_path / "public", props)
    assert sorted(p.name for p in (tmp_path / "public" / sfx.BUNDLE_DIR).iterdir()) == sorted(
        [f"{by['id']}.wav", f"{cc0['id']}.wav"])
    gone = f"ov:{uuid.uuid4()}"
    with pytest.raises(ValueError, match="not in the library"):
        sfx.credits({"sting": gone})
    with pytest.raises(ValueError, match="find_sfx first"):
        sfx.stage(tmp_path / "public", {"sting": gone})


def test_caption_credits():
    recipe = {"kind": "motion", "sfx_credits": ['Son : "Boing" par X, CC BY 4.0']}
    assert sfx.missing_credits(recipe, "Fun #fit") == recipe["sfx_credits"]
    cap = sfx.with_credits("Fun #fit  ", recipe)
    assert cap == 'Fun #fit\n\nSon : "Boing" par X, CC BY 4.0'
    assert sfx.with_credits(cap, recipe) == cap and sfx.missing_credits(recipe, cap) == []
    assert sfx.with_credits("x", {"kind": "motion"}) == "x"
    assert sfx.missing_credits(None, "") == []


@needs_ffmpeg
def test_a_render_stages_library_sounds_into_the_bundle(tmp_path, monkeypatch):
    by = _cache("by")
    seen = {}

    def fake_render(t, p, out, w, **kw):
        seen["files"] = sorted(x.name for x in (tmp_path / "bundle" / "public" / "ov-sfx"
                                                ).iterdir())
        return make_clip(out, "108x192", audio=False)

    monkeypatch.setattr(motion, "validate_props", lambda t, p: {**VALID, "props": p, "events": []})
    monkeypatch.setattr(motion, "bundle_dir", lambda: tmp_path / "bundle")
    monkeypatch.setattr(motion, "_render", fake_render)
    motion.render_motion_asset("PixelSkit", {"sting": f"ov:{by['id']}"}, tmp_path / "v.mp4",
                               tmp_path, timeout_s=60)
    assert seen["files"] == [f"{by['id']}.wav"]


def test_queue_motion_render_keeps_the_credits_and_refuses_unknown_sounds(store, tmp_path,
                                                                         monkeypatch):
    by = _cache("by")
    monkeypatch.setattr(motion, "validate_props", lambda t, p: {**VALID, "props": p})
    monkeypatch.setattr(motion, "list_templates", lambda: [{"id": "Hello", "style": "pixel"}])
    s = InstagramMCPSettings(_env_file=None, database_path=":memory:", media_root=str(tmp_path))
    idea = store.add_idea("motion")
    out = motion.queue_motion_render(store, s, template="Hello",
                                     props={"sting": f"ov:{by['id']}"}, idea_id=idea["id"])
    assert out["asset"]["recipe"]["sfx_credits"] == [by["credit"]]
    plain = motion.queue_motion_render(store, s, template="Hello", props={"sting": "hit"},
                                       idea_id=idea["id"])
    assert "sfx_credits" not in plain["asset"]["recipe"]
    with pytest.raises(ValueError, match="not in the library"):
        motion.queue_motion_render(store, s, template="Hello",
                                   props={"sting": f"ov:{uuid.uuid4()}"}, idea_id=idea["id"])


def test_submit_adds_the_cc_by_credit_and_the_publish_guard_checks_it(store, tmp_path):
    s = InstagramMCPSettings(_env_file=None, database_path=":memory:", media_root=str(tmp_path))
    credit = 'Son : "Boing" par InspectorJ (freesound.org/s/1), CC BY 4.0'
    idea = store.add_idea("motion", pillar="fun_facts", batch_date="2026-11-17")
    rel = "2026-11-17/master.mp4"
    (tmp_path / rel).parent.mkdir(parents=True)
    (tmp_path / rel).write_bytes(b"mp4")
    a = store.add_asset(idea["id"], batch_date="2026-11-17", file_path=rel,
                        qc={"passed": True}, recipe={"kind": "motion", "template": "PixelSkit",
                                                     "props": {}, "sfx_credits": [credit]})
    transition(store, a["id"], "ready", actor="worker")
    production.submit_asset(store, s, a["id"],
                            caption="Boing ! #fun")
    assert store.get_asset(a["id"])["caption"] == f"Boing ! #fun\n\n{credit}"
    transition(store, a["id"], "approved", actor="owner")
    store.update_asset(a["id"], caption="Boing ! #fun")  # the owner took the credit out
    with pytest.raises(QueueRefused, match="credit the sounds"):
        queue_asset(store, s, a["id"], utcnow() + timedelta(hours=2))
    store.update_asset(a["id"], caption=f"Boing !\n{credit}")
    assert queue_asset(store, s, a["id"], utcnow() + timedelta(hours=2))


def test_a_film_workspace_gets_a_copy_of_the_library(tmp_path):
    s = InstagramMCPSettings(_env_file=None, database_path=":memory:",
                             agent_workspace=str(tmp_path / "ws"),
                             lemo_skill_dir=str(tmp_path / "skill"))
    (tmp_path / "skill").mkdir()
    (tmp_path / "skill" / "SKILL.md").write_text("skill", "utf-8")
    brief = lemo.film_brief(s, {"id": 3, "instruction": "x"},
                            {"id": "lemo:a", "slug": "a", "label": "A", "line": "l"})
    assert "sfx/manifest.json" in brief and "credit" in brief
    assert not (film.prepare_workspace(s, 3, brief) / film.SFX).exists()  # no library yet
    by = _cache("by")
    ws = film.prepare_workspace(s, 3, brief)
    assert (ws / film.SFX / f"{by['id']}.wav").is_file()
    assert by["id"] in json.loads((ws / film.SFX / "manifest.json").read_text("utf-8"))["sounds"]
    assert not list((ws / film.SFX).glob(".*"))  # not the lock file


def test_motion_and_python_agree_on_the_library_peak():
    duck = (Path(motion.MOTION_DIR) / "src" / "lib" / "duck.ts").read_text("utf-8")
    assert f"LIBRARY_PEAK_LUFS = {sfx.PEAK_LUFS:g};" in duck
    assert f'BUNDLE_DIR = "{sfx.BUNDLE_DIR}"' in Path(sfx.__file__).read_text("utf-8")
    assert f"`{sfx.BUNDLE_DIR}/" in (Path(motion.MOTION_DIR) / "src" / "components" /
                                     "Sfx.tsx").read_text("utf-8")


def test_a_motion_recipe_keeps_its_sound_credits(tmp_path):
    """179: the motion envelope forbade sfx_credits, so a render with a CC BY sound failed."""
    from src.studio import render
    env = {"kind": "motion", "template": "PixelSkit", "props": {},
           "sfx_credits": ['Son : "Boing" par X, CC BY 4.0']}
    assert render.validate_recipe(env, tmp_path)["sfx_credits"] == env["sfx_credits"]
