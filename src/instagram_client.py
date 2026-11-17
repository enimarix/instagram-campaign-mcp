"""
Instagram Graph API client (Instagram API with Facebook Login).

Covers what an organic campaign needs:
- publishing: single image, carousel (2-10 items), Reels (incl. trial Reels), Stories
- container status polling (videos are processed asynchronously)
- per-media insights with the metric set that matches the media product type
- comment moderation, hashtag research, competitor lookup (Business Discovery)
- DMs (needs instagram_manage_messages)

All methods return plain dicts so they serialise straight into MCP tool results.
"""

from __future__ import annotations

import asyncio
import copy
import json
import re
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Iterable, List, Optional
from urllib.parse import urlencode, urlparse
from zoneinfo import ZoneInfo

import httpx
import structlog

from .config import InstagramMCPSettings, get_settings
from .store import CampaignStore
from .studio import media

logger = structlog.get_logger(__name__)

# Graph error codes that mean "slow down".
RATE_LIMIT_CODES = {4, 17, 32, 613, 80002}
# Meta's insights day (and online_followers hour keys) is Pacific time.
META_INSIGHTS_TZ = ZoneInfo("America/Los_Angeles")
# Media insights: metric set per media_product_type (Graph API v25+).
# `impressions`, `video_views`, `plays` are deprecated and intentionally absent.
INSIGHT_METRICS: Dict[str, List[str]] = {
    "FEED": [
        "reach", "views", "likes", "comments", "saved", "shares",
        "follows", "profile_visits", "total_interactions",
    ],
    "REELS": [
        "reach", "views", "likes", "comments", "saved", "shares",
        "total_interactions", "ig_reels_avg_watch_time",
    ],
    "STORY": [
        "reach", "views", "shares", "follows", "profile_visits",
        "replies", "total_interactions",
    ],
}
MEDIA_FIELDS = (
    "id,caption,media_type,media_product_type,media_url,thumbnail_url,"
    "permalink,timestamp,like_count,comments_count"
)
HASHTAG_RE = re.compile(r"#\w+")
# Feed images may have any aspect ratio from 4:5 (0.8) to 1.91:1, small slack
# for rounding (e.g. 1080x1351).
FEED_RATIO_RANGE = (0.795, 1.915)
# Meta's content publishing API only takes JPEG images. PIL reports some
# camera JPEGs (multi-picture) as MPO.
JPEG_FORMATS = {"JPEG", "MPO"}
# Meta puts the error code of a failed container in its status text,
# e.g. "Error: 2207026" - pull it out so callers can tell permanent failures.
CONTAINER_SUBCODE_RE = re.compile(r"\b(220\d{4})\b")
# Publishing-quota subcode: ~100 API posts per rolling 24h.
PUBLISH_QUOTA_SUBCODE = 2207042
# Code 100 + subcode 33: "Object with ID ... does not exist" (e.g. the owner deleted a post).
MISSING_OBJECT = (100, 33)
# Reels from local files: resumable upload ("rupload") of the bytes, then the usual polling.
RUPLOAD_URL = "https://rupload.facebook.com/ig-api-upload/{version}/{container_id}"
RUPLOAD_HOSTS = (".facebook.com", ".instagram.com")  # where we send the OAuth token
REEL_MAX_BYTES = 300 * 1024 * 1024  # IG User Media reference, Reel specs
UPLOAD_ATTEMPTS = 3
UPLOAD_CHUNK = 1024 * 1024


class InstagramAPIError(Exception):
    """Graph API error with Meta's code/subcode kept for diagnosis."""

    def __init__(
        self,
        message: str,
        error_code: Optional[int] = None,
        error_subcode: Optional[int] = None,
    ):
        self.message = message
        self.error_code = error_code
        self.error_subcode = error_subcode
        # True when the request may or may not have reached Meta (timeout,
        # dropped connection).
        self.network = False
        # True only when the network failure hit the final media_publish call:
        # the post may be live, so retrying could double-post.
        self.maybe_published = False
        super().__init__(message)


class RateLimitExceeded(InstagramAPIError):
    """Raised when Meta reports a rate limit (or the client-side cap is hit)."""


class NotConfigured(InstagramAPIError):
    """No access token yet (setup mode): Graph calls are impossible."""


NOT_CONFIGURED_MSG = (
    "instagram_not_configured: set INSTAGRAM_ACCESS_TOKEN and "
    "INSTAGRAM_BUSINESS_ACCOUNT_ID in .env"
)


class InvalidMedia(InstagramAPIError):
    """Rejected locally before calling Meta (bad caption, format, ratio...).
    Retrying the same post can never succeed."""


class RequestBudget:
    """Sliding-window cap on requests per hour.

    With a `store` the window lives in the database (graph_requests), so the worker, the
    API and the MCP server share one cap; without one it is this process's own.
    When the window is full it waits if a slot frees up within `max_wait`
    seconds; otherwise it raises RateLimitExceeded right away instead of
    silently blocking a tool call (or the scheduler) for up to an hour.
    """

    def __init__(self, per_hour: int, max_wait: float = 30.0, period: float = 3600.0,
                 store: Optional[CampaignStore] = None):
        self.per_hour = max(1, int(per_hour))
        self.period = period
        self.max_wait = max_wait
        self.store = store
        self._log: deque = deque()

    def _take(self, now: float) -> float:
        """Count one request: 0.0, or the seconds until a slot frees up (nothing counted)."""
        if self.store is not None:
            return self.store.take_request_slot(now, self.period, self.per_hour)
        while self._log and now - self._log[0] >= self.period:
            self._log.popleft()
        if len(self._log) < self.per_hour:
            self._log.append(now)
            return 0.0
        return self.period - (now - self._log[0])

    def used(self) -> int:
        """Requests counted in the current window."""
        since = time.time() - self.period
        if self.store is not None:
            return self.store.graph_requests_since(since)
        return sum(1 for t in self._log if t > since)

    async def acquire(self) -> None:
        while True:
            wait = self._take(time.time())
            if wait <= 0:
                return
            if wait > self.max_wait:
                raise RateLimitExceeded(
                    f"Client-side cap of {self.per_hour} requests/hour reached; next "
                    f"slot in {wait / 60:.0f} min (RATE_LIMIT_REQUESTS_PER_HOUR)."
                )
            await asyncio.sleep(wait)


class InstagramClient:
    """Async Graph API client with throttling, light caching and clear errors."""

    def __init__(
        self,
        settings: Optional[InstagramMCPSettings] = None,
        http_client: Optional[httpx.AsyncClient] = None,
        store: Optional[CampaignStore] = None,
    ):
        """`store`: count requests in its shared budget (else a per-process one)."""
        self.settings = settings or get_settings()
        self.base_url = self.settings.instagram_api_url
        self.access_token = self.settings.instagram_access_token
        if not self.access_token:
            raise NotConfigured(NOT_CONFIGURED_MSG)
        self.budget = RequestBudget(self.settings.rate_limit_requests_per_hour, store=store)
        self.client = http_client or httpx.AsyncClient(
            timeout=httpx.Timeout(60.0),
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
        )
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._page_tokens: Dict[str, str] = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def close(self):
        await self.client.aclose()

    # ------------------------------------------------------------------
    # Low-level request
    # ------------------------------------------------------------------
    @property
    def account_id(self) -> str:
        account_id = self.settings.instagram_business_account_id
        if not account_id:
            raise InstagramAPIError(
                "INSTAGRAM_BUSINESS_ACCOUNT_ID is not configured. "
                "Run get_account_pages to find it."
            )
        return account_id

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        use_cache: bool = False,
        token: Optional[str] = None,
    ) -> Dict[str, Any]:
        params = dict(params or {})
        method = method.upper()
        cache_key = f"{endpoint}?{urlencode(sorted(params.items()))}"
        use_cache = use_cache and token is None and self.settings.cache_enabled

        if method == "GET" and use_cache:
            entry = self._cache.get(cache_key)
            if entry and entry["expires"] > time.monotonic():
                # Copy so callers can't mutate the cached response.
                return copy.deepcopy(entry["data"])

        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        headers = {"Authorization": f"Bearer {token or self.access_token}"}

        if method not in ("GET", "POST", "DELETE"):
            raise ValueError(f"Unsupported HTTP method: {method}")
        await self.budget.acquire()
        try:
            if method == "GET":
                response = await self.client.get(url, params=params, headers=headers)
            elif method == "POST":
                response = await self.client.post(
                    url, params=params, json=data or None, headers=headers
                )
            else:
                response = await self.client.delete(url, params=params, headers=headers)
        except httpx.RequestError as e:
            err = InstagramAPIError(f"HTTP request failed: {e!r}")
            err.network = True
            raise err from e

        try:
            payload = response.json()
        except (json.JSONDecodeError, ValueError) as e:
            if response.status_code == 429:
                raise RateLimitExceeded("Instagram API rate limit exceeded", 429) from e
            raise InstagramAPIError(
                f"Invalid JSON response (HTTP {response.status_code})"
            ) from e

        if isinstance(payload, dict) and "error" in payload:
            err = payload["error"]
            code = err.get("code")
            subcode = err.get("error_subcode")
            msg = err.get("error_user_msg") or err.get("message", "Unknown error")
            logger.warning("graph_error", endpoint=endpoint, code=code, subcode=subcode)
            exc_cls = RateLimitExceeded if code in RATE_LIMIT_CODES else InstagramAPIError
            raise exc_cls(msg, code, subcode)

        if response.status_code == 429:
            raise RateLimitExceeded("Instagram API rate limit exceeded", 429)
        if response.status_code >= 400:
            raise InstagramAPIError(f"HTTP {response.status_code} from {endpoint}")
        if not isinstance(payload, dict):
            raise InstagramAPIError(f"Unexpected response from {endpoint}: {payload!r}")

        if method == "GET" and use_cache:
            self._cache[cache_key] = {
                "data": copy.deepcopy(payload),
                "expires": time.monotonic() + self.settings.cache_ttl_seconds,
            }
        return payload

    # ------------------------------------------------------------------
    # Account
    # ------------------------------------------------------------------
    async def validate_access_token(self) -> bool:
        try:
            await self._make_request("GET", "me", params={"fields": "id"})
            return True
        except InstagramAPIError:
            return False

    async def get_account_pages(self) -> List[Dict[str, Any]]:
        data = await self._make_request(
            "GET",
            "me/accounts",
            params={"fields": "id,name,instagram_business_account{id,username}"},
        )
        return data.get("data", [])

    async def get_profile_info(self, account_id: Optional[str] = None) -> Dict[str, Any]:
        fields = (
            "id,username,name,biography,website,profile_picture_url,"
            "followers_count,follows_count,media_count"
        )
        return await self._make_request(
            "GET", account_id or self.account_id, params={"fields": fields}, use_cache=True
        )

    async def get_account_insights(
        self,
        metrics: Optional[List[str]] = None,
        period: str = "day",
        since: Optional[int] = None,
        until: Optional[int] = None,
        breakdown: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        metrics = metrics or ["reach", "views", "accounts_engaged", "total_interactions"]
        params: Dict[str, Any] = {
            "metric": ",".join(metrics),
            "period": period,
            "metric_type": "total_value",
        }
        if since:
            params["since"] = since
        if until:
            params["until"] = until
        if breakdown:
            params["breakdown"] = breakdown
        data = await self._make_request(
            "GET", f"{self.account_id}/insights", params=params
        )
        return data.get("data", [])

    async def get_online_followers(self) -> Optional[Dict[int, int]]:
        """Followers online per UTC hour (0-23) on the latest day Meta reports, or None.

        Meta no longer lists `online_followers` in the IG User insights metric table; its
        limitations still name it (accounts with 100+ followers, last 30 days only, empty
        data set when unavailable). Hour keys are Meta's insights day, Pacific time, so
        they are shifted to UTC here. None on an empty data set or "invalid metric" (#100).
        """
        try:
            data = await self._make_request(
                "GET",
                f"{self.account_id}/insights",
                params={"metric": "online_followers", "period": "lifetime"},
            )
        except InstagramAPIError as e:
            if e.error_code != 100:
                raise
            logger.info("online_followers_unavailable", error=e.message)
            return None
        values = [
            v for item in data.get("data", []) for v in item.get("values", [])
            if isinstance(v.get("value"), dict) and v["value"]
        ]
        if not values:
            return None
        latest = max(values, key=lambda v: v.get("end_time", ""))
        end = latest.get("end_time")
        # ponytail: one offset for the whole day (noon of the day that ends at end_time);
        # the hour around a DST switch lands one bucket off, harmless for an average.
        ref = (datetime.strptime(end, "%Y-%m-%dT%H:%M:%S%z") - timedelta(hours=12)
               if end else datetime.now(timezone.utc))
        offset = int(ref.astimezone(META_INSIGHTS_TZ).utcoffset().total_seconds() // 3600)
        return {(int(h) - offset) % 24: int(n) for h, n in latest["value"].items()}

    async def get_publishing_limit(self) -> Dict[str, Any]:
        data = await self._make_request(
            "GET",
            f"{self.account_id}/content_publishing_limit",
            params={"fields": "config,quota_usage"},
        )
        items = data.get("data", [])
        return items[0] if items else {}

    # ------------------------------------------------------------------
    # Media read
    # ------------------------------------------------------------------
    async def get_media_posts(
        self, limit: int = 25, after: Optional[str] = None
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {"fields": MEDIA_FIELDS, "limit": min(limit, 100)}
        if after:
            params["after"] = after
        data = await self._make_request("GET", f"{self.account_id}/media", params=params)
        return {
            "posts": data.get("data", []),
            "next_cursor": data.get("paging", {}).get("cursors", {}).get("after"),
        }

    async def get_media(self, media_id: str) -> Dict[str, Any]:
        return await self._make_request("GET", media_id, params={"fields": MEDIA_FIELDS})

    async def get_media_insights(
        self,
        media_id: str,
        metrics: Optional[List[str]] = None,
        media_product_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return {metric: value}. Picks the right metrics for FEED/REELS/STORY.

        If Meta rejects one metric in the batch (it fails the whole request),
        the metrics are retried one at a time and unsupported ones are reported
        under `unavailable`.
        """
        if not metrics:
            if not media_product_type:
                media = await self.get_media(media_id)
                media_product_type = media.get("media_product_type", "FEED")
            metrics = INSIGHT_METRICS.get(media_product_type, INSIGHT_METRICS["FEED"])

        values: Dict[str, Any] = {}
        unavailable: Dict[str, str] = {}
        try:
            data = await self._make_request(
                "GET", f"{media_id}/insights", params={"metric": ",".join(metrics)}
            )
            values.update(_parse_insights(data.get("data", [])))
        except RateLimitExceeded:
            raise
        except InstagramAPIError:
            for metric in metrics:
                try:
                    data = await self._make_request(
                        "GET", f"{media_id}/insights", params={"metric": metric}
                    )
                    values.update(_parse_insights(data.get("data", [])))
                except RateLimitExceeded:
                    raise
                except InstagramAPIError as e:
                    unavailable[metric] = e.message
            if not values:
                # Every metric failed: the media itself is the problem (bad id,
                # no permission...). Don't pass that off as "no metrics".
                raise
        return {
            "media_id": media_id,
            "media_product_type": media_product_type,
            "metrics": values,
            "unavailable": unavailable,
        }

    # ------------------------------------------------------------------
    # Publishing
    # ------------------------------------------------------------------
    async def _create_container(self, payload: Dict[str, Any]) -> str:
        return _require_id(await self._create_container_data(payload), "media container")

    async def _create_container_data(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        clean = {k: v for k, v in payload.items() if v is not None}
        return await self._make_request("POST", f"{self.account_id}/media", data=clean)

    def _local_video(self, rel: str) -> Path:
        """A Reel file under the media root, checked before any network call."""
        try:
            path = media.resolve(self.settings.media_root, rel)
        except ValueError as e:
            raise InvalidMedia(f"video_path must be relative to the media root: {e}") from e
        if not path.is_file():
            raise InvalidMedia(f"video_path {rel!r} is not a file under the media root")
        size = path.stat().st_size
        if not 0 < size <= REEL_MAX_BYTES:
            raise InvalidMedia(f"Reel file is {size} bytes; Instagram takes 1 byte to 300 MB")
        return path

    async def _upload_video(self, container_id: str, uri: Optional[str], path: Path) -> None:
        """POST the file to the resumable-upload endpoint, retrying transient failures
        (network, 5xx/429, debug_info.retriable) with the polling backoff."""
        host = urlparse(uri or "").hostname or ""
        if not (uri and uri.startswith("https://") and host.endswith(RUPLOAD_HOSTS)):
            uri = RUPLOAD_URL.format(version=self.settings.instagram_api_version,
                                     container_id=container_id)
        size = path.stat().st_size
        headers = {
            "Authorization": f"OAuth {self.access_token}",
            "offset": "0",
            "file_size": str(size),
            "Content-Length": str(size),
        }
        delay = max(self.settings.container_poll_interval_seconds, 0.0)
        for attempt in range(1, UPLOAD_ATTEMPTS + 1):
            await self.budget.acquire()
            try:
                resp = await self.client.post(uri, content=_read_chunks(path), headers=headers)
            except httpx.RequestError as e:
                message, retriable = f"{e!r}", True
            else:
                try:
                    body = resp.json()
                except ValueError:
                    body = {}
                body = body if isinstance(body, dict) else {}
                if resp.is_success and body.get("success") is not False:
                    return
                info = body.get("debug_info") or {}
                message = info.get("message") or f"HTTP {resp.status_code}"
                retriable = (bool(info.get("retriable")) or resp.status_code == 429
                             or resp.status_code >= 500)
            if not retriable or attempt == UPLOAD_ATTEMPTS:
                raise InstagramAPIError(
                    f"Reel upload failed after {attempt} attempt(s): {message}")
            logger.warning("reel_upload_retry", container_id=container_id,
                           attempt=attempt, error=message)
            await asyncio.sleep(delay)
            delay = min(delay * 1.5, 30.0)

    async def get_container_status(self, container_id: str) -> Dict[str, Any]:
        return await self._make_request(
            "GET", container_id, params={"fields": "status_code,status"}
        )

    async def wait_for_container(self, container_id: str) -> Dict[str, Any]:
        """Poll until FINISHED. Raises on ERROR/EXPIRED or timeout.

        The interval grows by half each poll (capped at 30s) so a long video
        doesn't burn the hourly request budget on status checks.
        """
        deadline = time.monotonic() + self.settings.container_timeout_seconds
        interval = max(self.settings.container_poll_interval_seconds, 0.0)
        while True:
            status = await self.get_container_status(container_id)
            code = status.get("status_code")
            if code in ("FINISHED", "PUBLISHED"):
                return status
            if code in ("ERROR", "EXPIRED"):
                detail = status.get("status") or "no detail"
                match = CONTAINER_SUBCODE_RE.search(detail)
                raise InstagramAPIError(
                    f"Container {container_id} {code}: {detail}",
                    error_subcode=int(match.group(1)) if match else None,
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise InstagramAPIError(
                    f"Container {container_id} still {code} after "
                    f"{self.settings.container_timeout_seconds:.0f}s"
                )
            await asyncio.sleep(min(interval, remaining))
            interval = min(interval * 1.5, 30.0)

    async def _publish_container(self, container_id: str) -> Dict[str, Any]:
        await self.wait_for_container(container_id)
        try:
            data = await self._make_request(
                "POST",
                f"{self.account_id}/media_publish",
                data={"creation_id": container_id},
            )
        except RateLimitExceeded:
            raise
        except InstagramAPIError as e:
            if e.network:
                # The request may still be running at Meta: assume it might post.
                e.maybe_published = True
            elif await self._container_published(container_id):
                # Meta sometimes publishes and still answers with an error
                # ("unknown error", "service unavailable"): never retry those.
                e.maybe_published = True
                e.message = f"{e.message} (but Instagram reports the post as published)"
            raise
        media_id = _require_id(data, "media_publish")
        result: Dict[str, Any] = {"media_id": media_id, "container_id": container_id}
        try:
            media = await self.get_media(media_id)
            result["permalink"] = media.get("permalink")
            result["media_product_type"] = media.get("media_product_type")
        except InstagramAPIError:
            pass
        return result

    async def _container_published(self, container_id: str) -> bool:
        """After a failed media_publish: did the container get published anyway?
        If we can't tell, say yes - a missing post is better than a double post."""
        try:
            status = await self.get_container_status(container_id)
        except InstagramAPIError:
            return True
        return status.get("status_code") == "PUBLISHED"

    async def _check_image(self, image_url: str, check_ratio: bool = True) -> None:
        """Download the image and reject what Meta would reject: non-JPEG files
        and (for feed posts) ratios outside 4:5 .. 1.91:1."""
        if not self.settings.validate_image_ratio:
            return
        from PIL import Image  # local import keeps startup fast

        try:
            resp = await self.client.get(image_url, follow_redirects=True)
            resp.raise_for_status()
            img = Image.open(BytesIO(resp.content))
            width, height = img.size
            fmt = (img.format or "").upper()
        except Exception as e:  # noqa: BLE001 - surface any download/decode issue
            raise InstagramAPIError(f"Could not download/read image {image_url}: {e}") from e
        if fmt not in JPEG_FORMATS:
            raise InvalidMedia(
                f"Image {image_url} is {fmt or 'not a recognised format'}; Instagram's "
                "publishing API only accepts JPEG. Convert it, or set VALIDATE_IMAGE_RATIO=false."
            )
        if not check_ratio:
            return
        if not width or not height:
            raise InstagramAPIError(f"Image {image_url} has no size")
        ratio = width / height
        lo, hi = FEED_RATIO_RANGE
        if not lo <= ratio <= hi:
            raise InvalidMedia(
                f"Image is {width}x{height} (ratio {ratio:.2f}). Feed images must be "
                "between 4:5 (0.8) and 1.91:1. Crop it, or set VALIDATE_IMAGE_RATIO=false."
            )

    async def publish_image(
        self,
        image_url: str,
        caption: str = "",
        alt_text: Optional[str] = None,
        location_id: Optional[str] = None,
        user_tags: Optional[List[Dict[str, Any]]] = None,
        collaborators: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        _check_caption(caption, self.settings.max_hashtags)
        await self._check_image(image_url)
        container = await self._create_container(
            {
                "image_url": image_url,
                "caption": caption,
                "alt_text": alt_text,
                "location_id": location_id,
                "user_tags": user_tags,
                "collaborators": collaborators,
            }
        )
        return await self._publish_container(container)

    async def publish_carousel(
        self,
        items: List[Dict[str, str]],
        caption: str = "",
        location_id: Optional[str] = None,
        collaborators: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """items: [{"image_url": ...} | {"video_url": ...}], 2-10 entries.

        Instagram crops every slide to the first slide's aspect ratio.
        """
        _check_caption(caption, self.settings.max_hashtags)
        if not 2 <= len(items) <= 10:
            raise InvalidMedia("A carousel needs 2 to 10 items.")
        for i, item in enumerate(items):
            if not item.get("image_url") and not item.get("video_url"):
                raise InvalidMedia(f"Carousel item {i + 1} needs image_url or video_url")
        # Validate every image before creating any container. The first slide
        # sets the crop for all, so only its ratio matters.
        for i, item in enumerate(items):
            if item.get("image_url"):
                await self._check_image(item["image_url"], check_ratio=(i == 0))
        children: List[str] = []
        for i, item in enumerate(items):
            if item.get("image_url"):
                payload = {"image_url": item["image_url"], "is_carousel_item": True}
                if item.get("alt_text"):
                    payload["alt_text"] = item["alt_text"]
            elif item.get("video_url"):
                payload = {
                    "video_url": item["video_url"],
                    "media_type": "VIDEO",
                    "is_carousel_item": True,
                }
            else:
                raise InstagramAPIError(f"Carousel item {i + 1} needs image_url or video_url")
            child_id = await self._create_container(payload)
            await self.wait_for_container(child_id)
            children.append(child_id)

        parent = await self._create_container(
            {
                "media_type": "CAROUSEL",
                "children": ",".join(children),
                "caption": caption,
                "location_id": location_id,
                "collaborators": collaborators,
            }
        )
        result = await self._publish_container(parent)
        result["children"] = children
        return result

    async def publish_reel(
        self,
        video_url: Optional[str] = None,
        caption: str = "",
        cover_url: Optional[str] = None,
        thumb_offset_ms: Optional[int] = None,
        share_to_feed: bool = True,
        audio_name: Optional[str] = None,
        collaborators: Optional[List[str]] = None,
        location_id: Optional[str] = None,
        trial_graduation: Optional[str] = None,
        video_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Publish a Reel from a public `video_url` or a local `video_path` (relative to
        the media root, sent with the resumable upload). trial_graduation=MANUAL|
        SS_PERFORMANCE makes it a trial Reel shown to non-followers first."""
        if bool(video_url) == bool(video_path):
            raise InvalidMedia("Give exactly one of video_url or video_path for a Reel.")
        _check_caption(caption, self.settings.max_hashtags)
        path = self._local_video(video_path) if video_path else None
        payload: Dict[str, Any] = {
            "media_type": "REELS",
            "video_url": video_url,
            "upload_type": "resumable" if path else None,
            "caption": caption,
            "cover_url": cover_url,
            "thumb_offset": thumb_offset_ms,
            "share_to_feed": share_to_feed,
            "audio_name": audio_name,
            "collaborators": collaborators,
            "location_id": location_id,
        }
        if trial_graduation:
            if trial_graduation not in ("MANUAL", "SS_PERFORMANCE"):
                raise InvalidMedia("trial_graduation must be MANUAL or SS_PERFORMANCE")
            payload["trial_params"] = {"graduation_strategy": trial_graduation}
        if not path:
            return await self._publish_container(await self._create_container(payload))
        data = await self._create_container_data(payload)
        container = _require_id(data, "media container")
        await self._upload_video(container, data.get("uri"), path)
        return await self._publish_container(container)

    async def publish_story(
        self, image_url: Optional[str] = None, video_url: Optional[str] = None
    ) -> Dict[str, Any]:
        if bool(image_url) == bool(video_url):
            raise InvalidMedia("Give exactly one of image_url or video_url for a Story.")
        if image_url:
            await self._check_image(image_url, check_ratio=False)
        container = await self._create_container(
            {"media_type": "STORIES", "image_url": image_url, "video_url": video_url}
        )
        return await self._publish_container(container)

    # ------------------------------------------------------------------
    # Comments
    # ------------------------------------------------------------------
    async def get_comments(self, media_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        data = await self._make_request(
            "GET",
            f"{media_id}/comments",
            params={
                "fields": "id,text,username,timestamp,like_count,hidden,"
                "replies{id,text,username,timestamp}",
                "limit": min(limit, 50),
            },
        )
        return data.get("data", [])

    async def reply_to_comment(self, comment_id: str, message: str) -> Dict[str, Any]:
        return await self._make_request(
            "POST", f"{comment_id}/replies", data={"message": message}
        )

    async def comment_on_media(self, media_id: str, message: str) -> Dict[str, Any]:
        return await self._make_request(
            "POST", f"{media_id}/comments", data={"message": message}
        )

    async def hide_comment(self, comment_id: str, hide: bool = True) -> Dict[str, Any]:
        return await self._make_request("POST", comment_id, data={"hide": hide})

    async def delete_comment(self, comment_id: str) -> Dict[str, Any]:
        return await self._make_request("DELETE", comment_id)

    # ------------------------------------------------------------------
    # Research
    # ------------------------------------------------------------------
    async def search_hashtag(
        self, hashtag: str, edge: str = "top_media", limit: int = 25
    ) -> Dict[str, Any]:
        """Top or recent public posts for a hashtag.

        Meta allows 30 unique hashtags per account per rolling 7 days.
        """
        if edge not in ("top_media", "recent_media"):
            raise InstagramAPIError("edge must be top_media or recent_media")
        tag = hashtag.lstrip("#").strip()
        found = await self._make_request(
            "GET",
            "ig_hashtag_search",
            params={"user_id": self.account_id, "q": tag},
            use_cache=True,
        )
        ids = [h["id"] for h in found.get("data", [])]
        if not ids:
            return {"hashtag": tag, "posts": []}
        data = await self._make_request(
            "GET",
            f"{ids[0]}/{edge}",
            params={
                "user_id": self.account_id,
                "fields": "id,caption,media_type,permalink,timestamp,like_count,comments_count",
                "limit": min(limit, 50),
            },
        )
        return {"hashtag": tag, "hashtag_id": ids[0], "posts": data.get("data", [])}

    async def get_competitor_profile(self, username: str, media_limit: int = 12) -> Dict[str, Any]:
        """Business Discovery: public stats + recent posts of another
        Business/Creator account."""
        user = username.lstrip("@").strip()
        fields = (
            f"business_discovery.username({user}){{username,name,biography,"
            f"followers_count,media_count,media.limit({min(media_limit, 50)})"
            "{id,caption,media_type,media_product_type,permalink,timestamp,"
            "like_count,comments_count}}"
        )
        data = await self._make_request(
            "GET", self.account_id, params={"fields": fields}, use_cache=True
        )
        bd = data.get("business_discovery", {})
        media = bd.pop("media", {}).get("data", [])
        bd["recent_media"] = media
        return bd

    # ------------------------------------------------------------------
    # DMs (instagram_manage_messages)
    #
    # The Messenger-platform endpoints for Instagram only accept a *Page*
    # access token, so the user token is exchanged for the Page's token
    # (kept in memory only, never returned to the caller).
    # ------------------------------------------------------------------
    async def _resolve_page_id(self, page_id: Optional[str]) -> str:
        if page_id:
            return page_id
        account_id = self.account_id  # raises if not configured
        pages = await self.get_account_pages()
        linked = [
            p for p in pages
            if (p.get("instagram_business_account") or {}).get("id") == account_id
        ]
        # Never fall back to another Page: DMs would go out under the wrong brand.
        if not linked:
            raise InstagramAPIError(
                f"No Facebook Page linked to Instagram account {account_id} was found for "
                "this token. Pass page_id explicitly, or check get_account_pages."
            )
        return linked[0]["id"]

    async def _page_token(self, page_id: str) -> str:
        if page_id not in self._page_tokens:
            data = await self._make_request(
                "GET", page_id, params={"fields": "access_token"}
            )
            token = data.get("access_token")
            if not token:
                raise InstagramAPIError(
                    f"Could not get a Page access token for page {page_id}. The token "
                    "needs pages_show_list / pages_manage_metadata and a role on the Page."
                )
            self._page_tokens[page_id] = token
        return self._page_tokens[page_id]

    async def get_conversations(
        self, page_id: Optional[str] = None, limit: int = 25
    ) -> List[Dict[str, Any]]:
        page_id = await self._resolve_page_id(page_id)
        data = await self._make_request(
            "GET",
            f"{page_id}/conversations",
            params={
                "platform": "instagram",
                "fields": "id,updated_time,message_count,participants",
                "limit": min(limit, 100),
            },
            token=await self._page_token(page_id),
        )
        return data.get("data", [])

    async def get_conversation_messages(
        self, conversation_id: str, limit: int = 25, page_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        page_id = await self._resolve_page_id(page_id)
        data = await self._make_request(
            "GET",
            conversation_id,
            params={
                "fields": f"messages.limit({min(limit, 100)})"
                "{id,from,to,message,created_time,attachments}"
            },
            token=await self._page_token(page_id),
        )
        return data.get("messages", {}).get("data", [])

    async def send_dm(
        self, recipient_id: str, message: str, page_id: Optional[str] = None
    ) -> Dict[str, Any]:
        if not message.strip():
            raise InstagramAPIError("DM text is empty")
        if len(message.encode("utf-8")) > 1000:
            raise InstagramAPIError("DM text must be 1000 bytes (UTF-8) or less")
        page_id = await self._resolve_page_id(page_id)
        return await self._make_request(
            "POST",
            f"{page_id}/messages",
            data={"recipient": {"id": recipient_id}, "message": {"text": message}},
            token=await self._page_token(page_id),
        )


def caption_problem(caption: Optional[str], max_hashtags: Optional[int] = None
                    ) -> Optional[str]:
    """Why Instagram would reject this caption, or None if it looks fine. `max_hashtags`
    defaults to the `max_hashtags` setting."""
    if not caption:
        return None
    if max_hashtags is None:
        max_hashtags = get_settings().max_hashtags
    if len(caption) > 2200:
        return "Caption must be 2200 characters or less"
    if len(HASHTAG_RE.findall(caption)) > max_hashtags:
        return f"Instagram allows at most {max_hashtags} hashtags per caption"
    return None


def _check_caption(caption: Optional[str], max_hashtags: int) -> None:
    problem = caption_problem(caption, max_hashtags)
    if problem:
        raise InvalidMedia(problem)


async def _read_chunks(path: Path) -> AsyncIterator[bytes]:
    """Stream the file: a Reel can be 300 MB, never hold it in memory."""
    with path.open("rb") as f:
        while chunk := f.read(UPLOAD_CHUNK):
            yield chunk


def _require_id(data: Dict[str, Any], what: str) -> str:
    media_id = data.get("id")
    if not media_id:
        raise InstagramAPIError(f"{what} returned no id: {data!r}")
    return str(media_id)


def _parse_insights(items: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for item in items:
        name = item.get("name")
        if not name:
            continue
        if "total_value" in item:
            out[name] = item["total_value"].get("value")
        elif item.get("values"):
            out[name] = item["values"][0].get("value")
    return out
