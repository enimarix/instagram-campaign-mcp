"""Step 038: the VoxCPM2 voice service (vendor/voxcpm_tts) with the model and Whisper stubbed,
and its start/stop from `ig-campaign up`. No torch, no GPU, no network."""

import asyncio
import base64
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from src import scheduler
from src.config import InstagramMCPSettings
from src.studio import tts, tts_service
from src.studio.tts import WordTiming

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor" / "voxcpm_tts"
sys.path.insert(0, str(VENDOR))
import speech  # noqa: E402

_spec = importlib.util.spec_from_file_location("voxcpm_tts_server", VENDOR / "server.py")
server = sys.modules[_spec.name] = importlib.util.module_from_spec(_spec)  # pydantic needs it
_spec.loader.exec_module(server)


# --- speech normalisation --------------------------------------------------------------
@pytest.mark.parametrize("text, said", [
    ("Il vous reste 308 kcal.", "Il vous reste trois cent huit calories."),
    ("À 21 h, rien.", "À vingt et une heures, rien."),
    ("21h30", "vingt et une heures trente"),
    ("1 h et 1 kcal, 1 g", "une heure et une calorie, un gramme"),
    ("1 800 kcal", "mille huit cents calories"),
    ("1,5 kg ou 0,05 g", "un virgule cinq kilo ou zéro virgule zéro cinq gramme"),
    ("20 % de 2 l", "vingt pour cent de deux litres"),
    ("2 l'eau", "deux l'eau"),
    ("le 1er, la 1re, la 2e", "le premier, la première, la deuxième"),
    ("Sur macrobody.fr !", "Sur Macro Body point f r !"),
    ("MacroBody et macroBody", "Macro Body et Macro Body"),
    ("en 3 secondes", "en trois secondes"),
])
def test_speak_spells_out_what_is_read_as_digits(text, said):
    assert speech.speak(text) == said


def test_one_take_closes_each_line_as_a_sentence():
    assert speech.take_text(["vingt et une heures", "Une pizza ?", " ", "trop."]) == \
        "Vingt et une heures. Une pizza ? Trop."


def test_score_compares_normalised_words():
    meant = "Vingt-et-une heures… Il vous reste 308 kcal."
    assert speech.score(meant, meant) == 1.0
    heard = " 20 et une heures, il vous reste 308 calories."  # Whisper writes digits
    assert speech.score(meant, heard) == 1.0
    assert speech.score(meant, "Prop. Il nous reste des calories.") < 0.6


def test_line_spans_weigh_spelled_out_numbers_like_the_digits():
    lines = ["Il reste 308 kcal.", "Une pomme ?"]
    words = [{"text": t, "start_s": s, "end_s": e} for t, s, e in [
        ("Il", 0.0, 0.2), ("reste", 0.2, 0.5), ("trois", 0.5, 0.8), ("cent", 0.8, 1.0),
        ("huit", 1.0, 1.2), ("calories.", 1.2, 1.9), ("Une", 2.2, 2.4), ("pomme", 2.4, 2.9)]]
    spans = speech.line_spans(words, lines)
    assert spans == [{"text": lines[0], "start_s": 0.0, "end_s": 1.9},
                     {"text": lines[1], "start_s": 2.2, "end_s": 2.9}]
    # the studio maps these per-line spans back 1:1 (src/studio/tts.py)
    timings = tts.group_words_into_lines([WordTiming(**s) for s in spans], lines)
    assert [(t.start_s, t.end_s) for t in timings] == [(0.0, 1.9), (2.2, 2.9)]


def test_studio_grouping_alone_would_misplace_spelled_numbers():
    # why the service sends line spans: raw words in spoken form shift the line bounds
    lines = ["308 kcal, 1 800 kcal, 21 h", "Une pomme ou une pizza ce soir"]
    words = [WordTiming(w, i, i + 1) for i, w in enumerate(
        speech.speak(lines[0]).split() + lines[1].split())]
    grouped = tts.group_words_into_lines(words, lines)
    said = len(speech.speak(lines[0]).split())  # 12 words, the last ends at 12 s
    assert grouped[0].end_s < said  # line 1 cut short: its last words went to line 2


# --- voices -----------------------------------------------------------------------------
def test_brand_voices_load_with_one_default():
    voices = server.load_voices()
    assert sorted(voices) == ["coach_energique", "conteur_grave", "douce_nuit"]
    assert [v.id for v in voices.values() if v.default] == ["conteur_grave"]
    assert all(v.card.is_file() and v.card_text and v.address for v in voices.values())


def _voices_dir(tmp_path, entries, cards=("a",)):
    (tmp_path / "voices.json").write_text(json.dumps({"voices": entries}), encoding="utf-8")
    for c in cards:
        (tmp_path / f"{c}.wav").write_bytes(b"RIFF")
    return tmp_path


def test_voices_need_their_card_and_exactly_one_default(tmp_path):
    entry = {"id": "a", "label": "A", "description": "d", "card_text": "t", "default": True}
    with pytest.raises(ValueError, match="missing"):
        server.load_voices(_voices_dir(tmp_path, [entry, {**entry, "id": "b"}]))
    with pytest.raises(ValueError, match="default"):
        server.load_voices(_voices_dir(tmp_path, [{**entry, "default": False}]))


# --- takes and the HTTP shape -----------------------------------------------------------
class FakeEngine:
    """Says `heard[n]` on take n; audio bytes name the take."""

    def __init__(self, heard):
        self.heard, self.texts, self.model = list(heard), [], object()

    def take(self, text, voice):
        self.texts.append((text, voice.id))
        n = len(self.texts)
        said = self.heard[n - 1].split()
        words = [{"text": w, "start_s": i * 0.5, "end_s": i * 0.5 + 0.4}
                 for i, w in enumerate(said)]
        return f"take{n}".encode(), len(said) * 0.5, words

    def vram_gb(self):
        return None


GOOD = "Il reste trois cent huit calories. Une pomme ?"
SCRIPT = "Il reste 308 kcal\nUne pomme ?"


def _decoded(out):
    return base64.b64decode(out["audio"]).decode()


def test_a_good_first_take_is_kept():
    engine = FakeEngine([GOOD])
    voice = server.load_voices()["douce_nuit"]
    out = server.synthesize(engine, server.Settings(), SCRIPT, voice)
    assert engine.texts == [("Il reste trois cent huit calories. Une pomme ?", "douce_nuit")]
    assert _decoded(out) == "take1" and out["take"]["scores"] == [1.0]
    assert [w["text"] for w in out["words"]] == ["Il reste 308 kcal", "Une pomme ?"]


def test_bad_takes_are_redone_and_the_best_is_kept():
    voice = server.load_voices()["conteur_grave"]
    engine = FakeEngine(["Il reste des calories. Une pomme", "Prop", "Il reste des calories"])
    out = server.synthesize(engine, server.Settings(max_takes=3), SCRIPT, voice)
    assert len(engine.texts) == 3 and _decoded(out) == "take1"
    assert out["take"]["score"] == max(out["take"]["scores"]) < 0.9
    engine = FakeEngine(["Prop", GOOD, GOOD])
    out = server.synthesize(engine, server.Settings(max_takes=3), SCRIPT, voice)
    assert len(engine.texts) == 2 and _decoded(out) == "take2"  # stops once good


def test_settings_from_env_keep_the_approved_defaults(monkeypatch):
    for k in ("VOXCPM_STEPS", "VOXCPM_CFG", "VOXCPM_MAX_TAKES", "VOXCPM_MIN_SCORE"):
        monkeypatch.delenv(k, raising=False)
    assert server.Settings.from_env().model_dump() == {
        "steps": 30, "cfg": 1.6, "max_takes": 3, "min_score": 0.9}
    monkeypatch.setenv("VOXCPM_MAX_TAKES", "0")
    assert server.Settings.from_env().max_takes == 1


def test_http_shape_default_voice_and_errors():
    engine = FakeEngine([GOOD] * 3)
    app = server.create_app(engine, server.Settings(), server.load_voices())
    http = TestClient(app)
    health = http.get("/health").json()
    assert health["loaded"] and health["default_voice"] == "conteur_grave"
    assert health["voices"] == ["coach_energique", "conteur_grave", "douce_nuit"]
    body = http.post("/tts", json={"text": SCRIPT, "voice": ""}).json()
    assert set(body) == {"audio", "words", "take"} and body["take"]["voice"] == "conteur_grave"
    assert all(set(w) == {"text", "start_s", "end_s"} for w in body["words"])
    r = http.post("/tts", json={"text": SCRIPT, "voice": "robot"})
    assert r.status_code == 400 and "conteur_grave" in r.json()["detail"]
    assert http.post("/tts", json={"text": " \n "}).status_code == 400


def test_the_studio_http_provider_reads_the_service_answer(tmp_path, monkeypatch):
    engine = FakeEngine([GOOD])
    http = TestClient(server.create_app(engine, server.Settings(), server.load_voices()))
    answer = http.post("/tts", json={"text": SCRIPT, "voice": "douce_nuit"}).json()
    monkeypatch.setattr(tts.ffmpeg, "probe",
                        lambda p, **_: tts.ffmpeg.MediaInfo(1.9, None, None, None, None, True,
                                                            "pcm", 48000, 10))
    s = InstagramMCPSettings(_env_file=None, tts_provider="http", tts_http_response="json",
                             tts_http_url="http://127.0.0.1:8766/tts", tts_cache_dir=str(tmp_path))
    with respx.mock:
        respx.post("http://127.0.0.1:8766/tts").respond(json=answer)
        syn = tts.get_provider(s).synthesize(SCRIPT, "douce_nuit")
    assert [(t.text, t.start_s, t.end_s) for t in syn.lines] == [
        ("Il reste 308 kcal", 0.0, 2.9), ("Une pomme ?", 3.0, 4.4)]


# --- started by `ig-campaign up` ------------------------------------------------------
def _cfg(**kw):
    kw = {"tts_provider": "http", "tts_http_url": "http://127.0.0.1:8766/tts",
          "tts_server_python": "py.exe", "tts_server_hf_home": "D:/hf", **kw}
    return InstagramMCPSettings(_env_file=None, **kw)


def test_spawn_runs_the_server_on_the_url_port_with_hf_home(tmp_path):
    seen = {}

    def popen(cmd, **kw):
        seen.update(cmd=cmd, **kw)
        return "proc"

    assert tts_service.spawn(_cfg(), tmp_path / "tts.log", popen=popen) == "proc"
    assert seen["cmd"] == ["py.exe", str(VENDOR / "server.py"), "--host", "127.0.0.1",
                           "--port", "8766", "--exit-with-stdin"]
    assert seen["env"]["HF_HOME"] == "D:/hf" and seen["stdin"] == subprocess.PIPE
    with pytest.raises(ValueError, match="port"):
        tts_service.command(_cfg(tts_http_url="http://127.0.0.1/tts"))
    assert tts_service.health_url(_cfg()) == "http://127.0.0.1:8766/health"


class Proc:
    def __init__(self, code=None):
        self.code = code

    def poll(self):
        return self.code


async def test_wait_ready_until_health_answers_or_the_child_dies():
    with respx.mock:
        route = respx.get("http://127.0.0.1:8766/health")
        route.side_effect = [httpx.ConnectError("down"), httpx.Response(200, json={})]
        assert await tts_service.wait_ready(_cfg(), Proc(), poll_s=0)
        assert route.call_count == 2
    assert not await tts_service.wait_ready(_cfg(), Proc(code=1), poll_s=0)


async def test_up_starts_the_voice_before_the_worker_and_stops_it(monkeypatch):
    events = []

    class Server:
        def __init__(self, config):
            pass

        async def serve(self):  # let the worker task run before uvicorn "stops"
            for _ in range(3):
                await asyncio.sleep(0)
            events.append("serve")

    async def worker(settings):
        events.append("worker")

    async def ready(settings, proc):
        events.append("ready")
        return True

    import uvicorn
    monkeypatch.setattr(uvicorn, "Server", Server)
    monkeypatch.setattr(scheduler, "get_settings", lambda: _cfg())
    monkeypatch.setattr("src.api.app.create_app", lambda s: None)
    monkeypatch.setattr(scheduler, "_worker", worker)
    monkeypatch.setattr(tts_service, "spawn", lambda s: events.append("spawn") or "proc")
    monkeypatch.setattr(tts_service, "wait_ready", ready)
    monkeypatch.setattr(scheduler.downloader_service, "stop", lambda p: events.append(("stop", p)))
    await scheduler._up("127.0.0.1", 0)
    assert events == ["spawn", "ready", "worker", "serve", ("stop", "proc")]


def test_no_voice_service_without_tts_server_python():
    assert scheduler._start_voice(_cfg(tts_server_python=None)) is None


def test_only_the_small_cards_are_committed():
    sizes = [p.stat().st_size for p in (ROOT / "brand" / "voices").glob("*.wav")]
    assert len(sizes) == 3 and max(sizes) < 1_000_000
