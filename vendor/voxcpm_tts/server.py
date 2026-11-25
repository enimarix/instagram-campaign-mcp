"""
VoxCPM2 voice service for the studio (step 038, docs/DECISIONS.md 2026-11-19): a local
HTTP service the studio's `http` TTS provider calls (TTS_HTTP_RESPONSE=json).

  POST /tts {"text": "<one script line per line>", "voice": "<id>"}
       -> {"audio": <base64 wav>, "words": [{"text", "start_s", "end_s"}, ...], "take": {...}}
       `words` holds one span per script line, its text as written (speech.line_spans).
  GET  /health -> {"model", "loaded", "worker_pid", "voices", "default_voice", "settings",
       "recipes"} (settings: steps / cfg are the cloned voices'; a designed voice uses its recipe)
       (at once)

The owner's approved settings (by ear): the whole script in ONE take. A designed voice
(`recipe` in voices.json, casting of 2026-11-22) is made from its style + seed at its cfg and
steps, then its tempo; a cloned voice (no recipe) at cfg 1.6, 30 steps, from the voice card
as continuation (prompt wav + text) AND reference. Each take is
transcribed by Whisper (CPU, so VRAM stays under 8 GB with VoxCPM2 loaded) and compared to
the text; under VOXCPM_MIN_SCORE the take is redone, up to VOXCPM_MAX_TAKES, and the best
take is kept. One request at a time; one whose client is gone (the studio's timeout) is
dropped before the model load and before the takes.

The GPU is shared (step 145): the models load on the first request, under the machine's GPU
lock (src/studio/gpu_lock.py, the one Blender and Remotion renders take), and the lock is held
while they are loaded; the load also waits for free RAM / VRAM and no game (guard.admit, step
166), and everything runs at low priority. The models live in a worker process
(engine_worker.py, step 146): after VOXCPM_IDLE_UNLOAD_S without a request (default 120 s)
it is terminated, so the OS takes back all its VRAM and RAM, and the lock released, so a
render can run. A worker that dies or fails = HTTP 503, the lock released, and the next
request starts a new one. A load costs ~35 s. This process imports no torch (~60 MB), and
CI imports it without torch.

Run: python vendor/voxcpm_tts/server.py [--host 127.0.0.1] [--port 8766] (README.md).
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import functools
import importlib.util
import json
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from anyio import from_thread
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from engine_worker import MODEL_ID, WHISPER_ID, Engine, Worker, WorkerFailed
from speech import line_spans, score, speak, take_text

log = logging.getLogger("voxcpm_tts")

REPO = Path(__file__).resolve().parents[2]
# The studio's lock, by path: this service runs in its own venv, without the studio package.
_spec = importlib.util.spec_from_file_location("gpu_lock", REPO / "src" / "studio" / "gpu_lock.py")
gpu_lock = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gpu_lock)

VOICES_DIR = REPO / "brand" / "voices"


class Settings(BaseModel):
    """steps / cfg: the cloned voices' (a designed voice takes its recipe's); the rest: all."""
    steps: int = 30
    cfg: float = 1.6
    max_takes: int = 3
    min_score: float = 0.9
    idle_unload_s: float = 120.0

    @classmethod
    def from_env(cls) -> "Settings":
        env = os.environ.get
        return cls(steps=int(env("VOXCPM_STEPS", 30)), cfg=float(env("VOXCPM_CFG", 1.6)),
                   max_takes=max(1, int(env("VOXCPM_MAX_TAKES", 3))),
                   min_score=float(env("VOXCPM_MIN_SCORE", 0.9)),
                   idle_unload_s=float(env("VOXCPM_IDLE_UNLOAD_S", 120)))


class Recipe(BaseModel):
    """A designed voice (owner's casting, 2026-11-22): VoxCPM2 voice design, `(style)` before
    the text, no prompt continuation (cloning a take lost its energy). Take n uses seed +
    1000 * (n - 1); `reference` (a wav beside voices.json) keeps a timbre; `tempo` is played
    after (ffmpeg atempo, pitch unchanged)."""
    style: str = Field(min_length=1)
    seed: int
    cfg: float = Field(2.0, gt=0, le=10)
    steps: int = Field(30, ge=1, le=100)
    reference: Optional[str] = None
    tempo: float = Field(1.0, ge=0.5, le=2.0)  # atempo's range is 0.5-100; past 2x is noise


class Voice(BaseModel):
    id: str
    label: str
    description: str
    card_text: str = ""  # cloned voices: what the card says
    styles: List[str] = []
    address: List[str] = []
    default: bool = False
    recipe: Optional[Recipe] = None  # designed voice; None: cloned from the card
    card: Path  # cloned voices: the clip that defines the voice; designed: a sample to hear

    def take_params(self) -> Dict[str, Any]:
        """What the engine needs for a take (picklable: it crosses to the worker)."""
        if self.recipe is None:
            return {"card": str(self.card), "card_text": self.card_text}
        r = self.recipe.model_dump()
        r["reference"] = str(self.card.parent / r["reference"]) if r["reference"] else None
        return {"recipe": r}


def load_voices(folder: Path = VOICES_DIR) -> Dict[str, Voice]:
    """voices.json entries whose card wav (and reference) exists; ValueError when there is
    no default voice or a cloned voice has no card_text."""
    entries = json.loads((folder / "voices.json").read_text(encoding="utf-8"))["voices"]
    voices = {e["id"]: Voice(**e, card=folder / f"{e['id']}.wav") for e in entries}
    missing = [v.id for v in voices.values() if not v.card.is_file()
               or (v.recipe and v.recipe.reference and not (folder / v.recipe.reference).is_file())]
    if missing:
        raise ValueError(f"voice cards missing in {folder}: {missing}")
    textless = [v.id for v in voices.values() if v.recipe is None and not v.card_text]
    if textless:
        raise ValueError(f"cloned voices need their card_text: {textless}")
    if sum(v.default for v in voices.values()) != 1:
        raise ValueError("voices.json must mark exactly one voice `default: true`")
    return voices


def synthesize(engine: Worker, settings: Settings, script: str, voice: Voice) -> Dict[str, Any]:
    """Takes until one scores >= min_score (at most max_takes); the best one wins."""
    lines = [line.strip() for line in script.splitlines() if line.strip()]
    if not lines:
        raise ValueError("nothing to say: the text is empty")
    spoken = take_text([speak(line) for line in lines])
    best, scores = None, []
    for n in range(1, settings.max_takes + 1):
        t0 = time.perf_counter()
        audio, duration, words = engine.take(spoken, voice, n)
        heard = " ".join(w["text"] for w in words)
        s = round(score(spoken, heard), 3)
        scores.append(s)
        log.info("take %d voice=%s score=%.3f audio=%.1fs compute=%.1fs vram=%sGB heard=%r",
                 n, voice.id, s, duration, time.perf_counter() - t0, engine.vram_gb(), heard)
        if best is None or s > best[0]:
            best = (s, audio, duration, words)
        if s >= settings.min_score:
            break
    s, audio, duration, words = best
    return {"audio": base64.b64encode(audio).decode("ascii"),
            "words": line_spans(words, lines),
            "take": {"voice": voice.id, "score": s, "scores": scores,
                     "duration_s": round(duration, 3), "spoken": spoken}}


class TTSRequest(BaseModel):
    text: str
    voice: str = ""


def create_app(engine: Worker, settings: Settings, voices: Dict[str, Voice], *,
               gpu_path: Optional[str] = None,
               clock: Callable[[], float] = time.monotonic) -> FastAPI:
    """The HTTP service. `app.state.unload_if_idle()` drops the models once idle (main() calls
    it every few seconds); gpu_path None = gpu_lock.default_path()."""
    app = FastAPI(title="VoxCPM2 voice service")
    busy = threading.Lock()  # one request (or unload) at a time
    gpu = contextlib.ExitStack()  # holds the machine's GPU lock while the models are loaded
    last_used = [clock()]
    default = next(v.id for v in voices.values() if v.default)

    def drop() -> None:
        engine.unload()
        gpu.close()

    def load() -> None:
        if engine.model is not None:
            return
        t0 = time.perf_counter()
        gpu.enter_context(gpu_lock.hold(f"voice service {MODEL_ID}", gpu_path,  # + admission (166)
                                        need_vram_gb=gpu_lock.guard.VRAM_GB["voice"]))
        t1 = time.perf_counter()
        try:
            engine.load()
        except BaseException:
            drop()
            raise
        log.info("loaded %s + %s in %.0fs (waited %.0fs for the GPU)", MODEL_ID, WHISPER_ID,
                 time.perf_counter() - t1, t1 - t0)

    def unload_if_idle() -> bool:
        with busy:
            idle = clock() - last_used[0]
            if engine.model is None or idle < settings.idle_unload_s:
                return False
            t0 = time.perf_counter()
            drop()
            log.info("idle %.0fs: models unloaded in %.1fs, GPU released", idle,
                     time.perf_counter() - t0)
            return True

    app.state.unload_if_idle = unload_if_idle

    @app.get("/health")
    def health() -> Dict[str, Any]:
        return {"model": MODEL_ID, "loaded": engine.model is not None,
                "worker_pid": getattr(engine.model, "pid", None),  # the studio's watchdog (166)
                "voices": sorted(voices), "default_voice": default,
                "settings": settings.model_dump(),
                "recipes": {v.id: v.recipe.model_dump() for v in voices.values() if v.recipe}}

    @app.post("/tts")
    def tts(req: TTSRequest, request: Request) -> Dict[str, Any]:  # sync: run in a thread
        def gone() -> None:  # the studio gave up waiting (its timeout): nobody to speak for
            if from_thread.run(request.is_disconnected):
                raise HTTPException(503, "the client is gone")

        voice = voices.get(req.voice or default)
        if voice is None:
            raise HTTPException(400, f"unknown voice {req.voice!r}; voices: {sorted(voices)}")
        if not req.text.strip():  # before a ~35 s model load
            raise HTTPException(400, "nothing to say: the text is empty")
        with busy:
            try:
                gone()  # it may have waited behind another request
                load()  # may wait long for RAM / VRAM / the GPU lock
                gone()  # 2026-11-25: never synthesise for nobody ahead of a render
                return synthesize(engine, settings, req.text, voice)
            except ValueError as e:
                raise HTTPException(400, str(e)) from None
            except WorkerFailed as e:  # the worker is gone or broken: drop it, free the GPU
                drop()
                log.error("voice engine failed: %s", e)
                raise HTTPException(503, f"voice engine failed ({e}); the next request "
                                         "starts a new one") from None
            finally:
                last_used[0] = clock()

    return app


def _unload_when_idle(unload_if_idle: Callable[[], bool], every_s: float = 5.0) -> None:
    while True:
        time.sleep(every_s)
        try:
            unload_if_idle()
        except Exception:  # noqa: BLE001 - keep watching; the next tick retries
            log.exception("idle unload failed")


def _exit_with(pid: int) -> None:
    """Exit once process `pid` (the studio that started us) is gone, even killed, so no
    orphan keeps the GPU. Watching a pid, not a stdin pipe: on Windows a pending pipe read
    blocks other calls on that handle and hung the model load."""
    if sys.platform == "win32":
        import ctypes

        kernel = ctypes.windll.kernel32
        handle = kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE; 0: already gone
        if handle:
            kernel.WaitForSingleObject(handle, 0xFFFFFFFF)
    else:
        while True:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            except PermissionError:
                pass
            time.sleep(2)
    log.info("the studio (pid %d) is gone: exiting", pid)
    os._exit(0)


def main(argv: Optional[List[str]] = None) -> None:
    import uvicorn

    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8766)
    p.add_argument("--voices", type=Path, default=VOICES_DIR)
    p.add_argument("--exit-with-pid", type=int, help=argparse.SUPPRESS)
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    gpu_lock.guard.lower_self()  # step 166 (+ its CPUs, 171): so is the model worker, its child
    if args.exit_with_pid:
        threading.Thread(target=_exit_with, args=(args.exit_with_pid,), daemon=True).start()
    settings, voices = Settings.from_env(), load_voices(args.voices)
    app = create_app(Worker(functools.partial(Engine, settings.steps, settings.cfg,
                                              gpu_lock.guard.heavy_cpus())), settings,
                     voices)
    threading.Thread(target=_unload_when_idle, args=(app.state.unload_if_idle,),
                     daemon=True).start()
    log.info("up; %s loads on the first request (GPU lock %s); voices %s; %s", MODEL_ID,
             gpu_lock.default_path(), sorted(voices), settings.model_dump())
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
