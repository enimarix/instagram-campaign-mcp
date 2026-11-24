"""
The film's voice door (207): while a Lemo film runs, its runner serves the studio's own voice
engines (tts.get_provider: ElevenLabs and the local voice in the owner's order, each taking
over for the other, docs/DECISIONS.md 2026-11-24) on a loopback port, behind a token made
for that one run. The film calls it like the local voice service:
POST {"text": "<one line>", "voice": "<id>"} -> {"audio": <base64 WAV>, "words": [...],
"take": {"voice", "engine", "fallback", "duration_s"}}. The ElevenLabs key stays in this
process: film_env strips every secret from the film.

- One provider per film: an engine that failed is skipped for the rest of the film, so its
  lines never switch voice engines midway (tts.EngineProvider).
- HTTPServer, not the threading one: one line at a time, as the brief asks.
- 503 when the machine failed (no answer, no credits, a 5xx: the brief retries once), 422
  when the engine refused the text, 404 without the token.
"""

from __future__ import annotations

import base64
import json
import secrets
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from ..config import InstagramMCPSettings
from ..studio import ffmpeg, guard, tts

USAGE = 'POST JSON {"text": "<one line>", "voice": "<id from voices.json>"}'


def _wav(audio: Path) -> bytes:
    """The take as 16-bit WAV (ElevenLabs answers MP3; the brief promises WAV)."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "take.wav"
        ffmpeg.run(["-i", audio, "-c:a", "pcm_s16le", out], timeout_s=60)
        return out.read_bytes()


class VoiceDoor:
    def __init__(self, settings: InstagramMCPSettings,
                 provider: Optional[tts.TTSProvider] = None):
        self.provider = provider or tts.get_provider(settings)
        self.token = secrets.token_urlsafe(16)
        door = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 - http.server's name
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                code, out = door.answer(self.path, body)
                data = json.dumps(out, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args: Any) -> None:  # quiet: the film logs its own calls
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}/{self.token}"

    def __enter__(self) -> "VoiceDoor":
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.server.shutdown()
        self.server.server_close()

    def answer(self, path: str, body: bytes) -> Tuple[int, Dict[str, Any]]:
        """(HTTP status, JSON answer) for a POST to `path`."""
        if not secrets.compare_digest(path.encode(), f"/{self.token}".encode()):
            return 404, {"error": "not found"}
        try:
            req = json.loads(body)
            text, voice = str(req["text"]).strip(), req.get("voice")
        except (ValueError, KeyError, TypeError):
            return 400, {"error": USAGE}
        if not text:
            return 400, {"error": USAGE}
        try:
            synth = self.provider.synthesize(text, voice)
            if synth.audio_path is None:
                return 503, {"error": "no voice engine is set up in the studio"}
            audio = _wav(synth.audio_path)
        except tts.TTSError as e:
            return (503 if e.machine else 422), {"error": str(e)}
        except (ffmpeg.FFmpegError, ffmpeg.FFmpegNotFound, guard.Stopped) as e:
            return 503, {"error": f"the take could not be turned into WAV: {e}"}
        return 200, {
            "audio": base64.b64encode(audio).decode("ascii"),
            "words": [{"text": w.text, "start_s": w.start_s, "end_s": w.end_s}
                      for w in synth.words or []],
            "take": {"voice": synth.voice,
                     "engine": "elevenlabs" if synth.provider == "elevenlabs" else "local",
                     "fallback": synth.fallback, "duration_s": synth.duration_s}}
