import os
import tempfile
from pathlib import Path

import httpx
import pytest

# Settings must load without a real .env
os.environ.setdefault("INSTAGRAM_ACCESS_TOKEN", "test_token")
os.environ.setdefault("INSTAGRAM_BUSINESS_ACCOUNT_ID", "1789")
os.environ["IG_MCP_ENV_FILE"] = "/nonexistent.env"

# Step 160: every machine path a default setting points at goes to one temp dir per session,
# before src is imported. A test that reaches the agent runner (or a detached `agent run` it
# starts: it inherits this env) can't rebuild the live ~/.ig-campaign-agent, and a test never
# waits on (or blocks) the real GPU lock (145) nor writes the checkout's data/.
_TMP = Path(tempfile.mkdtemp(prefix="ig-test-"))
os.environ.update({
    "DATABASE_PATH": str(_TMP / "ig_campaign.db"),
    "MEDIA_ROOT": str(_TMP / "media"),
    "BACKUP_DIR": str(_TMP / "backups"),
    "TTS_CACHE_DIR": str(_TMP / "cache" / "tts"),
    "STT_CACHE_DIR": str(_TMP / "cache" / "stt"),
    "INBOX_DIR": str(_TMP / "inbox"),
    "AGENT_WORKSPACE": str(_TMP / "agent-ws"),
    "AGENT_LOG_DIR": str(_TMP / "logs" / "agent"),
    "GPU_LOCK_PATH": str(_TMP / "gpu" / "gpu.lock"),
    "CLAUDE_BIN": str(_TMP / "no-claude-in-tests"),  # never a real AI run from a test
    "LEMO_LIBRARY": str(_TMP / "no-lemo-library"),  # 172: tests build a tiny fake one
    # Step 166: the resource guard never waits on, probes or pauses the real machine in a
    # test (tests/test_guard.py drives it with fakes).
    "GUARD_MIN_FREE_RAM_GB": "0",
    "GUARD_STARTUP_GRACE_MIN": "0",
    "GUARD_WATCHDOG": "false",
    "GUARD_NVIDIA_SMI": str(_TMP / "no-nvidia-smi"),
})
_REAL = [Path.home() / ".ig-campaign-agent", Path.home() / ".ig-campaign"]


def _snapshot():
    """path -> mtime of everything under the real machine folders."""
    return {p: p.stat().st_mtime_ns for root in _REAL if root.exists()
            for p in (root, *root.rglob("*"))}


@pytest.fixture(autouse=True, scope="session")
def _real_machine_untouched():
    """The suite (and anything it starts) never creates or changes the real agent workspace
    or the GPU lock folder. A live studio render or a scheduled run starting meanwhile also
    changes them: then rerun."""
    before = _snapshot()
    yield
    after = _snapshot()
    # the live studio's own GPU holder note may change; one written by this process is a leak
    holder = Path.home() / ".ig-campaign" / "gpu.lock.holder"
    if holder in after and after[holder] != before.get(holder):
        if not holder.read_text(encoding="utf-8", errors="replace").startswith(
                f"pid {os.getpid()}:"):
            before.pop(holder, None)
            after.pop(holder)
    changed = sorted(str(p) for p in before.keys() | after.keys()
                     if before.get(p) != after.get(p))
    assert not changed, f"the test suite touched the real machine: {changed}"


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
