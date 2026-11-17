"""
Reel downloads for reactions (step 063b, GOAL.md §5.1): a public Reel permalink (a
watchlist find, a trend result, an owner inspiration, a DM pick) becomes a `clip` source
with `rights_basis = commentary`, its creator and stats, and the video in
`<media_root>/sources/<id>/clip.mp4`.

Two ClipDownloader providers, tried in order: `reels_downloader` (the local service of
063a, logged out) and `ytdlp` (optional extra `download`; the only one that may use
DOWNLOADER_COOKIES_FILE, a separate personal account, never the brand account). A
provider only finds the video URL; this module fetches it, from Instagram's CDN only, over
https, under MAX_DOWNLOAD_MB. No provider ever gets our Instagram token.

Response of the service (`GET /api/video?postUrl=&enhanced=true`, vendored source at
c36c205): {success, data: {title (caption), view_count, like_count, duration,
owner {username, is_private}, medias [{type, url}]}}; errors {status: error, message} with
400 "This post is not a video" and 401 "Video link for this post is not public." (which
it also says when Instagram blocks it, so a 401 falls through to yt-dlp).
"""

from __future__ import annotations

import os
import re
import time
from datetime import datetime, timedelta
from datetime import time as dtime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol, Tuple, Union
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import httpx

from ..config import InstagramMCPSettings
from ..store import CampaignStore, parse_dt, to_iso
from . import downloader_service, media
from .sources import check_rights

PROVIDER = "instagram_reel"  # sources.provider of a Reel first seen by a download
CDN_HOSTS = ("cdninstagram.com", "fbcdn.net")
TIMEOUT_S = 60.0
CHUNK = 1 << 16
CAPTION_MAX = 2200  # Instagram's own caption limit
_PERMALINK = re.compile(
    r"https://(?:www\.)?instagram\.com/(reels?|p|tv)/([A-Za-z0-9_-]+)/?(?:[?#].*)?")


class Refused(Exception):
    """The Reel may not be downloaded (private, not a video): no other provider tries."""


class ProviderFailed(Exception):
    """This provider could not get the video: the next one tries."""


class ClipDownloader(Protocol):
    name: str

    def version(self) -> str: ...

    def find(self, url: str) -> Dict[str, Any]:
        """{video_url, author, caption, views, likes, duration_s} of a public Reel;
        Refused or ProviderFailed otherwise."""


def permalink(url: str) -> str:
    """The canonical https://www.instagram.com/(reel|p)/<code>/ form; ValueError otherwise."""
    m = _PERMALINK.fullmatch((url or "").strip())
    if not m:
        raise ValueError("not a Reel link: https://www.instagram.com/reel/<code>/ (or /p/)")
    return f"https://www.instagram.com/{'p' if m[1] == 'p' else 'reel'}/{m[2]}/"


def _same_post(url: str) -> List[str]:
    code = permalink(url).rstrip("/").rsplit("/", 1)[1]
    return [f"https://www.instagram.com/{kind}/{code}/" for kind in ("reel", "p")]


def cdn_ok(url: str) -> bool:
    """https on an Instagram CDN host (the parsed host, never a substring)."""
    parts = urlsplit(url or "")
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and any(host == h or host.endswith("." + h)
                                           for h in CDN_HOSTS)


class ReelsDownloaderProvider:
    """The vendored service on 127.0.0.1 (063a). It gets the permalink, nothing else."""

    name = "reels_downloader"

    def __init__(self, settings: InstagramMCPSettings):
        self.url = f"http://{downloader_service.HOST}:{settings.downloader_port}/api/video"

    def version(self) -> str:
        try:
            return (downloader_service.commit() or "unknown")[:12]
        except downloader_service.DownloaderError:
            return "unknown"

    def find(self, url: str) -> Dict[str, Any]:
        try:
            with httpx.Client(timeout=TIMEOUT_S, trust_env=False) as http:
                r = http.get(self.url, params={"postUrl": url, "enhanced": "true"})
            body = r.json()
        except httpx.ConnectError:
            raise ProviderFailed("the downloader service is not running") from None
        except (httpx.HTTPError, ValueError) as e:
            raise ProviderFailed(f"the downloader service failed: {type(e).__name__}") from None
        message = str(body.get("message") or "")[:200] if isinstance(body, dict) else ""
        if r.status_code == 400 and "not a video" in message:
            raise Refused("not a video")
        if r.status_code != 200:
            raise ProviderFailed(f"downloader service: HTTP {r.status_code} {message}".strip())
        try:
            data = body["data"]
            owner = data.get("owner") or {}
            video = next((m["url"] for m in data.get("medias") or []
                          if m.get("type") == "video" and m.get("url")), None)
        except (KeyError, TypeError, AttributeError):
            raise ProviderFailed("the downloader service gave an unreadable answer") from None
        if owner.get("is_private"):
            raise Refused("private account")
        if not video:
            raise Refused("not a video")
        if not owner.get("username"):  # its page fallback knows no creator: credit needs one
            raise ProviderFailed("the downloader service found no creator username")
        return {"video_url": video, "author": owner["username"], "caption": data.get("title"),
                "views": data.get("view_count"), "likes": data.get("like_count"),
                "duration_s": data.get("duration") or None}


class YtDlpProvider:
    """yt-dlp, imported lazily (optional extra `download`). Asked for the info only:
    the file itself is fetched by fetch_video like any other provider's."""

    name = "ytdlp"

    def __init__(self, settings: InstagramMCPSettings):
        self.cookies = settings.downloader_cookies_file

    def version(self) -> str:
        try:
            from yt_dlp.version import __version__
        except ImportError:
            return "not installed"
        return __version__

    def find(self, url: str) -> Dict[str, Any]:
        try:
            import yt_dlp
        except ImportError:
            raise ProviderFailed('yt-dlp is not installed (pip install -e ".[download]")') from None
        opts: Dict[str, Any] = {"quiet": True, "no_warnings": True, "noplaylist": True}
        if self.cookies:
            opts["cookiefile"] = self.cookies
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception as e:  # yt-dlp raises DownloadError, ExtractorError and others
            text = str(e)[:300]
            if "private" in text.lower():
                raise Refused("private account") from None
            raise ProviderFailed(f"yt-dlp: {text}") from None
        if info.get("_type") == "playlist" or info.get("availability") == "private":
            raise Refused("private account" if info.get("availability") == "private"
                          else "not a single video (a carousel)")
        # One file with picture and sound (DASH parts would need a merge), best first.
        videos = [f for f in info.get("formats") or [info]
                  if f.get("url") and f.get("vcodec") not in (None, "none")]
        if not videos:
            raise Refused("not a video")
        formats = [f for f in videos if f.get("acodec") != "none"]
        if not formats:
            raise ProviderFailed("yt-dlp found no single file with picture and sound")
        best = max(formats, key=lambda f: (f.get("height") or 0, f.get("tbr") or 0))
        if not info.get("channel"):
            raise ProviderFailed("yt-dlp found no creator username")
        return {"video_url": best["url"], "author": info["channel"],
                "caption": info.get("description"), "views": info.get("view_count"),
                "likes": info.get("like_count"), "duration_s": info.get("duration")}


def fetch_video(url: str, dest: Path, max_bytes: int) -> int:
    """Stream the video to `dest` (bytes written). ProviderFailed for a non-CDN URL, an
    HTTP error or a file over the cap; nothing is left behind then."""
    if not cdn_ok(url):
        raise ProviderFailed(f"video host {urlsplit(url).hostname!r} is not Instagram's CDN")
    part = dest.with_name(dest.name + ".part")
    dest.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    try:
        # no redirects followed: a 3xx to another host is an error, never a fetch
        with httpx.Client(timeout=TIMEOUT_S, trust_env=False) as http, \
                http.stream("GET", url) as r:
            if r.status_code != 200:
                raise ProviderFailed(f"the CDN answered HTTP {r.status_code}")
            if int(r.headers.get("content-length") or 0) > max_bytes:
                raise ProviderFailed(f"the video is larger than {max_bytes / 1e6:g} MB")
            with open(part, "wb") as f:
                for chunk in r.iter_bytes(CHUNK):
                    size += len(chunk)
                    if size > max_bytes:
                        raise ProviderFailed(f"the video is larger than {max_bytes / 1e6:g} MB")
                    f.write(chunk)
        os.replace(part, dest)
    except httpx.HTTPError as e:
        part.unlink(missing_ok=True)
        raise ProviderFailed(f"the CDN download failed: {type(e).__name__}") from None
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    return size


def providers(settings: InstagramMCPSettings) -> List[ClipDownloader]:
    return [ReelsDownloaderProvider(settings), YtDlpProvider(settings)]


def _today_downloads(store: CampaignStore, settings: InstagramMCPSettings,
                     now: datetime) -> List[str]:
    tz = ZoneInfo(settings.timezone)
    start = datetime.combine(now.astimezone(tz).date(), dtime(), tz)
    with store._tx() as c:
        return [r[0] for r in c.execute(
            "SELECT downloaded_at FROM sources WHERE downloaded_at >= ?"
            " ORDER BY downloaded_at", (to_iso(start),))]


def _find_source(store: CampaignStore, source_or_url: Union[int, str]
                 ) -> Tuple[str, Optional[Dict[str, Any]]]:
    """(permalink, the source already holding this Reel or None)."""
    if isinstance(source_or_url, int) or str(source_or_url).strip().isdigit():
        source = store.get_source(int(source_or_url))  # KeyError: no such source
        return permalink(source.get("url") or ""), source
    url = permalink(str(source_or_url))
    with store._tx() as c:  # the file-holding row first
        row = c.execute("SELECT id FROM sources WHERE url IN (?, ?)"
                        " ORDER BY local_path IS NULL, id LIMIT 1", _same_post(url)).fetchone()
    return url, store.get_source(row[0]) if row else None


def _record_failure(store: CampaignStore, source_id: int, reason: str, now: datetime) -> None:
    store.patch_source_stats(source_id, {"download_error": reason[:500],
                                         "download_failed_at": to_iso(now)})


def _mark_picks(store: CampaignStore, url: str, result: Dict[str, Any]) -> None:
    """DM picks (113) of this Reel still `new`: downloaded with the source, or skipped with
    the refusal. A failure leaves them new (the next run retries). 113b does the rest."""
    status = result["status"]
    if status not in ("downloaded", "exists", "refused"):
        return
    post = _same_post(url)
    with store._tx() as c:
        picks = [r[0] for r in c.execute("SELECT id, reel_url FROM dm_picks WHERE status='new'")
                 if _PERMALINK.fullmatch(r[1]) and permalink(r[1]) in post]
    for pick_id in picks:
        if status == "refused":
            store._update("dm_picks", ("status", "skip_reason"), pick_id,
                          {"status": "skipped", "skip_reason": result["reason"][:300]})
        else:
            store._update("dm_picks", ("status", "skip_reason", "source_id"), pick_id,
                          {"status": "downloaded", "skip_reason": None,
                           "source_id": result["source"]["id"]})


def download_reel(store: CampaignStore, settings: InstagramMCPSettings,
                  source_or_url: Union[int, str], *, now: datetime,
                  sleep: Callable[[float], None] = time.sleep,
                  downloaders: Optional[List[ClipDownloader]] = None) -> Dict[str, Any]:
    """Download one public Reel (a source id or a permalink) for a reaction. Returns
    {status: downloaded | exists | refused | failed, source?, reason?, provider?}.
    ValueError for a link that is not a Reel permalink, KeyError for an unknown source id.
    A Reel already stored with its file is reused; a failure is written on the source
    (stats.download_error) and the owner can drop the file into the inbox instead."""
    url, source = _find_source(store, source_or_url)
    root = Path(settings.media_root)
    if source and source.get("local_path") and media.resolve(root, source["local_path"]).is_file():
        result: Dict[str, Any] = {"status": "exists", "source": source}
        _mark_picks(store, url, result)
        return result

    done_today = _today_downloads(store, settings, now)
    if len(done_today) >= settings.max_downloads_per_day:
        return {"status": "refused", "cap_reached": True, "source": source,
                "reason": f"daily cap reached ({settings.max_downloads_per_day} downloads)"}
    if done_today:  # a pause between downloads, never a burst
        wait = settings.download_delay_s - (now - parse_dt(done_today[-1])).total_seconds()
        if wait > 0:
            sleep(wait)
            now += timedelta(seconds=wait)

    if source is None:
        source = store.add_source(PROVIDER, role="clip", url=url)
    folder = root / "sources" / str(source["id"])
    errors = []
    for provider in downloaders if downloaders is not None else providers(settings):
        try:
            reel = provider.find(url)
            size = fetch_video(reel["video_url"], folder / "clip.mp4",
                               int(settings.max_download_mb * 1_000_000))
        except Refused as e:
            reason = f"{provider.name}: {e}"
            _record_failure(store, source["id"], reason, now)
            result = {"status": "refused", "reason": str(e), "provider": provider.name,
                      "source": store.get_source(source["id"])}
            _mark_picks(store, url, result)
            return result
        except ProviderFailed as e:
            errors.append(f"{provider.name}: {e}")
            continue
        author = reel["author"]
        note = (f"Public Reel by @{author} ({url}), downloaded for a reaction: commentary "
                f"use only, credit @{author} on screen and in the caption.")
        check_rights("commentary", note, author=author)
        stats = {"permalink": url, "caption": (reel.get("caption") or "")[:CAPTION_MAX],
                 "views": reel.get("views"), "likes": reel.get("likes"),
                 "duration_s": reel.get("duration_s"), "size_bytes": size}
        stats = {k: v for k, v in stats.items() if v not in (None, "")}  # keep research's
        stats.update(download_error=None, download_failed_at=None)  # null = key removed
        with store._tx() as c:  # ponytail: a store setter once store.py is free
            c.execute(
                "UPDATE sources SET role='clip', author=?, rights_basis='commentary',"
                " rights_note=?, audio_rights='not_covered', local_path=?, downloaded_at=?,"
                " downloader_version=? WHERE id=?",
                (author, note, media.relative(root, folder / "clip.mp4"), to_iso(now),
                 f"{provider.name} {provider.version()}", source["id"]))
        store.patch_source_stats(source["id"], stats)
        result = {"status": "downloaded", "provider": provider.name,
                  "source": store.get_source(source["id"])}
        _mark_picks(store, url, result)
        return result

    reason = "; ".join(errors) or "no downloader configured"
    _record_failure(store, source["id"], reason, now)
    return {"status": "failed", "source": store.get_source(source["id"]),
            "reason": reason + ". Save the video yourself and drop it into the inbox folder."}
