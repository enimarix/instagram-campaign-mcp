"""
The heavy half of the voice service (step 146): VoxCPM2 + Whisper live in a child process
that exits when the models are unloaded, so the OS gets every byte back. In-process, `del` +
gc + empty_cache gave the VRAM back but torch's CPU allocator (mimalloc on Windows) kept
~17 GB of committed RAM until the service restarted.

- Engine: the models. Runs in the worker process only (imports torch).
- Worker: the service's handle on that process: load() starts it (spawn) and waits until the
  models are loaded, take() asks it for one take, unload() terminates it. Anything that goes
  wrong in the worker (it died, the load or a take raised) is WorkerFailed, and the worker is
  then gone or must be dropped: the service answers 503 and the next request starts a new one.

Stdlib only at import: CI imports this module without torch.
"""

from __future__ import annotations

import io
import multiprocessing
import os
from typing import Any, Callable, Optional

MODEL_ID = "openbmb/VoxCPM2"
WHISPER_ID = "openai/whisper-large-v3-turbo"
PEAK = 0.99  # never clip; loudness is the studio's loudnorm (step 033)


class WorkerFailed(RuntimeError):
    """The engine process died, or its load or a take failed."""


class Engine:
    """VoxCPM2 + Whisper. take() returns (wav bytes, duration_s, Whisper words)."""

    def __init__(self, steps: int, cfg: float):
        self.steps, self.cfg = steps, cfg
        self.model = self.asr = None

    def load(self) -> None:
        import torch  # lazy: CI has no torch
        from transformers import pipeline
        from voxcpm import VoxCPM

        self.model = VoxCPM.from_pretrained(MODEL_ID, load_denoiser=False)
        # float32: the checkpoint's own fp16 runs ~16x slower on the CPU (190 s vs 12 s).
        self.asr = pipeline("automatic-speech-recognition", model=WHISPER_ID, device="cpu",
                            dtype=torch.float32)

    def take(self, text: str, card: str, card_text: str):
        import numpy as np
        import soundfile as sf

        wav = self.model.generate(text=text, prompt_wav_path=card, prompt_text=card_text,
                                  reference_wav_path=card, cfg_value=self.cfg,
                                  inference_timesteps=self.steps)
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


def serve(conn, make_engine: Callable[[], Any]) -> None:
    """The worker process: load, say ("ready", None), then answer each (text, card,
    card_text) with ("ok", (audio, duration_s, words, vram_gb)) or ("error", why). Returns
    (the process exits) when the service closes the pipe or dies."""
    # mimalloc (torch's CPU allocator on Windows) gives freed pages back at once instead of
    # keeping them: ~9.7 GB committed after the VoxCPM2 load instead of ~21 GB. Read when
    # torch loads, so before the first import.
    os.environ.setdefault("MIMALLOC_PURGE_DELAY", "0")
    try:
        engine = make_engine()
        engine.load()
    except BaseException as e:  # noqa: BLE001 - tell the service why, then exit
        conn.send(("error", f"load failed: {type(e).__name__}: {e}"))
        return
    conn.send(("ready", None))
    while True:
        try:
            text, card, card_text = conn.recv()
        except (EOFError, OSError):  # the service unloaded us or died
            return
        try:
            conn.send(("ok", (*engine.take(text, card, card_text), engine.vram_gb())))
        except BaseException as e:  # noqa: BLE001 - the service drops this worker
            conn.send(("error", f"take failed: {type(e).__name__}: {e}"))
            return


class Worker:
    """The service's handle on the engine process; the same load / take / unload / vram_gb
    surface as an in-process engine. `model` is the process while loaded, else None."""

    def __init__(self, make_engine: Callable[[], Any]):
        self.make_engine = make_engine  # picklable: it is built in the worker
        self.model: Optional[multiprocessing.process.BaseProcess] = None
        self.conn = None
        self._vram: Optional[float] = None

    def _answer(self):
        try:
            status, value = self.conn.recv()
        except (EOFError, OSError):
            self.model.join(5)
            raise WorkerFailed(f"the engine process died (exit code {self.model.exitcode})"
                               ) from None
        if status == "error":
            raise WorkerFailed(value)
        return value

    def load(self) -> None:
        ctx = multiprocessing.get_context("spawn")  # a fresh interpreter, never a fork
        self.conn, child = ctx.Pipe()
        self.model = ctx.Process(target=serve, args=(child, self.make_engine),
                                 name="voxcpm-engine", daemon=True)
        self.model.start()
        child.close()  # ours closed: the pipe breaks when the worker dies
        self._answer()

    def take(self, text: str, voice):
        try:
            self.conn.send((text, str(voice.card), voice.card_text))
        except OSError:
            raise WorkerFailed("the engine process is gone") from None
        audio, duration, words, self._vram = self._answer()
        return audio, duration, words

    def unload(self) -> None:
        """Terminate the worker: the OS takes back its RAM and VRAM. Idempotent."""
        if self.model is None:
            return
        self.conn.close()
        self.model.terminate()
        self.model.join(30)
        self.model = self.conn = None

    def vram_gb(self) -> Optional[float]:
        return self._vram
