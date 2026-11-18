"""
Stock clips (step 064, GOAL.md §5.1): Pexels videos through its official API become
`licensed` clip sources with the licence, the credit line and whether ads may use them.

API (docs checked 2026-11-18, https://www.pexels.com/api/documentation/): the key goes in
an `Authorization: <key>` header (never in a URL, never logged); 200 requests/hour and
20,000/month by default. `GET /v1/videos/search` takes query, orientation
(portrait|landscape|square), size (large 4K | medium Full HD | small HD, a minimum),
locale, page, per_page (≤ 80): no duration filter, so durations are filtered here.
`GET /v1/videos/videos/:id` returns one video {id, width, height, url, image, duration,
user {name, url}, video_files [{quality, file_type, width, height, link}]}. File links
are on `player.vimeo.com` in the docs and on `videos.pexels.com` in today's answers: only
those hosts are fetched, over https, redirects not followed, under MAX_CLIP_MB.

Licence (https://www.pexels.com/license/): free, commercial use including ads and
marketing, modification allowed, attribution not required (we still credit the author).
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

import httpx

from ..config import InstagramMCPSettings
from ..store import CampaignStore
from .downloader import ProviderFailed, fetch_video
from .sources import LocalInboxProvider, with_attribution

API = "https://api.pexels.com/v1/videos"
TIMEOUT_S = 30.0
ORIENTATIONS = ("portrait", "landscape", "square")
TARGET_HEIGHT = 1920  # the studio renders 1080x1920: a bigger file is only a slower download
LICENCE = "Pexels License"
RIGHTS_NOTE = (
    "Pexels License (https://www.pexels.com/license/): free to use and modify, commercial "
    "use and ads allowed, attribution not required. Not allowed: selling unaltered copies, "
    "implying that people or brands shown endorse us, showing identifiable people in a bad "
    "light, redistributing it on stock sites, using it in a trademark.")


class NotConfigured(RuntimeError):
    """No PEXELS_API_KEY: the stock search is off."""


def configured(settings: InstagramMCPSettings) -> bool:
    key = settings.pexels_api_key
    return bool(key and key.get_secret_value().strip())


def file_host_ok(url: str) -> bool:
    """https on Pexels' own file hosts (the parsed host, never a substring)."""
    parts = urlsplit(url or "")
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and (host == "player.vimeo.com"
                                        or host.endswith(".pexels.com"))


def normalise(video: Dict[str, Any]) -> Dict[str, Any]:
    """One API video as {id, url, author, author_url, duration_s, width, height, image,
    files [{quality, file_type, width, height, link}]}."""
    user = video.get("user") or {}
    return {"id": video["id"], "url": video.get("url"), "author": user.get("name"),
            "author_url": user.get("url"), "duration_s": video.get("duration"),
            "width": video.get("width"), "height": video.get("height"),
            "image": video.get("image"),
            "files": [{k: f.get(k) for k in ("quality", "file_type", "width", "height", "link")}
                      for f in video.get("video_files") or [] if f.get("link")]}


def pick_files(files: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The portrait mp4 files in the order to try: the tallest up to TARGET_HEIGHT first,
    then bigger ones smallest first (the size cap may refuse the first ones)."""
    portrait = [f for f in files if f.get("file_type") == "video/mp4" and f.get("width")
                and f.get("height") and f["height"] > f["width"]]
    fit = sorted((f for f in portrait if f["height"] <= TARGET_HEIGHT),
                 key=lambda f: f["height"], reverse=True)
    return fit + sorted((f for f in portrait if f["height"] > TARGET_HEIGHT),
                        key=lambda f: f["height"])


class PexelsProvider(LocalInboxProvider):
    """Pexels videos as clips. The download lands in a temporary folder under the media
    root, then goes through the inbox checks (probe, size and length caps, atomic move)."""

    name = "pexels"

    def __init__(self, store: CampaignStore, settings: InstagramMCPSettings):
        if not configured(settings):
            raise NotConfigured("Stock clips are off: add PEXELS_API_KEY to .env (H4)")
        super().__init__(store, settings)
        self._headers = {"Authorization": settings.pexels_api_key.get_secret_value().strip()}

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        try:
            with httpx.Client(timeout=TIMEOUT_S, trust_env=False) as http:
                r = http.get(API + path, params=params, headers=self._headers)
            body = r.json() if r.status_code == 200 else None
        except (httpx.HTTPError, ValueError) as e:
            raise ValueError(f"Pexels could not be reached: {type(e).__name__}") from None
        if r.status_code == 404:
            raise KeyError("No Pexels video with this id")
        if r.status_code in (401, 403):
            raise ValueError("Pexels refused the API key: check PEXELS_API_KEY")
        if r.status_code == 429:
            raise ValueError("Pexels rate limit reached (200 requests an hour): try later")
        if r.status_code != 200 or not isinstance(body, dict):
            raise ValueError(f"Pexels answered HTTP {r.status_code}")
        return body

    def search(self, query: str, *, orientation: str = "portrait",
               min_duration: Optional[float] = None, max_duration: Optional[float] = None,
               per_page: int = 15, page: int = 1) -> List[Dict[str, Any]]:
        """Normalised videos for `query` (at least Full HD), filtered by duration here."""
        if not (query or "").strip():
            raise ValueError("query is required")
        if orientation not in ORIENTATIONS:
            raise ValueError(f"orientation must be one of {', '.join(ORIENTATIONS)}")
        if not 1 <= per_page <= 80 or page < 1:
            raise ValueError("per_page must be 1-80 and page at least 1")
        body = self._get("/search", {"query": query.strip(), "orientation": orientation,
                                     "size": "medium", "per_page": per_page, "page": page})
        out = [normalise(v) for v in body.get("videos") or []]
        return [v for v in out if (min_duration is None or (v["duration_s"] or 0) >= min_duration)
                and (max_duration is None or (v["duration_s"] or 0) <= max_duration)]

    def ingest(self, item: str, **_: Any) -> Dict[str, Any]:
        """Download Pexels video `item` (its id) and store it as a `licensed` clip; the
        clip already stored for that id is returned as is."""
        video_id = int(str(item).strip())  # ValueError for anything but an id
        done = [s for s in self.store._select("SELECT * FROM sources",
                                              {"provider": self.name,
                                               "external_id": str(video_id)}, "id", 1)
                if s.get("local_path")]
        if done:
            return done[0]
        video = normalise(self._get(f"/videos/{video_id}"))
        author = (video["author"] or "").strip() or "Pexels"
        max_bytes = int(self.settings.max_clip_mb * 1_000_000)
        root = Path(self.settings.media_root)
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root, prefix=".stock-") as tmp:
            path = Path(tmp) / f"pexels-{video_id}.mp4"
            errors = []
            for f in pick_files(video["files"]):
                try:
                    fetch_video(f["link"], path, max_bytes, host_ok=file_host_ok,
                                hosts="a Pexels file host")
                    break
                except ProviderFailed as e:
                    errors.append(f"{f['width']}x{f['height']}: {e}")
            else:
                raise ValueError("no portrait file of this video could be downloaded"
                                 + (f" ({'; '.join(errors)})" if errors else ""))
            return self.ingest_file(
                path, rights_basis="licensed", rights_note=RIGHTS_NOTE,
                # the licence covers the file, but stock sound may hold third-party music:
                # muted unless the clip is silent anyway (then no_audio)
                audio_rights="not_covered", author=author, url=video["url"], licence=LICENCE,
                external_id=str(video_id),
                extra_stats={"attribution": f"Video by {author} on Pexels",
                             "author_url": video["author_url"], "ads_allowed": True,
                             "licence_url": "https://www.pexels.com/license/"})


def search(store: CampaignStore, settings: InstagramMCPSettings, query: str,
           **kwargs: Any) -> List[Dict[str, Any]]:
    return PexelsProvider(store, settings).search(query, **kwargs)


def add_clip(store: CampaignStore, settings: InstagramMCPSettings,
             result_id: int) -> Dict[str, Any]:
    """The `licensed` clip of Pexels video `result_id`, with its licence and credit."""
    return with_attribution(PexelsProvider(store, settings).ingest(str(result_id)))
