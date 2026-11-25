"""
Voice-over (GOAL.md §4.1 TTSProvider, §5.6 synthetic voice): script text → audio file + line
timings for the motion timeline (motion/src/lib/timeline.ts takes one {text, start_s, end_s} per
script line, so per-word engine timings are grouped per line here).

Providers: `none` (no audio, estimated timings, captions only) and `http` (a local TTS service
set up in the `# --- Voice (TTS)` settings block; request and response shapes are documented
there). HTTP results are cached by a hash of everything that changes the audio.

Step 204: with ELEVENLABS_API_KEY set, get_provider gives an EngineProvider: ElevenLabs
(`elevenlabs`) and the local service (`http`) in the owner's priority order (voices.engine),
the other one taking over on any failure, in the voice paired with the one asked
(voices.engine_plan). Scripts may carry ElevenLabs audio tags (`[excited]`, `[laughs]`): only
ElevenLabs hears them; the local engine and every line timing (captions) get the text
without them (strip_tags).
"""

from __future__ import annotations

import base64
import binascii
import functools
import hashlib
import importlib.util
import json
import mimetypes
import os
import re
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Sequence, Tuple

import httpx
import structlog

from ..config import InstagramMCPSettings
from . import elevenlabs, ffmpeg, voices

logger = structlog.get_logger(__name__)

# An audio tag: a few words in square brackets, no digits ("[1]" is not one), no nesting.
TAG = re.compile(r"\[[^\[\]\d\n]{1,40}\]")


def strip_tags(text: str) -> str:
    """`text` without ElevenLabs audio tags, spaces tidied on every line."""
    return "\n".join(" ".join(TAG.sub(" ", line).split()) for line in text.splitlines())


# The local voice service's French normaliser (numbers, units, times, macrobody.fr) and its
# rule that a (bracketed) part is shown, never said: ElevenLabs says the script the same way.
SPEECH = Path(__file__).resolve().parents[2] / "vendor" / "voxcpm_tts" / "speech.py"


@functools.lru_cache(maxsize=1)
def _speech() -> Optional[Any]:
    try:
        spec = importlib.util.spec_from_file_location("voxcpm_speech", SPEECH)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except (ImportError, OSError) as e:  # num2words missing: said as written
        logger.warning("tts.speech_normaliser_missing", error=str(e)[:200])
        return None


def say_as_written(line: str) -> str:
    """A script line as a voice must hear it: numbers, units and the brand spelled out, a
    (bracketed) part left unsaid; audio tags untouched (vendor/voxcpm_tts/speech.py)."""
    sp = _speech()
    return sp.unbracket(sp.speak(line)) if sp else line


def hears_tags(model: str) -> bool:
    """ElevenLabs models that act on audio tags; the others read them aloud. Docs read
    2026-11-24: elevenlabs.io/docs/best-practices/prompting.md (v4, and « also apply to
    Eleven v3 »), docs/overview/models.md (v4 Turbo, v3 Conversational: « Audio tags for
    fine-grained control »)."""
    return model.startswith(("eleven_v3", "eleven_v4"))


def retag(lines: Sequence[str], spoken: Optional[Sequence[str]]) -> List[str]:
    """`lines` (the props' plain lines) with their audio tags back from `spoken`, matched by
    their plain text (a line the schema added, or one edited since, goes untagged; the same
    plain line twice takes its tagged versions in order)."""
    pool: Dict[str, List[str]] = {}
    for s in spoken or []:
        pool.setdefault(strip_tags(s), []).append(s)
    out = []
    for line in lines:
        tagged = pool.get(line)
        out.append(tagged.pop(0) if tagged else line)
    return out

# Same reading-speed rule as motion/src/lib/timeline.ts (READ_CHARS_PER_S, MIN_LINE_S,
# LINE_GAP_S): change both together.
READ_CHARS_PER_S = 15.0
MIN_LINE_S = 1.2
LINE_GAP_S = 0.3


class TTSError(RuntimeError):
    """Synthesis failed. `status` is the service's HTTP status when there was one;
    `unreachable`: the service did not answer (down, or no answer in time)."""

    def __init__(self, message: str, *, status: Optional[int] = None,
                 unreachable: bool = False):
        super().__init__(message)
        self.status = status
        self.unreachable = unreachable

    @property
    def machine(self) -> bool:
        """The machine failed, not the text (step 197): no answer, or HTTP 5xx (the voice
        service answers 503 when its engine died)."""
        return self.unreachable or (self.status or 0) >= 500


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
    voice: Optional[str] = None  # the voice that spoke (an engine's fallback may swap it)
    fallback: Optional[str] = None  # why the first engine did not speak, when it did not


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
        lines = reading_timings(script_lines(strip_tags(text)))
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


class _Cached:
    """Synthesis through `_request(spoken, voice)` with a file cache (`tts_cache_dir`) keyed
    by `cache_key`. The lines (and so the captions) never carry audio tags; what the engine
    hears is `_spoken(text)`."""

    name = "cached"

    def __init__(self, settings: InstagramMCPSettings, *,
                 http_client: Optional[httpx.Client] = None):
        self.s = settings
        self.cache_dir = Path(settings.tts_cache_dir)
        self.http = http_client
        self._spans: Optional[List[Tuple[float, float]]] = None  # the last request's lines

    def _timings(self, words: Optional[List["WordTiming"]], lines: List[str],
                 duration: float) -> List["LineTiming"]:
        return (group_words_into_lines(words, lines) if words
                else estimate_line_timings(lines, duration))

    def _voice(self, voice: Optional[str]) -> str:
        return self.s.tts_voice if voice is None else voice

    def _spoken(self, text: str) -> str:
        return strip_tags(text)

    def cache_key(self, text: str, voice: str) -> str:
        raise NotImplementedError

    def _request(self, text: str, voice: str):
        raise NotImplementedError

    def synthesize(self, text: str, voice: Optional[str] = None) -> Synthesis:
        lines = script_lines(strip_tags(text))
        voice = self._voice(voice)
        spoken = "\n".join(script_lines(self._spoken(text)))
        key = self.cache_key(spoken, voice)
        meta_path = self.cache_dir / f"{key}.json"
        cached = self._load(meta_path)
        if cached:
            logger.info("tts.cache_hit", provider=self.name, key=key[:12])
            cached.voice = voice
            if len(cached.lines) == len(lines):  # another script may say the same (« 21h »
                cached.lines = [LineTiming(line, t.start_s, t.end_s)  # / « 21 h »): ours
                                for line, t in zip(lines, cached.lines)]
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
        timings = self._timings(words, lines, duration)
        result = Synthesis(audio_path, duration, timings, words, self.name, voice)
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


class HttpProvider(_Cached):
    """A TTS service over HTTP (settings `tts_http_*`), with a file cache (`tts_cache_dir`)."""

    name = "http"

    def __init__(self, settings: InstagramMCPSettings, *,
                 http_client: Optional[httpx.Client] = None):
        if not settings.tts_http_url:
            raise TTSError("TTS_PROVIDER=http needs TTS_HTTP_URL")
        super().__init__(settings, http_client=http_client)

    def cache_key(self, text: str, voice: str) -> str:
        s = self.s
        parts = [self.name, voice, text, s.tts_http_url, s.tts_http_method.upper(),
                 s.tts_http_body_template, s.tts_http_response, s.tts_http_audio_field]
        recipe = voices.recipe(voice)  # a designed voice re-tuned under the same id: new audio
        if recipe is not None:
            parts.append(recipe)
        return hashlib.sha256(json.dumps(parts, sort_keys=True).encode("utf-8")).hexdigest()

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
            raise TTSError(f"the TTS service did not answer within {s.tts_timeout_s} s",
                           unreachable=True) from None
        except httpx.HTTPError as e:
            raise TTSError(f"TTS request failed ({type(e).__name__})", unreachable=True) from None
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


def alignment_words(alignment: Optional[dict]) -> Optional[List[WordTiming]]:
    """Word timings from ElevenLabs' per-character alignment; the characters of audio tags
    (inside [ ]) are skipped, so the words match the script without its tags."""
    if not alignment:
        return None
    try:
        chars = alignment["characters"]
        starts = alignment["character_start_times_seconds"]
        ends = alignment["character_end_times_seconds"]
    except (KeyError, TypeError):
        return None
    if any(not isinstance(c, str) or len(c) != 1 for c in chars):
        return None  # not one entry per character: the line timings are estimated instead
    text = "".join(chars)
    in_tag = [False] * len(text)
    for m in TAG.finditer(text):  # the same tags strip_tags takes out ("[1]" is kept)
        in_tag[m.start():m.end()] = [True] * (m.end() - m.start())
    words: List[WordTiming] = []
    cur, t0, t1 = "", 0.0, 0.0
    for i, (ch, s, e) in enumerate(zip(text, starts, ends)):
        if in_tag[i] or ch.isspace():
            if cur:
                words.append(WordTiming(cur, round(t0, 3), round(t1, 3)))
                cur = ""
            continue
        if not cur:
            t0 = float(s)
        cur, t1 = cur + ch, float(e)
    if cur:
        words.append(WordTiming(cur, round(t0, 3), round(t1, 3)))
    return words or None


def alignment_lines(alignment: Optional[dict]) -> Optional[List[Tuple[float, float]]]:
    """(start, end) of each line of the text ElevenLabs spoke that says something (a line of
    tags or spaces only is skipped), from its per-character alignment."""
    if not alignment:
        return None
    try:
        chars = alignment["characters"]
        starts = alignment["character_start_times_seconds"]
        ends = alignment["character_end_times_seconds"]
    except (KeyError, TypeError):
        return None
    if any(not isinstance(c, str) or len(c) != 1 for c in chars):
        return None
    text = "".join(chars)
    in_tag = [False] * len(text)
    for m in TAG.finditer(text):
        in_tag[m.start():m.end()] = [True] * (m.end() - m.start())
    spans: List[Tuple[float, float]] = []
    cur: Optional[Tuple[float, float]] = None
    for i, (ch, s, e) in enumerate(zip(text, starts, ends)):
        if ch == "\n":
            if cur:
                spans.append(cur)
            cur = None
        elif not in_tag[i] and not ch.isspace():
            cur = (float(s), float(e)) if cur is None else (cur[0], float(e))
    if cur:
        spans.append(cur)
    return spans or None


class ElevenLabsProvider(_Cached):
    """An ElevenLabs card's voice (voices.el_card) through the API, model from the owner's
    choice (voices.engine). It hears the audio tags. Before spending, the account's credits
    are checked against the text: too few is a TTSError, never a cut-off voice (a key that
    may not read them goes ahead). Its failures are the machine's (TTSError.machine: the
    video waits, never fails for its script), except a request ElevenLabs refused as bad
    (400, 422)."""

    name = "elevenlabs"

    def _voice(self, voice: Optional[str]) -> str:
        return voice or ""

    def _spoken(self, text: str) -> str:
        """Each line said as written (say_as_written); its tags only for a model that
        hears them (the others would read them aloud)."""
        keep = hears_tags(voices.engine()["model"])
        return "\n".join(say_as_written(" ".join((line if keep else strip_tags(line)).split()))
                         for line in text.splitlines())

    def _timings(self, words, lines, duration):
        """ElevenLabs' own per-line timings when every line got one; else the default."""
        spans = self._spans
        if spans and len(spans) == len(lines):
            return [LineTiming(line, round(min(a, duration), 3), round(min(b, duration), 3))
                    for line, (a, b) in zip(lines, spans)]  # never past the audio's end
        return super()._timings(words, lines, duration)

    def _card(self, voice: str) -> Dict[str, Any]:
        card = voices.el_card(voice)
        if not card:
            raise TTSError(f"{voice!r} is not an ElevenLabs voice")
        return card

    def cache_key(self, text: str, voice: str) -> str:
        card = self._card(voice)
        parts = [self.name, card["el_voice_id"], voices.engine()["model"], text]
        return hashlib.sha256(json.dumps(parts).encode("utf-8")).hexdigest()

    def _request(self, text: str, voice: str):
        card = self._card(voice)
        try:
            left = elevenlabs.credits(self.s, client=self.http)["left"]
        except elevenlabs.ElevenLabsError as e:  # e.g. a key scoped to text to speech only
            left = None
            logger.info("tts.elevenlabs_credits_unknown", error=str(e)[:200])
        if left is not None and left < len(text):
            raise TTSError(f"ElevenLabs credits: {left} left, this voice-over needs "
                           f"{len(text)}", unreachable=True)
        try:
            # no language_code: a card's label is the voice's language, not the script's
            audio, alignment = elevenlabs.speech(self.s, card["el_voice_id"], text,
                                                 voices.engine()["model"], client=self.http)
        except elevenlabs.ElevenLabsError as e:
            raise TTSError(str(e), status=e.status,
                           unreachable=e.status not in (400, 422)) from None
        except ValueError as e:  # a card id that is not an ElevenLabs id
            raise TTSError(str(e)) from None
        if not audio:
            raise TTSError("ElevenLabs returned no audio")
        self._spans = alignment_lines(alignment)
        return audio, ".mp3", alignment_words(alignment)


class EngineProvider:
    """The owner's engines in priority order (voices.engine_plan for the voice asked): the
    first one that speaks wins; one that failed is skipped for the rest of this provider's
    life (one video, one engine: a sitcom's lines never switch engines mid-video once one
    failed). The result's `fallback` says why the first engine did not speak."""

    name = "engine"

    def __init__(self, settings: InstagramMCPSettings, local: Optional[TTSProvider],
                 eleven: Optional[TTSProvider]):
        self.engines = {"local": local, "elevenlabs": eleven}
        self.failed: Dict[str, str] = {}

    def synthesize(self, text: str, voice: Optional[str] = None) -> Synthesis:
        why: Optional[str] = None
        last: Optional[TTSError] = None
        for engine, v in voices.engine_plan(voice):
            provider = self.engines[engine]
            if provider is None or engine in self.failed:
                why = why or self.failed.get(engine) or f"{engine} is not set up"
                continue
            try:
                synth = provider.synthesize(text, v)
            except TTSError as e:
                self.failed[engine] = str(e)[:200]
                why, last = why or self.failed[engine], e
                logger.warning("tts.engine_failed", engine=engine, error=str(e)[:200])
                continue
            synth.voice, synth.fallback = v, why
            return synth
        if last is not None:
            raise last
        if any(e in self.failed for e, _ in voices.engine_plan(voice)):  # failed earlier
            raise TTSError(f"no voice engine left for this video: {why}", unreachable=True)
        return NoneProvider().synthesize(text, voice)  # none set up: captions only, as before


def get_provider(settings: InstagramMCPSettings) -> TTSProvider:
    local = HttpProvider(settings) if settings.tts_provider == "http" else None
    if elevenlabs.configured(settings):
        return EngineProvider(settings, local, ElevenLabsProvider(settings))
    if voices.el_cards():  # no key (any more): a card speaks in its local relay voice
        return EngineProvider(settings, local, None)
    return local or NoneProvider()


def voiced(settings: InstagramMCPSettings) -> bool:
    """Whether the studio has a voice engine (else captions only)."""
    return settings.tts_provider != "none" or elevenlabs.configured(settings)
