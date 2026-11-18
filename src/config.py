"""
Configuration management for the Instagram campaign MCP server.

Settings come from environment variables or a `.env` file in the app's home
folder, so it is found even when an MCP client launches the server from
another working directory. The home folder is:

- IG_MCP_HOME if set;
- the project folder (next to pyproject.toml) for a source checkout or an
  editable install (`pip install -e .`, what install.ps1 / install.sh do);
- ~/.instagram-campaign-mcp for a regular `pip install`, where the code lives
  in site-packages and must not hold your .env or database.

Set IG_MCP_ENV_FILE to use a different .env file.
"""

import os
from decimal import Decimal
from pathlib import Path
from typing import Literal, Optional
from urllib.parse import urlparse

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _app_home(source_root: Optional[Path] = None) -> Path:
    if os.environ.get("IG_MCP_HOME"):
        return Path(os.environ["IG_MCP_HOME"]).expanduser().resolve()
    source_root = source_root or Path(__file__).resolve().parent.parent
    if (source_root / "pyproject.toml").is_file():
        return source_root
    return Path.home() / ".instagram-campaign-mcp"


APP_HOME = _app_home()
ENV_FILE = os.environ.get("IG_MCP_ENV_FILE", str(APP_HOME / ".env"))
PLACEHOLDERS = {"your_long_lived_access_token", "your_ig_user_id"}  # env.example's values
LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


class InstagramMCPSettings(BaseSettings):
    """Instagram MCP Server configuration settings."""

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Instagram API ---------------------------------------------------
    # Optional so everything starts in "setup mode" before the owner adds a token.
    instagram_access_token: Optional[str] = Field(None, description="Long-lived access token")
    instagram_business_account_id: Optional[str] = Field(
        None, description="Instagram professional account ID (IG User ID)"
    )
    # App ID/secret are only needed for token exchange helpers; API calls work without them.
    facebook_app_id: Optional[str] = Field(None, description="Meta app ID")
    # Never logged or returned (token refresh, src/studio/token.py).
    facebook_app_secret: Optional[SecretStr] = Field(None, description="Meta app secret")

    instagram_api_version: str = Field("v25.0", description="Graph API version")
    instagram_api_base_url: str = Field(
        "https://graph.facebook.com", description="Graph API host"
    )

    # --- Rate limiting / publishing ---------------------------------------
    rate_limit_requests_per_hour: int = Field(200, description="Client-side request cap")
    container_poll_interval_seconds: float = Field(
        5.0, description="Seconds between media container status checks"
    )
    container_timeout_seconds: float = Field(
        600.0, description="Max seconds to wait for a container to finish processing"
    )
    validate_image_ratio: bool = Field(
        True,
        description="Download images before publishing and reject non-JPEG files "
        "and feed ratios outside 4:5..1.91:1",
    )

    timezone: str = Field(
        "Europe/Paris",
        description="Time zone used for schedule times given without an offset",
    )

    # --- Slot planner -----------------------------------------------------
    max_posts_per_day: int = Field(3, ge=1, description="Most posts on one local day")
    min_slot_gap_minutes: int = Field(
        120, ge=1, description="Minimum real time between two publishes"
    )
    posting_windows: str = Field(
        "11:00-13:00,17:00-21:00",
        description="Local posting windows (TIMEZONE), comma-separated HH:MM-HH:MM",
    )
    slot_jitter_minutes: int = Field(
        7, ge=0, description="Random shift of each planned slot, in minutes either way"
    )
    slot_min_posts: int = Field(
        5, ge=1, description="Matured Reels a posting window needs before its results"
                             " weigh its slots"
    )
    slot_explore_share: float = Field(
        0.15, ge=0, le=1, description="Share of days whose first slot goes to the least-tried"
                                      " window, to keep learning"
    )
    max_late_minutes: int = Field(
        30, ge=1, description="A post later than this (e.g. PC asleep) moves to the next slot"
    )
    publishing_paused: bool = Field(
        False, description="Hold the whole queue (default; the website's pause switch wins)"
    )

    @field_validator("posting_windows")
    @classmethod
    def validate_posting_windows(cls, v):
        from .learning.slots import parse_windows

        parse_windows(v)
        return v

    # --- Campaign store ---------------------------------------------------
    database_path: str = Field(
        str(APP_HOME / "data" / "ig_campaign.db"),
        description="SQLite file for schedule, labels and insight snapshots",
    )

    # --- Media ------------------------------------------------------------
    media_root: str = Field(
        str(APP_HOME / "data" / "media"),
        description="Asset files (<date>/<asset id>/...); the API serves them at /api/media",
    )
    render_concurrency: int = Field(
        2, ge=1, description="Renders the worker runs at once (2 fit a laptop CPU, step 006a)"
    )

    # --- Housekeeping -----------------------------------------------------
    # Once a day (src/studio/housekeeping.py). Liked assets are archived only past best_before.
    archive_unreviewed_days: int = Field(
        7, ge=1, description="A ready asset never reviewed for this many days is archived"
    )
    delete_archived_files_days: int = Field(
        14, ge=0, description="Files of an asset archived this many days ago are deleted"
    )
    backup_dir: str = Field(
        str(APP_HOME / "data" / "backups"), description="Nightly database backups"
    )
    backup_keep: int = Field(14, ge=1, description="Database backups kept (newest)")
    snapshot_thin_after_days: int = Field(
        45, ge=31, description="Insight snapshots of posts older than this keep only the "
                               "age-schedule points and the latest"
    )
    min_free_disk_gb: float = Field(
        5.0, ge=0, description="No render starts while the media disk has less free space"
    )

    # --- Quality check ----------------------------------------------------
    # Checked after every render (src/studio/qc.py); a failing check makes the asset `failed`.
    qc_min_duration_s: float = Field(5.0, gt=0, description="Shortest video that passes QC")
    qc_max_duration_s: float = Field(90.0, gt=0, description="Longest video that passes QC")
    qc_max_black_s: float = Field(1.5, gt=0, description="A black stretch this long fails QC")
    qc_max_freeze_s: float = Field(3.0, gt=0, description="A frozen stretch this long fails QC")
    qc_max_freeze_s_motion: float = Field(
        8.0, gt=0, description="Same for motion renders (their title cards are still on purpose)"
    )
    qc_loudness_tolerance_lu: float = Field(
        2.0, ge=0, description="Allowed distance (LU) from the -14 LUFS loudness target"
    )
    # Instagram cut captions from 30 to 5 hashtags (@creators, Dec 2025); the Graph API
    # reference still says 30, so we keep to the app's rule (docs/DECISIONS.md).
    max_hashtags: int = Field(5, ge=0, description="Most hashtags a caption may carry")

    # --- Voice (TTS) -------------------------------------------------------
    # src/studio/tts.py. `none` = no voice, captions only. `http` = a local TTS service:
    # TTS_HTTP_BODY_TEMPLATE is JSON with {text} and {voice} placeholders (JSON-escaped), e.g.
    # {"text": "{text}", "voice": "{voice}"}. The service answers either raw audio bytes
    # (TTS_HTTP_RESPONSE=audio) or JSON (=json): {"<TTS_HTTP_AUDIO_FIELD>": "<base64 audio>",
    # "words": [{"text": "Hi", "start_s": 0.0, "end_s": 0.4}, ...]} (words optional).
    tts_provider: Literal["none", "http"] = Field("none", description="Voice engine")
    tts_http_url: Optional[str] = Field(None, description="TTS service URL (http provider)")
    tts_http_method: str = Field("POST", description="HTTP method of the TTS request")
    tts_http_body_template: str = Field(
        '{"text": "{text}", "voice": "{voice}"}', description="JSON request body template"
    )
    tts_http_response: Literal["audio", "json"] = Field(
        "audio", description="audio = raw audio bytes; json = base64 audio + optional words"
    )
    tts_http_audio_field: str = Field("audio", description="JSON field holding base64 audio")
    # Never logged or put into errors.
    tts_http_auth_header: Optional[SecretStr] = Field(
        None, description="Extra request header 'Name: value', e.g. 'Authorization: Bearer x'"
    )
    tts_voice: str = Field("", description="Voice id passed to the engine")
    tts_timeout_s: float = Field(120.0, gt=0, description="TTS request timeout in seconds")
    tts_cache_dir: str = Field(
        str(APP_HOME / "data" / "cache" / "tts"), description="Synthesized audio cache"
    )

    # --- Transcription ----------------------------------------------------
    # src/studio/stt.py. `none` = no transcript. `faster_whisper` = local CPU model (int8),
    # optional extra `pip install -e .[stt]`; the model downloads on first use.
    stt_provider: Literal["none", "faster_whisper"] = Field(
        "none", description="Speech-to-text engine"
    )
    stt_model: str = Field("small", description="faster-whisper model: tiny, base, small, ...")
    stt_language: Optional[str] = Field(None, description="Language code; empty = auto-detect")
    stt_cache_dir: str = Field(
        str(APP_HOME / "data" / "cache" / "stt"), description="Transcript cache"
    )

    # --- Clip intake ------------------------------------------------------
    # src/studio/sources.py. The inbox is a drop zone: each file gets its rights on the
    # website before it becomes a clip; nothing is imported automatically.
    inbox_dir: str = Field(
        str(APP_HOME / "data" / "inbox"), description="Clips waiting for their rights"
    )
    max_clip_mb: float = Field(300.0, gt=0, description="Largest clip accepted (MB, 10^6 B)")
    max_clip_seconds: float = Field(300.0, gt=0, description="Longest clip accepted (seconds)")
    # src/studio/stock.py: Pexels stock videos (H4). Sent as a header only, never logged.
    pexels_api_key: Optional[SecretStr] = Field(None, description="Pexels API key; empty = off")

    # --- Reel downloader --------------------------------------------------
    # src/studio/downloader_service.py: the vendored downloader (vendor/), run by the worker
    # on 127.0.0.1 only once `ig-campaign downloader setup` built it.
    downloader_port: int = Field(3711, ge=1, le=65535, description="Loopback port of the service")
    downloader_health_url: str = Field(
        "", description="A public Reel permalink for the daily health check; empty = no check"
    )
    # src/studio/downloader.py: Reels downloaded for a reaction (GOAL.md §5.1).
    max_downloads_per_day: int = Field(30, ge=0, description="Reel downloads per owner-local day")
    download_delay_s: float = Field(5.0, ge=0, description="Least seconds between two downloads")
    max_download_mb: float = Field(200.0, gt=0, description="Largest Reel file (MB, 10^6 B)")
    downloader_cookies_file: str = Field(
        "", description="yt-dlp fallback only: a cookies.txt of a SEPARATE personal Instagram "
        "account, never the brand account; empty = logged out"
    )

    # --- Production tools -------------------------------------------------
    # src/studio/production.py (the agent's batch tools).
    best_before_default_days: int = Field(
        30, ge=1, description="Shelf life of a submitted video whose pillar sets no shelf_days"
    )
    wait_for_renders_max_s: float = Field(
        240.0, gt=0, description="Longest wait_for_renders call (MCP clients time out long calls)"
    )

    # --- Daily quotas -----------------------------------------------------
    # create_idea guards (src/learning/quotas.py, GOAL.md §3.1-3.2).
    batch_size: int = Field(10, ge=1, description="Ideas per daily batch")
    explore_share: float = Field(
        0.3, ge=0, le=1, description="Max share of explore ideas in a batch (rounded up)"
    )
    humour_share: float = Field(
        0.5, ge=0, le=1, description="Target share of humour ideas in a batch (+/- 1 idea)"
    )
    max_reactions_per_day: int = Field(
        3, ge=0, description="Reactions the owner can record per day (Track A volume)"
    )
    reaction_margin: int = Field(
        2, ge=0, description="Extra reaction ideas prepared above MAX_REACTIONS_PER_DAY"
    )
    max_dm_pick_extras_per_day: int = Field(
        3, ge=0, description="DM-pick remix ideas allowed past a full batch per day (073)"
    )
    dedupe_days: int = Field(30, ge=0, description="How far back create_idea looks for duplicates")
    dedupe_threshold: float = Field(
        0.85, gt=0, le=1, description="Hook similarity (difflib ratio) that counts as a duplicate"
    )
    bench_target_days: int = Field(
        3, ge=0, description="Days of liked videos on the bench beyond which batches shrink"
    )
    batch_floor: int = Field(
        5, ge=1, description="Smallest batch, however full the bench (learning never stops)"
    )

    # --- Agent runs ---------------------------------------------------------
    # `ig-campaign agent run <playbook>` (src/agent/runner.py): Claude Code headless, locked
    # down (GOAL.md §4, third rule). The workspace must be outside the repo and APP_HOME.
    agent_workspace: str = Field(
        str(Path.home() / ".ig-campaign-agent"),
        description="Agent working folder (playbook, skills, MCP config); refreshed each run",
    )
    agent_log_dir: str = Field(
        str(APP_HOME / "data" / "logs" / "agent"), description="One log file per agent run"
    )
    claude_bin: str = Field("claude", description="Claude Code CLI executable")
    agent_max_turns: int = Field(100, ge=1, description="Default --max-turns of a run")
    agent_timeout_minutes: float = Field(
        90.0, gt=0, description="Wall-clock limit of a run; the CLI is killed after it"
    )
    # Run times are settled at step 062 (H8); install-schedule registers them with the OS.
    agent_schedule: str = Field(
        "daily-learn@02:00,daily-produce@03:00",
        description="Daily agent runs, comma-separated playbook@HH:MM (TIMEZONE); empty = none",
    )

    @field_validator("agent_schedule")
    @classmethod
    def validate_agent_schedule(cls, v):
        from .agent.schedule import parse_schedule

        parse_schedule(v)
        return v

    # --- Winner scoring ---------------------------------------------------
    winner_min_age_hours: float = Field(
        48.0, description="Posts younger than this are not judged yet"
    )
    winner_min_reach: int = Field(
        300, description="Minimum reach before a post can be called a winner"
    )
    winner_threshold: float = Field(
        1.5, description="Engagement index (vs account median) needed to win"
    )
    baseline_window: int = Field(
        30, description="How many recent matured posts form the account baseline"
    )
    max_open_experiments: int = Field(
        2, ge=1, le=10, description="Experiments open at once (src/learning/experiments.py)"
    )

    # --- Evidence engine (learnings checked against the numbers) -----------
    evidence_min_n_medium: int = Field(
        5, ge=1, description="Matching matured Reels a learning needs for medium confidence"
    )
    evidence_min_n_high: int = Field(
        15, ge=1, description="Matching matured Reels a learning needs for high confidence"
    )
    evidence_min_effect: float = Field(
        0.15, ge=0, description="How far from 1.0 the index must be: a do needs > 1 + this,"
                                " a dont < 1 - this"
    )

    # --- Batch mix (src/learning/mix.py) ------------------------------------
    mix_floor: float = Field(
        0.10, ge=0, le=1, description="Smallest share of each allowed option in the batch mix"
    )
    mix_min_posts: int = Field(
        5, ge=1, description="Matured Reels an option needs before its engagement index"
                             " counts in the mix"
    )
    mix_index_weight: float = Field(
        0.5, ge=0, le=1, description="Weight of the engagement index vs the like rate once"
                                     " an option has MIX_MIN_POSTS"
    )

    # --- Website ----------------------------------------------------------
    # Optional; required before `serve` binds a non-loopback host. Never logged or returned.
    ui_password: Optional[SecretStr] = Field(None, description="Website password")
    session_ttl_hours: float = Field(720.0, description="Login session lifetime (30 days)")
    login_max_failures: int = Field(5, ge=1, description="Failed logins before the lock")
    login_lockout_minutes: float = Field(
        15.0, description="Failure window and lock duration after too many failed logins"
    )
    web_dist: str = Field(
        str(APP_HOME / "web" / "dist"), description="Built website (`npm --prefix web run build`)"
    )

    # --- Reaction reel ----------------------------------------------------
    # src/studio/reactions.py: one long owner recording, cut into pieces in order.
    reaction_upload_max_mb: int = Field(
        16000, ge=1, description="Largest reaction reel upload (an hour of phone video fits)"
    )

    # --- Remix ------------------------------------------------------------
    # src/studio/remix.py: a reaction remix uses only the part of the clip it reacts to.
    remix_max_clip_s: float = Field(
        45.0, gt=0, description="Longest stretch of a clip one reaction remix may use (seconds)"
    )

    # --- Logging / cache --------------------------------------------------
    log_level: str = Field("INFO", description="Log level")
    cache_enabled: bool = Field(True, description="Cache GET responses")
    cache_ttl_seconds: int = Field(300, description="Cache TTL in seconds")

    # --- MCP --------------------------------------------------------------
    mcp_server_name: str = Field("instagram-campaign-mcp", description="MCP server name")
    mcp_server_version: str = Field("2.0.0", description="MCP server version")
    mcp_transport: str = Field("stdio", description="stdio | streamable-http")
    # `agent` exposes only AGENT_TOOLS (src/instagram_mcp_server.py) for unattended runs.
    # An unknown value fails validation; it never falls back to `full`.
    ig_mcp_profile: Literal["full", "agent"] = Field(
        "full", description="MCP tool profile: full (owner) | agent (allow-listed tools only)"
    )

    # --- Ads (Phase 9, H6) --------------------------------------------------
    # src/ads/client.py reads with INSTAGRAM_ACCESS_TOKEN (needs ads_read). Empty = ads off.
    meta_ad_account_id: Optional[str] = Field(
        None, description="Ad account id, digits only (the client adds act_)"
    )
    # Budget guard (src/ads/budget.py): money in the ad account's currency. 0 = no spend.
    ads_daily_cap: Decimal = Field(Decimal(0), ge=0, description="Most spend per owner-local day")
    ads_test_cap: Decimal = Field(Decimal(0), ge=0, description="Most spend per A/B test")
    ads_lifetime_cap: Decimal = Field(Decimal(0), ge=0, description="Most spend ever")
    # ponytail: EUR until H9 names the account's currency; it must match the ad account's.
    ads_currency: str = Field("EUR", description="ISO 4217 code of the ad account currency")

    @field_validator("ads_currency")
    @classmethod
    def validate_ads_currency(cls, v):
        v = v.strip().upper()
        if not (len(v) == 3 and v.isascii() and v.isalpha()):
            raise ValueError(f"ADS_CURRENCY must be an ISO 4217 code like EUR, got {v!r}")
        return v

    @model_validator(mode="after")
    def validate_ads_caps(self):
        if self.ads_daily_cap > self.ads_lifetime_cap:
            raise ValueError("ADS_DAILY_CAP must not be above ADS_LIFETIME_CAP")
        return self

    @field_validator("meta_ad_account_id")
    @classmethod
    def validate_ad_account_id(cls, v):
        v = (v or "").strip().removeprefix("act_")
        if v and not (v.isascii() and v.isdigit()):
            raise ValueError(f"META_AD_ACCOUNT_ID must be digits (e.g. 1234567890), got {v!r}")
        return v or None

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v):
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if v.upper() not in valid_levels:
            raise ValueError(f"Log level must be one of: {valid_levels}")
        return v.upper()

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v):
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as e:
            raise ValueError(f"Unknown time zone {v!r} (use an IANA name like Europe/Paris)") from e
        return v

    @field_validator("instagram_api_version")
    @classmethod
    def validate_api_version(cls, v):
        if not v.startswith("v"):
            raise ValueError("API version must start with 'v' (e.g., 'v25.0')")
        return v

    @field_validator("instagram_api_base_url")
    @classmethod
    def validate_api_base_url(cls, v):
        # The token travels to this host: https only, plain http just for a local stub (e2e).
        url = urlparse(v)
        if not url.hostname or not (
            url.scheme == "https" or (url.scheme == "http" and url.hostname in LOOPBACK_HOSTS)
        ):
            raise ValueError(
                f"INSTAGRAM_API_BASE_URL must be an https:// URL (http:// only for "
                f"127.0.0.1, ::1 or localhost), got {v!r}"
            )
        return v

    @property
    def instagram_configured(self) -> bool:
        """True when Graph-backed work (publish, insights, account) can run."""
        # env.example's placeholder values count as not set (doctor relies on it).
        return all(v and v not in PLACEHOLDERS
                   for v in (self.instagram_access_token, self.instagram_business_account_id))

    @property
    def instagram_api_url(self) -> str:
        return f"{self.instagram_api_base_url.rstrip('/')}/{self.instagram_api_version}"


_settings: Optional[InstagramMCPSettings] = None


def get_settings() -> InstagramMCPSettings:
    """Get the global settings instance."""
    global _settings
    if _settings is None:
        _settings = InstagramMCPSettings()
    return _settings


def reload_settings() -> InstagramMCPSettings:
    """Reload settings from environment variables."""
    global _settings
    _settings = InstagramMCPSettings()
    return _settings
