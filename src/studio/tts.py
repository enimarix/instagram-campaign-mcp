"""
Voice-over (GOAL.md §4.1 TTSProvider, §5.6 synthetic voice): script text → audio file + line
timings for the motion timeline (motion/src/lib/timeline.ts takes one {text, start_s, end_s} per
script line, so per-word engine timings are grouped per line here).

Providers: `none` (no audio, estimated timings, captions only) and `http` (a local TTS service
set up in the `# --- Voice (TTS)` settings block; request and response shapes are documented
there). HTTP results are cached by a hash of everything that changes the audio.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import mimetypes
import os
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional, Protocol, Sequence

import httpx
import structlog

from ..config import InstagramMCPSettings
from . import ffmpeg

logger = structlog.get_logger(__name__)

# Same reading-speed rule as motion/src/lib/timeline.ts (READ_CHARS_PER_S, MIN_LINE_S,
# LINE_GAP_S): change both together.
READ_CHARS_PER_S = 15.0
MIN_LINE_S = 1.2
LINE_GAP_S = 0.3


class TTSError(RuntimeError):
    """Synthesis failed. `status` is the service's HTTP status when there was one."""

    def __init__(self, message: str, *, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


@dataclass
class LineTiming:
    text: str
    start_s: float
    end_s: float


@dataclass
class WordTiming:
    text: str
    start_s: float
    end_s: float


@dataclass
class Synthesis:
    audio_path: Optional[Path]  # None: no voice (captions only)
    duration_s: float
    lines: List[LineTiming]
    words: Optional[List[WordTiming]]
    provider: str


class TTSProvider(Protocol):
    name: str

    def synthesize(self, text: str, voice: Optional[str] = None) -> Synthesis:
        """`text` holds one script line per line (the first is the hook)."""
        ...


def script_lines(text: str) -> List[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        raise TTSError("nothing to say: the script is empty")
    return lines


def _chars(s: str) -> int:
    return max(len(s), 1)


def reading_timings(lines: Sequence[str]) -> List[LineTiming]:
    """Timings without a voice: each line READ_CHARS_PER_S, at least MIN_LINE_S, then a
    LINE_GAP_S pause (the motion timeline's estimate, minus its hook minimum)."""
    out, t = [], 0.0
    for line in lines:
        read = max(MIN_LINE_S, len(line) / READ_CHARS_PER_S)
        out.append(LineTiming(line, round(t, 3), round(t + read, 3)))
        t += read + LINE_GAP_S
    return out


def estimate_line_timings(lines: Sequence[str], total_duration_s: float) -> List[LineTiming]:
    """Spread the lines over real audio that came without timings: LINE_GAP_S between lines
    (dropped when the audio is too short for them), the rest shared by character count."""
    gap = LINE_GAP_S if total_duration_s > LINE_GAP_S * len(lines) else 0.0
    speech = total_duration_s - gap * (len(lines) - 1)
    total_chars = sum(_chars(line) for line in lines)
    out, t = [], 0.0
    for line in lines:
        end = t + speech * _chars(line) / total_chars
        out.append(LineTiming(line, round(t, 3), round(end, 3)))
        t = end + gap
    out[-1].end_s = round(total_duration_s, 3)
    return out


def _alnum(s: str) -> int:
    return sum(ch.isalnum() for ch in s)


def group_words_into_lines(words: Sequence[WordTiming],
                           lines: Sequence[str]) -> List[LineTiming]:
    """Line timings from the engine's word timings. Words are matched to lines by position in
    the letters and digits of the script, so punctuation or a different split of a word by the
    engine does not shift the grouping. A line that got no word sits at the previous end."""
    if not words:
        raise TTSError("the engine returned no word timings")
    bounds, acc = [], 0
    for line in lines:
        acc += _alnum(line)
        bounds.append(acc)
    total_line = acc or 1
    total_word = sum(_alnum(w.text) for w in words) or 1
    groups: List[List[WordTiming]] = [[] for _ in lines]
    pos, i = 0, 0
    for w in words:
        mid = (pos + _alnum(w.text) / 2) * total_line / total_word
        pos += _alnum(w.text)
        while i < len(lines) - 1 and mid >= bounds[i]:
            i += 1
        groups[i].append(w)
    out, prev_end = [], 0.0
    for line, group in zip(lines, groups):
        if group:
            out.append(LineTiming(line, group[0].start_s, group[-1].end_s))
            prev_end = group[-1].end_s
        else:
            out.append(LineTiming(line, prev_end, prev_end))
    return out


class NoneProvider:
    """No voice: captions only, on the reading-speed estimate."""

    name = "none"

    def synthesize(self, text: str, voice: Optional[str] = None) -> Synthesis:
        lines = reading_timings(script_lines(text))
        return Synthesis(None, round(lines[-1].end_s + LINE_GAP_S, 3), lines, None, self.name)


def render_body(template: str, text: str, voice: str) -> str:
    """The request body: `template` with {text} and {voice} replaced by JSON-escaped strings
    (the placeholders sit inside quotes in the template). Raises TTSError when the result is
    not JSON."""
    esc = lambda s: json.dumps(s, ensure_ascii=False)[1:-1]  # noqa: E731
    body = template.replace("{text}", esc(text)).replace("{voice}", esc(voice))
    try:
        json.loads(body)
    except ValueError as e:
        raise TTSError(f"TTS_HTTP_BODY_TEMPLATE is not JSON after filling in: {e}") from None
    return body


class HttpProvider:
    """A TTS service over HTTP (settings `tts_http_*`), with a file cache (`tts_cache_dir`)."""

    name = "http"

    def __init__(self, settings: InstagramMCPSettings, *,
                 http_client: Optional[httpx.Client] = None):
        if not settings.tts_http_url:
            raise TTSError("TTS_PROVIDER=http needs TTS_HTTP_URL")
        self.s = settings
        self.cache_dir = Path(settings.tts_cache_dir)
        self.http = http_client

    def cache_key(self, text: str, voice: str) -> str:
        s = self.s
        parts = [self.name, voice, text, s.tts_http_url, s.tts_http_method.upper(),
                 s.tts_http_body_template, s.tts_http_response, s.tts_http_audio_field]
        return hashlib.sha256(json.dumps(parts).encode("utf-8")).hexdigest()

    def synthesize(self, text: str, voice: Optional[str] = None) -> Synthesis:
        lines = script_lines(text)
        voice = self.s.tts_voice if voice is None else voice
        spoken = "\n".join(lines)
        key = self.cache_key(spoken, voice)
        meta_path = self.cache_dir / f"{key}.json"
        cached = self._load(meta_path)
        if cached:
            logger.info("tts.cache_hit", provider=self.name, key=key[:12])
            return cached

        audio, ext, words = self._request(spoken, voice)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        audio_path = self.cache_dir / f"{key}{ext}"
        _write_atomic(audio_path, audio)
        try:
            duration = ffmpeg.probe(audio_path).duration
        except ffmpeg.FFmpegError as e:
            audio_path.unlink(missing_ok=True)
            raise TTSError(f"the TTS service returned unreadable audio: {e}") from None
        timings = (group_words_into_lines(words, lines) if words
                   else estimate_line_timings(lines, duration))
        result = Synthesis(audio_path, duration, timings, words, self.name)
        meta = {"audio": audio_path.name, "duration_s": duration,
                "lines": [asdict(t) for t in timings],
                "words": [asdict(w) for w in words] if words else None}
        _write_atomic(meta_path, json.dumps(meta, ensure_ascii=False).encode("utf-8"))
        logger.info("tts.synthesized", provider=self.name, key=key[:12], chars=len(spoken),
                    duration_s=duration, word_timings=bool(words))
        return result

    def _load(self, meta_path: Path) -> Optional[Synthesis]:
        if not meta_path.is_file():
            return None
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        audio_path = self.cache_dir / meta["audio"]
        if not audio_path.is_file():
            return None
        words = meta["words"]
        return Synthesis(audio_path, meta["duration_s"],
                         [LineTiming(**t) for t in meta["lines"]],
                         [WordTiming(**w) for w in words] if words is not None else None,
                         self.name)

    def _request(self, text: str, voice: str):
        """(audio bytes, file extension, word timings or None). Errors never carry the auth
        header: only the HTTP status or the kind of failure."""
        s = self.s
        headers = {"Content-Type": "application/json"}
        if s.tts_http_auth_header:
            name, sep, value = s.tts_http_auth_header.get_secret_value().partition(":")
            if not sep or not name.strip():
                raise TTSError("TTS_HTTP_AUTH_HEADER must look like 'Name: value'")
            headers[name.strip()] = value.strip()
        body = render_body(s.tts_http_body_template, text, voice)
        client = self.http or httpx.Client()
        try:
            resp = client.request(s.tts_http_method.upper(), s.tts_http_url, content=body,
                                  headers=headers, timeout=s.tts_timeout_s)
        except httpx.TimeoutException:
            raise TTSError(f"the TTS service did not answer within {s.tts_timeout_s} s") from None
        except httpx.HTTPError as e:
            raise TTSError(f"TTS request failed ({type(e).__name__})") from None
        finally:
            if self.http is None:
                client.close()
        if resp.status_code >= 400:
            raise TTSError(f"the TTS service answered HTTP {resp.status_code}",
                           status=resp.status_code)
        if s.tts_http_response == "audio":
            ctype = resp.headers.get("content-type", "").split(";")[0].strip()
            audio, ext, words = resp.content, mimetypes.guess_extension(ctype) or ".audio", None
        else:
            audio, words = _parse_json(resp, s.tts_http_audio_field)
            ext = ".audio"
        if not audio:
            raise TTSError("the TTS service returned no audio")
        return audio, ext, words


def _parse_json(resp: httpx.Response, field: str):
    try:
        data = resp.json()
        audio = base64.b64decode(data[field], validate=True)
        words = data.get("words")
        words = [WordTiming(str(w["text"]), float(w["start_s"]), float(w["end_s"]))
                 for w in words] if words else None
    except (ValueError, KeyError, TypeError, binascii.Error) as e:
        raise TTSError(f"unexpected TTS JSON answer ({type(e).__name__}: {e})") from None
    return audio, words


def _write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")  # two renders, same text
    tmp.write_bytes(data)
    os.replace(tmp, path)


def get_provider(settings: InstagramMCPSettings) -> TTSProvider:
    if settings.tts_provider == "http":
        return HttpProvider(settings)
    return NoneProvider()
