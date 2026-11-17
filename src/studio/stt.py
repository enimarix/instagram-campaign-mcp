"""
Clip transcription (GOAL.md §3.1 Track A step 5): a clip's speech → timed caption lines
[{start_s, end_s, text}] ready for the `captions` op (recipe.CaptionLine: at most 80 chars,
sorted, non-overlapping).

Providers (settings block `# --- Transcription`): `none` (default, no lines) and
`faster_whisper` (local CPU, int8; optional extra: `pip install -e .[stt]`, which downloads
the model from the Hugging Face Hub on first use). Results are cached by file sha256 +
provider + model + language under `stt_cache_dir`.
"""

from __future__ import annotations

import hashlib
import json
import math
import tempfile
import textwrap
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Protocol

import structlog
from pydantic import ValidationError

from ..config import InstagramMCPSettings
from . import ffmpeg, media
from .recipe import MAX_CAPTION, CaptionLine
from .tts import _write_atomic

logger = structlog.get_logger(__name__)

EXTRACT_TIMEOUT_S = 300.0
# Whisper's own silence rule (no_speech_threshold 0.6 + log_prob_threshold -1.0).
NO_SPEECH_PROB = 0.6
LOW_LOGPROB = -1.0

Line = Dict[str, Any]


class STTError(RuntimeError):
    """Transcription is not possible (missing dependency, unreadable audio)."""


class STTProvider(Protocol):
    name: str
    model: str

    def transcribe(self, path: Path, *, language: Optional[str] = None) -> List[Line]:
        ...


def split_text(text: str, max_chars: int = MAX_CAPTION) -> List[str]:
    """`text` in as few word-wrapped chunks of at most `max_chars` as possible, evened out
    (85 chars → 43 + 41, not 80 + 4)."""
    n = math.ceil(len(text) / max_chars)
    width = math.ceil(len(text) / n)
    chunks = textwrap.wrap(text, width)
    while len(chunks) > n and width < max_chars:
        width += 1
        chunks = textwrap.wrap(text, width)
    return chunks


def to_lines(segments: Iterable[Any], max_chars: int = MAX_CAPTION) -> List[Line]:
    """Engine segments (objects with start, end, text; optional no_speech_prob and
    avg_logprob) → caption lines. Silent and empty segments are dropped, long ones split
    with the time shared by characters, overlaps trimmed (a line starts at the earliest
    when the previous one ends)."""
    out: List[Line] = []
    prev_end = 0.0
    for seg in sorted(segments, key=lambda s: s.start):
        if (getattr(seg, "no_speech_prob", 0.0) > NO_SPEECH_PROB
                and getattr(seg, "avg_logprob", 0.0) < LOW_LOGPROB):
            continue
        text = " ".join(seg.text.split())
        if not text:
            continue
        chunks = split_text(text, max_chars)
        start, end = max(float(seg.start), prev_end), float(seg.end)
        total = sum(len(c) for c in chunks)
        done, t = 0, start
        for chunk in chunks:
            done += len(chunk)
            chunk_start, t = t, round(start + (end - start) * done / total, 3)
            try:
                line = CaptionLine(start_s=chunk_start, end_s=t, text=chunk)
            except ValidationError:  # zero length after trimming, or emoji only
                continue
            out.append(line.model_dump())
            prev_end = line.end_s
    return out


class NoneProvider:
    name = "none"
    model = ""

    def transcribe(self, path: Path, *, language: Optional[str] = None) -> List[Line]:
        return []


class FasterWhisperProvider:
    """faster-whisper (CTranslate2) on the CPU, int8. The model loads on first use."""

    name = "faster_whisper"

    def __init__(self, settings: InstagramMCPSettings):
        try:
            import faster_whisper
        except ImportError:
            raise STTError("STT_PROVIDER=faster_whisper needs the optional dependency: "
                           "install with `pip install -e .[stt]`") from None
        self._fw = faster_whisper
        self._whisper = None
        self.model = settings.stt_model
        self.language = settings.stt_language or None
        self.cache_dir = Path(settings.stt_cache_dir)

    def cache_key(self, file_sha: str, language: Optional[str]) -> str:
        parts = [self.name, self.model, language, file_sha]
        return hashlib.sha256(json.dumps(parts).encode("utf-8")).hexdigest()

    def transcribe(self, path: Path, *, language: Optional[str] = None) -> List[Line]:
        path = Path(path)
        language = language or self.language
        key = self.cache_key(_sha256(path), language)
        cached = self.cache_dir / f"{key}.json"
        if cached.is_file():
            logger.info("stt.cache_hit", provider=self.name, key=key[:12])
            return json.loads(cached.read_text(encoding="utf-8"))
        lines = self._run(path, language) if ffmpeg.probe(path).has_audio else []
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        _write_atomic(cached, json.dumps(lines, ensure_ascii=False).encode("utf-8"))
        logger.info("stt.transcribed", provider=self.name, model=self.model, key=key[:12],
                    lines=len(lines))
        return lines

    def _run(self, path: Path, language: Optional[str]) -> List[Line]:
        with tempfile.TemporaryDirectory() as tmp:
            wav = Path(tmp) / "audio.wav"
            ffmpeg.run(["-i", path, "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", wav],
                       timeout_s=EXTRACT_TIMEOUT_S)
            if self._whisper is None:
                self._whisper = self._fw.WhisperModel(self.model, device="cpu",
                                                      compute_type="int8")
            segments, _info = self._whisper.transcribe(str(wav), language=language,
                                                       vad_filter=True)
            return to_lines(segments)  # segments is lazy: consume it while the wav exists


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def get_provider(settings: InstagramMCPSettings) -> STTProvider:
    if settings.stt_provider == "faster_whisper":
        return FasterWhisperProvider(settings)
    return NoneProvider()


def transcribe_source(store, settings: InstagramMCPSettings, source_id: int, *,
                      language: Optional[str] = None,
                      provider: Optional[STTProvider] = None) -> List[Line]:
    """Transcribe a downloaded clip and keep the lines on the source, in
    `stats.transcript = {provider, model, lines}` (069 reads them from there)."""
    source = store.get_source(source_id)
    if not source["local_path"]:
        raise STTError(f"source {source_id} has no local file")
    provider = provider or get_provider(settings)
    lines = provider.transcribe(media.resolve(settings.media_root, source["local_path"]),
                                language=language)
    store.patch_source_stats(source_id, {"transcript": {
        "provider": provider.name, "model": provider.model, "lines": lines}})
    return lines
