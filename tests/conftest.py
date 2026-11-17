import os

import httpx
import pytest

# Settings must load without a real .env
os.environ.setdefault("INSTAGRAM_ACCESS_TOKEN", "test_token")
os.environ.setdefault("INSTAGRAM_BUSINESS_ACCOUNT_ID", "1789")
os.environ["IG_MCP_ENV_FILE"] = "/nonexistent.env"

from src.config import InstagramMCPSettings  # noqa: E402
from src.instagram_client import InstagramClient  # noqa: E402
from src.store import CampaignStore  # noqa: E402

API = "https://graph.facebook.com/v25.0"
# TestClient base URL: without UI_PASSWORD the Host guard refuses Starlette's "testserver".
LOCAL = "http://127.0.0.1"


@pytest.fixture
def settings():
    return InstagramMCPSettings(
        _env_file=None,
        instagram_access_token="test_token",
        instagram_business_account_id="1789",
        container_poll_interval_seconds=0,
        container_timeout_seconds=5,
        validate_image_ratio=False,
        database_path=":memory:",
        cache_enabled=False,
    )


@pytest.fixture
async def client(settings):
    c = InstagramClient(settings, http_client=httpx.AsyncClient())
    yield c
    await c.close()


@pytest.fixture
def store():
    s = CampaignStore(":memory:")
    yield s
    s.close()
