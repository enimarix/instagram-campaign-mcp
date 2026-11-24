"""The Voix page (owner's casting 2026-11-22): the voice-over voices from brand/voices/voices.json,
the owner's on / off, and only the voices on reaching a video (render_motion, render_remix,
the agent's copy of voices.json)."""

import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.studio import motion, sitcom, tts, voices

from .conftest import LOCAL
from .test_api_assets import _settings

ENTRIES = [
    {"id": "a", "label": "A", "description": "designed", "sample_text": "salut",
     "address": ["tu"], "default": True, "enabled": True, "gender": "female",
     "recipe": {"style": "warm", "seed": 1}},
    {"id": "b", "label": "B", "description": "designed too", "enabled": True, "gender": "male",
     "recipe": {"style": "fast", "seed": 2}},
    {"id": "old", "label": "Old", "description": "cloned", "card_text": "bonjour",
     "enabled": False, "gender": "male"},
]


@pytest.fixture
def folder(tmp_path, monkeypatch):
    (tmp_path / "voices.json").write_text(json.dumps({"voices": ENTRIES}), encoding="utf-8")
    for v in ("a", "old"):  # b has no sample file
        (tmp_path / f"{v}.wav").write_bytes(b"RIFFwav")
    monkeypatch.setattr(voices, "VOICES_DIR", tmp_path)
    return tmp_path


def test_voices_list_with_the_json_defaults_and_samples(store, folder):
    listed = voices.list_voices(store)
    assert [(v["id"], v["enabled"], v["designed"]) for v in listed] == [
        ("a", True, True), ("b", True, True), ("old", False, False)]
    by = {v["id"]: v for v in listed}
    assert by["a"]["sample"] == "/api/voices/a/sample" and by["b"]["sample"] is None
    assert by["old"]["sample_text"] == "bonjour"  # a cloned voice's card says its card_text
    assert voices.sample_file("a") == folder / "a.wav"
    assert voices.sample_file("b") is None and voices.sample_file("../voices") is None


def test_owner_turns_voices_on_and_off_but_one_stays_on(store, folder):
    assert voices.set_enabled(store, "old", True)["enabled"] is True
    assert voices.set_enabled(store, "a", False)["enabled"] is False
    voices.set_enabled(store, "old", False)
    with pytest.raises(ValueError, match="at least one voice"):
        voices.set_enabled(store, "b", False)
    with pytest.raises(ValueError, match="unknown voice"):
        voices.set_enabled(store, "nope", True)
    assert [v["id"] for v in voices.enabled_voices(store)] == ["b"]


def test_only_voices_on_reach_a_video(store, folder):
    assert voices.check_voice(store, None) == "a"  # the default
    assert voices.check_voice(store, "b") == "b"
    with pytest.raises(ValueError, match="voices on: a, b"):
        voices.check_voice(store, "old")
    voices.set_enabled(store, "a", False)
    assert voices.check_voice(store, None) == "b"  # default off: the first voice on


def test_the_agent_sees_the_voices_on_only(store, folder, tmp_path):
    voices.set_enabled(store, "a", False)
    dest = tmp_path / "ws-voices.json"
    voices.agent_copy(store, dest)
    copied = json.loads(dest.read_text(encoding="utf-8"))["voices"]
    assert [(v["id"], v["default"]) for v in copied] == [("b", True)]
    assert "recipe" not in copied[0] and "enabled" not in copied[0]


def test_brand_voices_are_the_owner_casting(store):
    """The real list: the three designed voices on, souriante the default, the old cloned
    voices off; every voice has its sample."""
    listed = voices.list_voices(store)
    assert [v["id"] for v in listed if v["enabled"]] == [
        "souriante", "energique_femme", "energique_homme"]
    assert voices.default_voice(store) == "souriante"
    assert all(v["sample"] for v in listed)
    assert all(v["use_for"] for v in listed if v["enabled"])  # what the AI picks each one for


def test_voices_api(store, folder):
    with TestClient(create_app(_settings(), store=store), base_url=LOCAL) as tc:
        assert [v["id"] for v in tc.get("/api/voices").json()] == ["a", "b", "old"]
        r = tc.get("/api/voices/a/sample")
        assert r.status_code == 200 and r.content == b"RIFFwav"
        assert r.headers["content-type"] == "audio/wav"
        assert tc.get("/api/voices/b/sample").status_code == 404
        assert tc.patch("/api/voices/old", json={"enabled": True}).json()["enabled"] is True
        assert tc.patch("/api/voices/nope", json={"enabled": True}).status_code == 422
        assert tc.patch("/api/voices/a", json={"on": True}).status_code == 422


def test_sitcom_characters_speak_in_voices_on(store, folder):
    cast = voices.say_cast(store)
    assert cast == {"male": ("b", "a"), "female": ("a", "b")}  # "old" is off
    assert sitcom.say_voice("dad", "a", cast) == "b"
    assert sitcom.say_voice("grandma", "a", cast) == "b"  # the narrator has "a"
    assert sitcom.say_voice("grandma", "b", cast) == "a"
    voices.set_enabled(store, "b", False)
    assert voices.say_cast(store) == {"male": ("a", "a"), "female": ("a", "a")}


def test_a_re_tuned_recipe_is_new_audio_in_the_cache(store, folder, tmp_path):
    s = _settings(tts_provider="http", tts_http_url="http://127.0.0.1:1/tts",
                  tts_cache_dir=str(tmp_path / "cache"))
    provider = tts.get_provider(s)
    before = provider.cache_key("Salut.", "a")
    assert provider.cache_key("Salut.", "old") == provider.cache_key("Salut.", "old")
    entries = [{**e, "recipe": {**e["recipe"], "seed": 9}} if e["id"] == "a" else e
               for e in ENTRIES]
    (folder / "voices.json").write_text(json.dumps({"voices": entries}), encoding="utf-8")
    assert provider.cache_key("Salut.", "a") != before
    assert voices.recipe("a")["seed"] == 9 and voices.recipe("old") is None


def test_a_re_render_keeps_its_voice_even_if_turned_off(store, folder, tmp_path, monkeypatch):
    monkeypatch.setattr(motion, "validate_props", lambda t, p: {
        "props": p, "fps": 30, "durationInFrames": 90, "coverFrame": 12})
    monkeypatch.setattr(motion, "list_templates", lambda: [{"id": "Hello", "style": "pixel"}])
    s = _settings(tts_provider="http", tts_http_url="http://127.0.0.1:1/tts",
                  media_root=str(tmp_path))
    idea = store.add_idea("motion")
    voiced = {"title": "Hi", "voice": {"lines": [], "audioSrc": "voice/x.wav"}}
    out = motion.queue_motion_render(store, s, template="Hello", props=voiced,
                                     idea_id=idea["id"], voice="old")  # no new voice-over
    assert out["asset"]["recipe"]["props"]["voice"]["audioSrc"] == "voice/x.wav"
    with pytest.raises(ValueError, match="not available"):  # a new voice-over: refused
        motion.queue_motion_render(store, s, template="Hello", props={"title": "Hi"},
                                   idea_id=idea["id"], voice="old")


def test_sitcom_cast_takes_voices_without_a_gender(store, folder):
    entries = [*ENTRIES, {"id": "n", "label": "N", "description": "no gender", "enabled": True,
                          "recipe": {"style": "x", "seed": 3}}]
    (folder / "voices.json").write_text(json.dumps({"voices": entries}), encoding="utf-8")
    assert voices.say_cast(store) == {"male": ("b", "n"), "female": ("a", "n")}
    voices.set_enabled(store, "a", False)
    voices.set_enabled(store, "b", False)
    assert voices.say_cast(store) == {"male": ("n", "n"), "female": ("n", "n")}  # never old ones


def test_two_quick_switches_never_turn_every_voice_off(store, folder, monkeypatch):
    slow = store.get_state

    def get_state(key):  # widen the read-check-write window
        value = slow(key)
        time.sleep(0.05)
        return value

    monkeypatch.setattr(store, "get_state", get_state)
    errors = []

    def off(v):
        try:
            voices.set_enabled(store, v, False)
        except ValueError as e:
            errors.append(str(e))

    threads = [threading.Thread(target=off, args=(v,)) for v in ("a", "b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(errors) == 1 and "at least one" in errors[0]
    assert len(voices.enabled_voices(store)) == 1


def test_a_sitcom_re_render_compares_with_the_default_narrator(store, folder, tmp_path,
                                                               monkeypatch):
    seen = {}
    monkeypatch.setattr(motion, "validate_props", lambda t, p: {
        "props": p, "fps": 30, "durationInFrames": 90, "coverFrame": 12})
    monkeypatch.setattr(motion, "list_templates", lambda: [{"id": sitcom.TEMPLATE, "style": "sitcom"}])
    monkeypatch.setattr(motion, "build_props",
                        lambda t, p, s, v=None, cast=None, *a: seen.update(voice=v, cast=cast) or p)
    s = _settings(tts_provider="http", tts_http_url="http://127.0.0.1:1/tts",
                  media_root=str(tmp_path))
    idea = store.add_idea("motion")
    motion.queue_motion_render(store, s, template=sitcom.TEMPLATE, idea_id=idea["id"],
                               props={"voice": {"lines": []}, "scenes": []})
    assert seen == {"voice": "a", "cast": {"male": ("b", "a"), "female": ("a", "b")}}
