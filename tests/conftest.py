import os
import tempfile

import httpx
import pytest

# Settings must load without a real .env
os.environ.setdefault("INSTAGRAM_ACCESS_TOKEN", "test_token")
os.environ.setdefault("INSTAGRAM_BUSINESS_ACCOUNT_ID", "1789")
os.environ["IG_MCP_ENV_FILE"] = "/nonexistent.env"
# The worker's daily backup (render loop) must never write into the checkout's data/.
os.environ.setdefault("BACKUP_DIR", tempfile.mkdtemp(prefix="ig-test-backups-"))

from src.config import InstagramMCPSettings  # noqa: E402
from src.instagram_client import InstagramClient  # noqa: E402
from src.store import CampaignStore  # noqa: E402
from src.studio import downloader_service  # noqa: E402


@pytest.fixture(autouse=True)
def _no_real_downloader(monkeypatch, tmp_path_factory):
    """A built vendor/ submodule on a dev machine must never start inside a test (063a)."""
    monkeypatch.setattr(downloader_service, "VENDOR_DIR",
                        tmp_path_factory.getbasetemp() / "no-downloader")

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
