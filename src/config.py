"""
Configuration management for the Instagram campaign MCP server.

Settings come from environment variables or a `.env` file. The `.env` file is
looked up in the project root (next to README.md), so it is found even when an
MCP client launches the server from another working directory. Set
IG_MCP_ENV_FILE to use a different file.
"""

import os
from pathlib import Path
from typing import List, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = os.environ.get("IG_MCP_ENV_FILE", str(PROJECT_ROOT / ".env"))


class InstagramMCPSettings(BaseSettings):
    """Instagram MCP Server configuration settings."""

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Instagram API ---------------------------------------------------
    instagram_access_token: str = Field(..., description="Long-lived access token")
    instagram_business_account_id: Optional[str] = Field(
        None, description="Instagram professional account ID (IG User ID)"
    )
    # App ID/secret are only needed for token exchange helpers; API calls work without them.
    facebook_app_id: Optional[str] = Field(None, description="Meta app ID")
    facebook_app_secret: Optional[str] = Field(None, description="Meta app secret")

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
        True, description="Download feed images and check aspect ratio before publishing"
    )

    timezone: str = Field(
        "Europe/Paris",
        description="Time zone used for schedule times given without an offset",
    )

    # --- Campaign store ---------------------------------------------------
    database_path: str = Field(
        str(PROJECT_ROOT / "data" / "ig_campaign.db"),
        description="SQLite file for schedule, labels and insight snapshots",
    )

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

    # --- Logging / cache --------------------------------------------------
    log_level: str = Field("INFO", description="Log level")
    cache_enabled: bool = Field(True, description="Cache GET responses")
    cache_ttl_seconds: int = Field(300, description="Cache TTL in seconds")

    allowed_image_formats: List[str] = Field(
        ["jpg", "jpeg", "png"], description="Allowed image formats"
    )

    # --- MCP --------------------------------------------------------------
    mcp_server_name: str = Field("instagram-campaign-mcp", description="MCP server name")
    mcp_server_version: str = Field("2.0.0", description="MCP server version")
    mcp_transport: str = Field("stdio", description="stdio | streamable-http")

    @field_validator("allowed_image_formats", mode="before")
    @classmethod
    def parse_list_from_string(cls, v):
        if isinstance(v, str):
            return [item.strip() for item in v.split(",")]
        return v

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
