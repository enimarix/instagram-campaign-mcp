"""
VoxCPM2 voice service for the studio (step 038, docs/DECISIONS.md 2026-11-19): a local
HTTP service the studio's `http` TTS provider calls (TTS_HTTP_RESPONSE=json).

  POST /tts {"text": "<one script line per line>", "voice": "<id>"}
       -> {"audio": <base64 wav>, "words": [{"text", "start_s", "end_s"}, ...], "take": {...}}
       `words` holds one span per script line, its text as written (speech.line_spans).
  GET  /health -> {"model", "loaded", "voices", "default_voice", "settings"} (at once)

The owner's approved settings (by ear): the whole script in ONE take, cfg 1.6, 30 steps,
cloned from the voice card as continuation (prompt wav + text) AND reference. Each take is
transcribed by Whisper (CPU, so VRAM stays under 8 GB with VoxCPM2 loaded) and compared to
the text; under VOXCPM_MIN_SCORE the take is redone, up to VOXCPM_MAX_TAKES, and the best
take is kept. One request at a time.

The GPU is shared (step 145): the models load on the first request, under the machine's GPU
lock (src/studio/gpu_lock.py, the one Blender and Remotion renders take), and the lock is held
while they are loaded. After VOXCPM_IDLE_UNLOAD_S without a request (default 120 s) both are
dropped (VRAM and Whisper's ~3 GB of RAM) and the lock released, so a render can run. A load
costs ~35 s. torch / voxcpm / transformers are imported only by Engine.load(), so CI imports
this module without them.

Run: python vendor/voxcpm_tts/server.py [--host 127.0.0.1] [--port 8766] (README.md).
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import gc
import importlib.util
import io
import json
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from speech import line_spans, score, speak, take_text

log = logging.getLogger("voxcpm_tts")

REPO = Path(__file__).resolve().parents[2]
# The studio's lock, by path: this service runs in its own venv, without the studio package.
_spec = importlib.util.spec_from_file_location("gpu_lock", REPO / "src" / "studio" / "gpu_lock.py")
gpu_lock = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gpu_lock)

MODEL_ID = "openbmb/VoxCPM2"
WHISPER_ID = "openai/whisper-large-v3-turbo"
VOICES_DIR = REPO / "brand" / "voices"
PEAK = 0.99  # never clip; loudness is the studio's loudnorm (step 033)


class Settings(BaseModel):
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


class Voice(BaseModel):
    id: str
    label: str
    description: str
    card_text: str
    styles: List[str] = []
    address: List[str] = []
    default: bool = False
    card: Path  # the clip that defines the voice: <voices dir>/<id>.wav


def load_voices(folder: Path = VOICES_DIR) -> Dict[str, Voice]:
    """voices.json entries whose card wav exists; ValueError when there is no default voice."""
    entries = json.loads((folder / "voices.json").read_text(encoding="utf-8"))["voices"]
    voices = {e["id"]: Voice(**e, card=folder / f"{e['id']}.wav") for e in entries}
    missing = [v.id for v in voices.values() if not v.card.is_file()]
    if missing:
        raise ValueError(f"voice cards missing in {folder}: {missing}")
    if sum(v.default for v in voices.values()) != 1:
        raise ValueError("voices.json must mark exactly one voice `default: true`")
    return voices


class Engine:
    """VoxCPM2 + Whisper. take() returns (wav bytes, duration_s, Whisper words)."""

    def __init__(self, settings: Settings):
        self.s = settings
        self.model = self.asr = None

    def load(self) -> None:
        import torch  # lazy: CI has no torch
        from transformers import pipeline
        from voxcpm import VoxCPM

        self.model = VoxCPM.from_pretrained(MODEL_ID, load_denoiser=False)
        # float32: the checkpoint's own fp16 runs ~16x slower on the CPU (190 s vs 12 s).
        self.asr = pipeline("automatic-speech-recognition", model=WHISPER_ID, device="cpu",
                            dtype=torch.float32)

    def unload(self) -> None:
        """Drop both models: VRAM back to the driver, Whisper's RAM back to the OS."""
        self.model = self.asr = None
        gc.collect()
        try:
            import torch
            torch.cuda.empty_cache()
        except Exception:  # noqa: BLE001 - no torch / no CUDA: nothing cached
            pass

    def take(self, text: str, voice: Voice):
        import numpy as np
        import soundfile as sf

        card = str(voice.card)
        wav = self.model.generate(text=text, prompt_wav_path=card, prompt_text=voice.card_text,
                                  reference_wav_path=card, cfg_value=self.s.cfg,
                                  inference_timesteps=self.s.steps)
        sr = self.model.tts_model.sample_rate
        wav = np.asarray(wav, dtype=np.float32)
        peak = float(np.abs(wav).max()) if wav.size else 0.0
        if peak > PEAK:
            wav *= PEAK / peak
        out = self.asr({"raw": wav, "sampling_rate": sr}, return_timestamps="word",
                       generate_kwargs={"language": "french"}, chunk_length_s=30)
        words = [{"text": c["text"].strip(), "start_s": float(c["timestamp"][0]),
                  "end_s": float(c["timestamp"][1] if c["timestamp"][1] is not None
                                 else len(wav) / sr)}
                 for c in out["chunks"] if c["text"].strip()]
        buf = io.BytesIO()
        sf.write(buf, wav, sr, format="WAV", subtype="PCM_16")
        return buf.getvalue(), len(wav) / sr, words

    def vram_gb(self) -> Optional[float]:
        try:
            import torch
            return round(torch.cuda.max_memory_allocated() / 1e9, 2)
        except Exception:  # noqa: BLE001 - no CUDA: no number
            return None


def synthesize(engine: Engine, settings: Settings, script: str, voice: Voice) -> Dict[str, Any]:
    """Takes until one scores >= min_score (at most max_takes); the best one wins."""
    lines = [line.strip() for line in script.splitlines() if line.strip()]
    if not lines:
        raise ValueError("nothing to say: the text is empty")
    spoken = take_text([speak(line) for line in lines])
    best, scores = None, []
    for n in range(1, settings.max_takes + 1):
        t0 = time.perf_counter()
        audio, duration, words = engine.take(spoken, voice)
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


def create_app(engine: Engine, settings: Settings, voices: Dict[str, Voice], *,
               gpu_path: Optional[str] = None,
               clock: Callable[[], float] = time.monotonic) -> FastAPI:
    """The HTTP service. `app.state.unload_if_idle()` drops the models once idle (main() calls
    it every few seconds); gpu_path None = gpu_lock.default_path()."""
    app = FastAPI(title="VoxCPM2 voice service")
    busy = threading.Lock()  # one request (or unload) at a time
    gpu = contextlib.ExitStack()  # holds the machine's GPU lock while the models are loaded
    last_used = [clock()]
    default = next(v.id for v in voices.values() if v.default)

    def load() -> None:
        if engine.model is not None:
            return
        t0 = time.perf_counter()
        gpu.enter_context(gpu_lock.hold(f"voice service {MODEL_ID}", gpu_path))
        t1 = time.perf_counter()
        try:
            engine.load()
        except BaseException:
            engine.unload()
            gpu.close()
            raise
        log.info("loaded %s + %s in %.0fs (waited %.0fs for the GPU)", MODEL_ID, WHISPER_ID,
                 time.perf_counter() - t1, t1 - t0)

    def unload_if_idle() -> bool:
        with busy:
            idle = clock() - last_used[0]
            if engine.model is None or idle < settings.idle_unload_s:
                return False
            t0 = time.perf_counter()
            engine.unload()
            gpu.close()
            log.info("idle %.0fs: models unloaded in %.1fs, GPU released", idle,
                     time.perf_counter() - t0)
            return True

    app.state.unload_if_idle = unload_if_idle

    @app.get("/health")
    def health() -> Dict[str, Any]:
        return {"model": MODEL_ID, "loaded": engine.model is not None,
                "voices": sorted(voices), "default_voice": default,
                "settings": settings.model_dump()}

    @app.post("/tts")
    def tts(req: TTSRequest) -> Dict[str, Any]:  # sync: FastAPI runs it in a thread
        voice = voices.get(req.voice or default)
        if voice is None:
            raise HTTPException(400, f"unknown voice {req.voice!r}; voices: {sorted(voices)}")
        if not req.text.strip():  # before a ~35 s model load
            raise HTTPException(400, "nothing to say: the text is empty")
        with busy:
            try:
                load()
                return synthesize(engine, settings, req.text, voice)
            except ValueError as e:
                raise HTTPException(400, str(e)) from None
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
    if args.exit_with_pid:
        threading.Thread(target=_exit_with, args=(args.exit_with_pid,), daemon=True).start()
    settings, voices = Settings.from_env(), load_voices(args.voices)
    app = create_app(Engine(settings), settings, voices)
    threading.Thread(target=_unload_when_idle, args=(app.state.unload_if_idle,),
                     daemon=True).start()
    log.info("up; %s loads on the first request (GPU lock %s); voices %s; %s", MODEL_ID,
             gpu_lock.default_path(), sorted(voices), settings.model_dump())
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
