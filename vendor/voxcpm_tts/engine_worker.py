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
import subprocess
import threading
from typing import Any, Callable, Optional

MODEL_ID = "openbmb/VoxCPM2"
# Whisper large-v3-turbo for faster-whisper (CTranslate2), run int8 on the CPU: the same words
# and score as the transformers fp32 pipeline, in half the time, ~3 GB RAM instead of ~13 GB at
# peak (step 146). VOXCPM_WHISPER: another hub id or a local converted folder.
WHISPER_ID = os.environ.get("VOXCPM_WHISPER", "mobiuslabsgmbh/faster-whisper-large-v3-turbo")
PEAK = 0.99  # never clip; loudness is the studio's loudnorm (step 033)


def atempo(wav, sr: int, tempo: float):
    """`wav` (float32 mono) played `tempo` times faster, pitch unchanged (ffmpeg atempo,
    through pipes). The casting's approved speed-ups were made exactly this way."""
    import numpy as np
    import soundfile as sf

    buf = io.BytesIO()
    sf.write(buf, wav, sr, format="WAV", subtype="FLOAT")
    out = subprocess.run(["ffmpeg", "-v", "error", "-f", "wav", "-i", "pipe:0",
                          "-af", f"atempo={tempo}", "-f", "wav", "-c:a", "pcm_f32le", "pipe:1"],
                         input=buf.getvalue(), capture_output=True, check=True, timeout=120).stdout
    faster, _ = sf.read(io.BytesIO(out), dtype="float32")
    return np.asarray(faster, dtype=np.float32)


class WorkerFailed(RuntimeError):
    """The engine process died, or its load or a take failed."""


class Engine:
    """VoxCPM2 + Whisper. take() returns (wav bytes, duration_s, Whisper words)."""

    def __init__(self, steps: int, cfg: float, threads: int = 0):
        self.steps, self.cfg, self.threads = steps, cfg, threads  # threads 0: the libraries'
        self.model = self.asr = None

    def load(self) -> None:
        import torch
        from faster_whisper import WhisperModel  # lazy: CI has neither
        from voxcpm import VoxCPM

        if self.threads:  # the CPUs the guard gives the voice (step 171): no oversubscription
            torch.set_num_threads(self.threads)
        self.model = VoxCPM.from_pretrained(MODEL_ID, load_denoiser=False)
        self.asr = WhisperModel(WHISPER_ID, device="cpu", compute_type="int8",
                                cpu_threads=self.threads)

    def take(self, text: str, params: dict, attempt: int = 1):
        """One take. params (server.Voice.take_params): {"recipe": {style, seed, cfg, steps,
        reference, tempo}} for a designed voice, else {"card", "card_text"} to clone."""
        import numpy as np
        import soundfile as sf
        import torch
        import torchaudio

        r = params.get("recipe")
        if r:
            seed = r["seed"] + 1000 * (attempt - 1)  # a redone take is another seed
            torch.manual_seed(seed)
            np.random.seed(seed)
            ref = {"reference_wav_path": r["reference"]} if r.get("reference") else {}
            wav = self.model.generate(text=f"({r['style']}){text}", cfg_value=r["cfg"],
                                      inference_timesteps=r["steps"], **ref)
        else:
            card = params["card"]
            wav = self.model.generate(text=text, prompt_wav_path=card,
                                      prompt_text=params["card_text"], reference_wav_path=card,
                                      cfg_value=self.cfg, inference_timesteps=self.steps)
        sr = self.model.tts_model.sample_rate
        wav = np.asarray(wav, dtype=np.float32)
        if r and r.get("tempo", 1.0) != 1.0:  # before the peak limit: atempo can overshoot
            wav = atempo(wav, sr, r["tempo"])
        peak = float(np.abs(wav).max()) if wav.size else 0.0
        if peak > PEAK:
            wav *= PEAK / peak
        # Whisper hears 16 kHz. An array, not the wav: faster-whisper 1.2.1's own decoding
        # passes PyAV 19 an argument it no longer takes.
        heard = torchaudio.functional.resample(torch.from_numpy(wav), sr, 16000).numpy()
        segments, _ = self.asr.transcribe(heard, language="fr", word_timestamps=True)
        words = [{"text": w.word.strip(), "start_s": float(w.start), "end_s": float(w.end)}
                 for seg in segments for w in seg.words if w.word.strip()]
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
    """The worker process: load, say ("ready", None), then answer each (text, params,
    attempt) with ("ok", (audio, duration_s, words, vram_gb)) or ("error", why). Returns
    (the process exits) when the service closes the pipe; exits at once if the service dies
    (its GPU lock is then gone: this worker must not keep the GPU through a load or a take)."""
    threading.Thread(target=_exit_with_parent, daemon=True).start()
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
            text, params, attempt = conn.recv()
        except (EOFError, OSError):  # the service unloaded us or died
            return
        try:
            conn.send(("ok", (*engine.take(text, params, attempt), engine.vram_gb())))
        except BaseException as e:  # noqa: BLE001 - the service drops this worker
            conn.send(("error", f"take failed: {type(e).__name__}: {e}"))
            return


def _exit_with_parent() -> None:
    parent = multiprocessing.parent_process()
    if parent is not None:
        parent.join()
        os._exit(0)


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

    def take(self, text: str, voice, attempt: int = 1):
        try:
            self.conn.send((text, voice.take_params(), attempt))
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
