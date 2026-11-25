"""Step 204: ElevenLabs first, the local voice as the other engine (respx for both, ffmpeg
probe stubbed), audio tags heard by ElevenLabs only, the cards and the Voix page routes."""

import base64
import json

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from src.agent import film_voice
from src.api.app import create_app
from src.config import InstagramMCPSettings
from src.studio import elevenlabs, ffmpeg, motion, render, sitcom, tts, voices

from .conftest import LOCAL

EL = "https://api.elevenlabs.io"
LOCAL_TTS = "http://127.0.0.1:5002/tts"
KEY = "sk_test_key"
LOCAL_VOICES = [
    {"id": "souriante", "label": "Souriante", "gender": "female", "address": ["tu", "vous"],
     "styles": ["paper", "pixel"], "enabled": True, "default": True},
    {"id": "energique_homme", "label": "Énergique (homme)", "gender": "male",
     "address": ["tu"], "styles": ["pixel"], "enabled": True},
]


def _settings(tmp_path, **kw):
    kw = {"tts_provider": "http", "tts_http_url": LOCAL_TTS, "tts_cache_dir": str(tmp_path / "c"),
          "elevenlabs_api_key": KEY, "database_path": ":memory:", **kw}
    return InstagramMCPSettings(_env_file=None, instagram_access_token=None, **kw)


@pytest.fixture(autouse=True)
def folder(tmp_path, monkeypatch):
    d = tmp_path / "brand"
    d.mkdir()
    (d / "voices.json").write_text(json.dumps({"voices": LOCAL_VOICES}), encoding="utf-8")
    monkeypatch.setattr(voices, "VOICES_DIR", d)
    monkeypatch.setattr(tts.ffmpeg, "probe", lambda path, **_: ffmpeg.MediaInfo(
        2.0, None, None, None, None, True, "mp3", 44100, 10))
    return d


@pytest.fixture
def card():
    return voices.add_el_card(el_voice_id="abc123", label="Liam FR", fallback="energique_homme",
                              use_for="Énergie, astuces", language="fr")


def _alignment(text):
    chars = list(text)
    return {"characters": chars,
            "character_start_times_seconds": [i * 0.05 for i in range(len(chars))],
            "character_end_times_seconds": [i * 0.05 + 0.05 for i in range(len(chars))]}


def _el_routes(left=10_000, tts_status=200):
    respx.get(f"{EL}/v1/user/subscription").respond(json={
        "character_count": 10_000 - left, "character_limit": 10_000,
        "next_character_count_reset_unix": 1796005036, "tier": "free"})

    def speak(request):
        if tts_status != 200:
            return httpx.Response(tts_status, json={"detail": {"status": "quota_exceeded",
                                                               "message": "quota exceeded"}})
        text = json.loads(request.content)["text"]
        return httpx.Response(200, json={"audio_base64": base64.b64encode(b"ID3mp3").decode(),
                                         "alignment": _alignment(text)})

    return respx.post(url__regex=rf"{EL}/v1/text-to-speech/abc123/with-timestamps.*").mock(
        side_effect=speak)


def _local_route():
    return respx.post(LOCAL_TTS).respond(200, content=b"RIFFlocal",
                                         headers={"content-type": "audio/wav"})


def test_tags_are_stripped_and_put_back_line_by_line():
    assert tts.strip_tags("[excited] Arrête  de compter [short pause] tes pas.") == \
        "Arrête de compter tes pas."
    assert tts.strip_tags("Note [1] reste.") == "Note [1] reste."  # not a tag
    spoken = ["[curious] Pourquoi ?", "[laughs] Parce que."]
    assert tts.retag(["Pourquoi ?", "Parce que."], spoken) == spoken
    assert tts.retag(["Pourquoi ?", "Autre ligne."], spoken) == ["[curious] Pourquoi ?",
                                                                 "Autre ligne."]


def test_alignment_words_skip_the_tags():
    words = tts.alignment_words(_alignment("[excited] Salut toi"))
    assert [w.text for w in words] == ["Salut", "toi"]
    assert words[0].start_s == pytest.approx(10 * 0.05)


@respx.mock
def test_elevenlabs_speaks_first_and_hears_the_tags(tmp_path, card):
    route = _el_routes()
    synth = tts.get_provider(_settings(tmp_path)).synthesize(
        "[excited] Arrête de compter tes pas.\n[laughs] Sérieux.", "energique_homme")
    sent = route.calls.last.request
    assert sent.headers["xi-api-key"] == KEY
    body = json.loads(sent.content)
    assert body == {"text": "[excited] Arrête de compter tes pas.\n[laughs] Sérieux.",
                    "model_id": "eleven_v4"}  # no language_code: the script's own language
    assert synth.provider == "elevenlabs" and synth.voice == card["id"]
    assert synth.fallback is None and synth.audio_path.suffix == ".mp3"
    assert [t.text for t in synth.lines] == ["Arrête de compter tes pas.", "Sérieux."]


@respx.mock
def test_no_credits_falls_back_to_the_paired_local_voice_without_spending(tmp_path, card):
    tts_route = _el_routes(left=5)
    local = _local_route()
    synth = tts.get_provider(_settings(tmp_path)).synthesize("[sighs] Encore lundi.", card["id"])
    assert not tts_route.called  # too few credits: nothing spent
    assert json.loads(local.calls.last.request.content) == {"text": "Encore lundi.",
                                                            "voice": "energique_homme"}
    assert synth.provider == "http" and synth.voice == "energique_homme"
    assert "credits" in synth.fallback


@respx.mock
def test_an_elevenlabs_error_falls_back_and_stays_skipped(tmp_path, card):
    _el_routes(tts_status=401)
    local = _local_route()
    provider = tts.get_provider(_settings(tmp_path))
    first = provider.synthesize("Un.", card["id"])
    assert first.provider == "http" and "quota exceeded" in first.fallback
    provider.synthesize("Deux.", card["id"])  # same video: ElevenLabs is not tried again
    assert respx.calls.call_count == 2 + 2  # subscription + tts once, then two local calls
    assert local.call_count == 2


@respx.mock
def test_local_first_when_the_owner_says_so(tmp_path, card):
    voices.set_engine(priority="local")
    route = _el_routes()
    local = _local_route()
    synth = tts.get_provider(_settings(tmp_path)).synthesize("Salut.", card["id"])
    assert synth.provider == "http" and local.called and not route.called
    respx.post(LOCAL_TTS).respond(503)  # the local service is down: ElevenLabs takes over
    synth = tts.get_provider(_settings(tmp_path)).synthesize("Autre.", "energique_homme")
    assert synth.provider == "elevenlabs" and synth.voice == card["id"]


@respx.mock
def test_both_engines_down_raise_a_machine_error(tmp_path, card):
    respx.get(f"{EL}/v1/user/subscription").mock(side_effect=httpx.ConnectError("down"))
    respx.post(url__regex=rf"{EL}/v1/text-to-speech/.*").mock(
        side_effect=httpx.ConnectError("down"))
    respx.post(LOCAL_TTS).respond(503)
    with pytest.raises(tts.TTSError) as e:
        tts.get_provider(_settings(tmp_path)).synthesize("Salut.", card["id"])
    assert e.value.machine


def test_engine_plan_pairs_the_voices(card):
    assert voices.engine_plan(card["id"]) == [("elevenlabs", card["id"]),
                                              ("local", "energique_homme")]
    assert voices.engine_plan("energique_homme") == [("elevenlabs", card["id"]),
                                                     ("local", "energique_homme")]
    assert voices.engine_plan("souriante") == [("local", "souriante")]  # no pair
    voices.set_engine(priority="local", model="eleven_flash_v2_5")
    assert voices.engine() == {"priority": "local", "model": "eleven_flash_v2_5"}
    assert voices.engine_plan(card["id"])[0] == ("local", "energique_homme")
    with pytest.raises(ValueError):
        voices.set_engine(priority="cloud")


def test_cards_list_and_reach_the_agent_without_internals(store, card, tmp_path):
    by = {v["id"]: v for v in voices.list_voices(store)}
    el = by[card["id"]]
    assert el["engine"] == "elevenlabs" and el["gender"] == "male" and el["enabled"]
    assert el["fallback"] == "energique_homme" and by["souriante"]["engine"] == "local"
    assert voices.check_voice(store, card["id"]) == card["id"]
    voices.agent_copy(store, tmp_path / "v.json")
    copied = {v["id"]: v for v in json.loads((tmp_path / "v.json").read_text("utf-8"))["voices"]}
    assert copied[card["id"]]["engine"] == "elevenlabs"
    assert "el_voice_id" not in copied[card["id"]] and "fallback" not in copied[card["id"]]
    with pytest.raises(ValueError, match="fallback"):
        voices.add_el_card(el_voice_id="x", label="X", fallback="nope")
    assert voices.add_el_card(el_voice_id="y", label="Liam FR", fallback="souriante")["id"] \
        == "el_liam_fr_2"
    voices.remove_el_card(store, "el_liam_fr_2")
    with pytest.raises(KeyError):
        voices.remove_el_card(store, "souriante")  # never a local voice


def test_motion_props_lose_their_tags_but_the_voice_keeps_them(tmp_path):
    props = {"hook": "[excited] Arrête de compter tes pas", "facts": [{"text": "Dix mille."}],
             "outro": "[warmly] À demain."}
    tagged = motion.tagged_lines("FactQuest", props)
    assert tagged == {"spoken": ["[excited] Arrête de compter tes pas", "Dix mille.",
                                 "[warmly] À demain."]}
    plain = motion.strip_props(props, motion.raw_lines("FactQuest", props)[0])
    assert plain["hook"] == "Arrête de compter tes pas" and plain["outro"] == "À demain."
    heard = []

    class Fake:
        def synthesize(self, text, voice=None):
            heard.append(text)
            return tts.NoneProvider().synthesize(text)

    report = []
    real = motion.get_provider
    motion.get_provider = lambda s: Fake()
    try:
        out = motion.build_props("FactQuest", plain, _settings(tmp_path), "souriante",
                                 spoken=tagged["spoken"], report=report)
    finally:
        motion.get_provider = real
    assert heard == ["\n".join(tagged["spoken"])]
    assert [line["text"] for line in out["voice"]["lines"]] == [
        "Arrête de compter tes pas", "Dix mille.", "À demain."]
    assert len(report) == 1 and motion.voiced_by(report) is None  # no audio: no badge


def test_voice_todo_takes_the_tagged_lines_and_the_badge():
    render.VoiceTodo(voice="a", spoken=["[laughs] x"], spoken_says=["y"])
    assert motion.voiced_by([tts.Synthesis(ffmpeg.Path("a.mp3"), 1.0, [], None, "http",
                                           "souriante", "ElevenLabs credits: 0 left")]) == {
        "engine": "http", "voice": "souriante", "fallback": "ElevenLabs credits: 0 left"}


@respx.mock
def test_voix_page_routes(store, tmp_path):
    _el_routes(left=1234)
    respx.get(f"{EL}/v1/models").respond(json=[
        {"model_id": "eleven_v4", "name": "Eleven v4", "can_do_text_to_speech": True,
         "languages": [{"language_id": "fr"}], "model_rates": {"character_cost_multiplier": 1}},
        {"model_id": "eleven_sts", "can_do_text_to_speech": False}])
    library = respx.get(f"{EL}/v1/shared-voices").respond(json={
        "voices": [{"public_owner_id": "own1", "voice_id": "lib1", "name": "Hugo",
                    "gender": "male", "language": "fr", "accent": "parisian",
                    "preview_url": "https://x/p.mp3", "free_users_allowed": True}],
        "has_more": True, "total_count": 40})
    add = respx.post(f"{EL}/v1/voices/add/own1/lib1").respond(json={"voice_id": "acc9"})
    s = _settings(tmp_path)
    with TestClient(create_app(s, store=store), base_url=LOCAL) as tc:
        eng = tc.get("/api/voices/engine").json()
        assert eng["priority"] == "elevenlabs" and eng["model"] == "eleven_v4" and eng["local"]
        assert eng["elevenlabs"]["credits"]["left"] == 1234
        assert tc.patch("/api/voices/engine", json={"priority": "local"}).json()["priority"] \
            == "local"
        assert tc.patch("/api/voices/engine", json={"priority": "x"}).status_code == 422
        assert [m["id"] for m in tc.get("/api/voices/elevenlabs/models").json()] == ["eleven_v4"]
        page = tc.get("/api/voices/elevenlabs/search", params={
            "language": "fr", "gender": "male", "use_cases": ["social_media"]}).json()
        assert page["next"] == "1" and page["voices"][0]["accent"] == "parisian"
        q = library.calls.last.request.url.params
        assert q["language"] == "fr" and q["use_cases"] == "social_media" and q["page"] == "0"
        made = tc.post("/api/voices/elevenlabs", json={
            "voice_id": "lib1", "public_owner_id": "own1", "label": "Hugo",
            "fallback": "energique_homme", "gender": "male"}).json()
        assert json.loads(add.calls.last.request.content) == {"new_name": "Hugo"}
        assert voices.el_card(made["id"])["el_voice_id"] == "acc9"
        assert tc.post("/api/voices/elevenlabs", json={
            "voice_id": "lib1", "public_owner_id": "own1", "label": "Hugo",
            "fallback": "nope"}).status_code == 422
        assert add.call_count == 1  # a bad card never spends a voice slot
        assert tc.delete(f"/api/voices/{made['id']}").json()["removed"] is True
        assert tc.delete("/api/voices/souriante").status_code == 404
    respx.get(f"{EL}/v1/shared-voices").respond(401, json={"detail": {"message": "bad key"}})
    with TestClient(create_app(s, store=store), base_url=LOCAL) as tc:
        r = tc.get("/api/voices/elevenlabs/search")
        assert r.status_code == 502 and "bad key" in r.json()["message"]
        assert KEY not in r.text


def test_ids_never_build_another_url(tmp_path):
    with pytest.raises(ValueError):
        elevenlabs.speech(_settings(tmp_path), "../v1/user", "x", "eleven_v4")


# --- audit fixes (204) ------------------------------------------------------------------------
def test_a_tag_never_changes_how_strips_join():
    for tagged, plain in ((["Tu manges trop", "[surprised] Arrête"], ["Tu manges trop", "Arrête"]),
                          (["Fini. [laughs]", "Suite"], ["Fini.", "Suite"])):
        assert tts.strip_tags(motion._paper_line(tagged)) == motion._paper_line(plain)
    assert tts.strip_tags(motion._editorial_line("Ton assiette", "[warmly] Voilà")) ==         motion._editorial_line("Ton assiette", "Voilà") == "Ton assiette. Voilà"


def test_retag_matches_by_text_so_an_added_line_keeps_the_others():
    assert tts.retag(["a", "b", "c"], ["[x] a", "[y] c"]) == ["[x] a", "b", "[y] c"]
    assert tts.retag(["a", "a"], ["[x] a", "[y] a"]) == ["[x] a", "[y] a"]


def test_alignment_keeps_brackets_with_digits():
    assert [w.text for w in tts.alignment_words(_alignment("Étape [1] : [excited] mange"))] == [
        "Étape", "[1]", ":", "mange"]
    assert tts.alignment_words({"characters": ["ab"], "character_start_times_seconds": [0],
                                "character_end_times_seconds": [1]}) is None


@respx.mock
def test_a_key_that_cannot_read_credits_still_speaks(tmp_path, card):
    route = _el_routes()
    respx.get(f"{EL}/v1/user/subscription").respond(401, json={"detail": {"message": "no perm"}})
    synth = tts.get_provider(_settings(tmp_path)).synthesize("Salut.", card["id"])
    assert route.called and synth.provider == "elevenlabs" and synth.fallback is None


@respx.mock
def test_no_credits_with_the_local_voice_down_waits_for_the_machine(tmp_path, card):
    voices.set_engine(priority="local")
    _el_routes(left=0)
    respx.post(LOCAL_TTS).respond(503)
    with pytest.raises(tts.TTSError) as e:
        tts.get_provider(_settings(tmp_path)).synthesize("Salut.", card["id"])
    assert e.value.machine and "credits" in str(e.value)


def test_a_card_turned_off_is_no_twin_and_a_removed_one_speaks_locally(store, card):
    voices.set_enabled(store, card["id"], False)
    assert voices.engine_plan("energique_homme") == [("local", "energique_homme")]
    voices.set_enabled(store, card["id"], True)
    assert voices.engine_plan("energique_homme")[0] == ("elevenlabs", card["id"])
    voices.remove_el_card(store, card["id"])
    assert voices.engine_plan(card["id"]) == [("local", None)]  # the default local voice


def test_no_local_service_gives_captions_for_an_unpaired_voice(tmp_path, card):
    synth = tts.get_provider(_settings(tmp_path, tts_provider="none")).synthesize(
        "[warmly] Bonsoir.", "souriante")
    assert synth.audio_path is None and [t.text for t in synth.lines] == ["Bonsoir."]


@respx.mock
def test_a_library_voice_already_in_the_account_becomes_a_card(tmp_path):
    respx.post(f"{EL}/v1/voices/add/own1/lib1").respond(400, json={"detail": {
        "message": "voice already added"}})
    respx.get(f"{EL}/v2/voices").respond(json={"voices": [
        {"voice_id": "acc9", "name": "Hugo", "labels": {}}], "has_more": False})
    made = voices.add_from_elevenlabs(_settings(tmp_path), voice_id="lib1", public_owner_id="own1",
                                      label="Hugo", fallback="energique_homme")
    assert voices.el_card(made["id"])["el_voice_id"] == "acc9"
    respx.post(f"{EL}/v1/voices/add/own2/lib2").respond(400, json={"detail": {"message": "nope"}})
    with pytest.raises(elevenlabs.ElevenLabsError):
        voices.add_from_elevenlabs(_settings(tmp_path), voice_id="lib2", public_owner_id="own2",
                                   label="Zoé", fallback="souriante")


# --- second audit fixes (204) -----------------------------------------------------------------
@respx.mock
def test_elevenlabs_hears_numbers_and_units_spelled_out(tmp_path, card):
    route = _el_routes()
    synth = tts.get_provider(_settings(tmp_path)).synthesize(
        "[excited] 308 kcal avant 21 h\nVa sur macrobody.fr (rires)", card["id"])
    assert json.loads(route.calls.last.request.content)["text"] == (
        "[excited] trois cent huit calories avant vingt et une heures\n"
        "Va sur Macro Body point f r")
    assert [t.text for t in synth.lines] == ["308 kcal avant 21 h",
                                             "Va sur macrobody.fr (rires)"]  # as written
    first, second = synth.lines  # ElevenLabs' own line timings, one span per line
    assert first.end_s <= second.start_s


@respx.mock
def test_a_model_without_tags_never_hears_them(tmp_path, card):
    voices.set_engine(model="eleven_flash_v2_5")
    route = _el_routes()
    tts.get_provider(_settings(tmp_path)).synthesize("[excited] Salut [laughs] toi.", card["id"])
    assert json.loads(route.calls.last.request.content)["text"] == "Salut toi."
    assert tts.hears_tags("eleven_v4") and tts.hears_tags("eleven_v3_conversational")
    assert not tts.hears_tags("eleven_multilingual_v2")


def test_alignment_lines_one_span_per_line_that_speaks():
    spans = tts.alignment_lines(_alignment("[x] Un\n[laughs]\nDeux"))
    assert len(spans) == 2 and spans[0][1] < spans[1][0]


def test_films_get_the_elevenlabs_cards_too(store, card, tmp_path):
    voices.agent_copy(store, tmp_path / "v.json")  # 207: films speak through the voice door
    listed = json.loads((tmp_path / "v.json").read_text("utf-8"))["voices"]
    assert card["id"] in [v["id"] for v in listed]
    assert not any(k in v for v in listed for k in ("el_voice_id", "fallback", "recipe"))
    assert sum(v.get("default", False) for v in listed) == 1


def _door(tmp_path, monkeypatch):
    monkeypatch.setattr(film_voice, "_wav", lambda path: b"RIFFwav")
    door = film_voice.VoiceDoor(_settings(tmp_path))
    door.server.server_close()  # answer() is tested without a socket
    return door


def _say(door, voice, text="[excited] Salut toi."):
    return door.answer(f"/{door.token}", json.dumps({"text": text, "voice": voice}).encode())


@respx.mock
def test_the_film_voice_door_speaks_elevenlabs_first(tmp_path, card, monkeypatch):
    _el_routes()
    door = _door(tmp_path, monkeypatch)
    code, out = _say(door, "energique_homme")  # a local voice speaks through its card
    assert code == 200 and base64.b64decode(out["audio"]) == b"RIFFwav" and out["words"]
    assert out["take"]["engine"] == "elevenlabs" and out["take"]["voice"] == card["id"]
    assert out["take"]["fallback"] is None
    assert door.answer("/not-the-token", b"{}")[0] == 404
    assert door.answer(f"/{door.token}", b"not json")[0] == 400
    assert door.answer(f"/{door.token}", b'{"text": " "}')[0] == 400


@respx.mock
def test_the_film_voice_door_falls_back_to_the_local_voice(tmp_path, card, monkeypatch):
    _el_routes(tts_status=500)
    local = _local_route()
    code, out = _say(_door(tmp_path, monkeypatch), card["id"])
    assert code == 200 and out["take"]["engine"] == "local"
    assert out["take"]["voice"] == "energique_homme" and out["take"]["fallback"]
    assert "[excited]" not in json.loads(local.calls.last.request.content)["text"]


@respx.mock
def test_the_film_voice_door_says_503_when_no_engine_speaks(tmp_path, card, monkeypatch):
    _el_routes(tts_status=500)
    respx.post(LOCAL_TTS).respond(503)
    code, out = _say(_door(tmp_path, monkeypatch), card["id"])
    assert code == 503 and out["error"]


@respx.mock
def test_without_a_key_a_card_speaks_in_its_local_relay(tmp_path, card):
    local = _local_route()
    synth = tts.get_provider(_settings(tmp_path, elevenlabs_api_key=None)).synthesize(
        "Salut.", card["id"])
    assert json.loads(local.calls.last.request.content)["voice"] == "energique_homme"
    assert synth.provider == "http" and "elevenlabs is not set up" in synth.fallback


def test_a_card_added_again_starts_on(store, card):
    voices.set_enabled(store, card["id"], False)
    voices.remove_el_card(store, card["id"])
    again = voices.add_el_card(el_voice_id="abc123", label="Liam FR", fallback="energique_homme")
    assert again["id"] == card["id"]
    assert {v["id"]: v["enabled"] for v in voices.list_voices(store)}[card["id"]] is True
    assert voices.engine_plan("energique_homme")[0] == ("elevenlabs", card["id"])


def test_only_spoken_strings_lose_their_tags():
    props = {"hook": "[excited] Salut", "citations": [{"title": "[PDF] Rapport ANSES"}]}
    out = motion.strip_props(props, ["[excited] Salut, ça va"])
    assert out == {"hook": "Salut", "citations": [{"title": "[PDF] Rapport ANSES"}]}


def test_the_card_file_is_written_again_when_windows_holds_it(monkeypatch):
    real, calls = voices.os.replace, []

    def flaky(a, b):
        calls.append(a)
        if len(calls) == 1:
            raise PermissionError("in use")
        real(a, b)

    monkeypatch.setattr(voices.os, "replace", flaky)
    voices.set_engine(priority="local")
    assert len(calls) == 2 and voices.engine()["priority"] == "local"


# --- third audit fixes (204) ------------------------------------------------------------------
@respx.mock
def test_a_cache_hit_keeps_this_scripts_own_line_text(tmp_path, card):
    route = _el_routes()
    provider = tts.get_provider(_settings(tmp_path))
    provider.synthesize("Rendez-vous à 21h.", card["id"])
    again = tts.get_provider(_settings(tmp_path)).synthesize("Rendez-vous à 21 h.", card["id"])
    assert route.call_count == 1  # same words said: one recording
    assert [t.text for t in again.lines] == ["Rendez-vous à 21 h."]


def test_elevenlabs_first_casts_the_cards_and_never_leaves_a_local_pick_on_voxcpm(
        store, card, tmp_path):
    # the owner's bug (2026-11-25): the default « souriante » has no card of its own, so with
    # ElevenLabs first it still spoke VoxCPM; a sitcom dad got the narrator's own card
    her = voices.add_el_card(el_voice_id="xyz789", label="Koraly", fallback="energique_homme",
                            gender="female")
    assert voices.engine_plan("souriante")[0] == ("elevenlabs", her["id"])  # her gender's card
    assert voices.engine_plan(None)[0] == ("elevenlabs", card["id"])  # no voice: a card too
    assert {v["id"] for v in voices.cast_voices(store)} == {card["id"], her["id"]}
    assert voices.default_voice(store) == her["id"]  # the default's gender, as a card
    voices.agent_copy(store, tmp_path / "v.json")
    listed = json.loads((tmp_path / "v.json").read_text(encoding="utf-8"))["voices"]
    assert {v["id"] for v in listed} == {card["id"], her["id"]}  # the film picks a card
    cast = voices.say_cast(store)
    assert sitcom.say_voice("dad", card["id"], cast) != card["id"]  # never the narrator's
    voices.set_engine(priority="local")  # local first: the local voices, as before
    assert voices.engine_plan("souriante") == [("local", "souriante")]
    assert voices.default_voice(store) == "souriante"


def test_a_cast_queued_with_local_ids_never_doubles_the_narrator(card):
    # 089: cast {male: (energique_homme, ...)} queued before the fix, narrator the card
    cast = {"male": ("energique_homme", "souriante"), "female": ("souriante", "energique_homme")}
    assert sitcom.say_voice("dad", card["id"], cast) == "souriante"  # not Liam twice
