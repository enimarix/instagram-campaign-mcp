"""Step 145: one heavy GPU job at a time (src/studio/gpu_lock.py) and the renders that take it.
No GPU, no Blender, no Node: the renderers are faked."""

import logging
import subprocess
import sys
import threading
import time

import pytest

from src.studio import cinematic, gpu_lock, motion
from tests.test_studio_cinematic import ONE_LINE

CHILD = """
import importlib.util, sys, time
spec = importlib.util.spec_from_file_location("gpu_lock", sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
with m.hold("child render", sys.argv[2]):
    print("held", flush=True)
    time.sleep(120)
"""


def _free(path=None):
    """True when the GPU lock can be taken right now (another handle, like another process)."""
    try:
        with gpu_lock.hold("probe", path, timeout_s=0):
            return True
    except gpu_lock.LockTimeout:
        return False


def test_two_processes_cannot_hold_it_and_death_releases_it(tmp_path, caplog):
    path = tmp_path / "gpu.lock"
    child = subprocess.Popen([sys.executable, "-c", CHILD, gpu_lock.__file__, str(path)],
                             stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "held"
        caplog.set_level(logging.WARNING, "gpu_lock")
        start = time.monotonic()
        with pytest.raises(gpu_lock.LockTimeout, match="still locked"):
            with gpu_lock.hold("parent render", path, timeout_s=0.5, poll_s=0.05):
                pass
        assert time.monotonic() - start >= 0.5
        # (not child.pid: a venv python.exe on Windows may be a launcher with a child)
        assert "(held by pid " in caplog.text and ": child render)" in caplog.text
    finally:
        child.kill()  # no clean exit: the OS drops the lock
        child.wait()
        child.stdout.close()
    with gpu_lock.hold("parent render", path, timeout_s=5):
        assert (tmp_path / "gpu.lock.holder").read_text().endswith(": parent render")


def test_the_second_holder_waits_then_gets_it(tmp_path, caplog):
    path = tmp_path / "gpu.lock"
    held, order = threading.Event(), []

    def first():
        with gpu_lock.hold("Blender render", path):
            held.set()
            time.sleep(0.5)
            order.append("first done")

    caplog.set_level(logging.WARNING, "gpu_lock")
    t = threading.Thread(target=first)
    t.start()
    held.wait(5)
    with gpu_lock.hold("voice service", path, poll_s=0.05):  # no timeout: waits as long as needed
        order.append("second in")
    t.join()
    assert order == ["first done", "second in"]
    assert "voice service: waiting for the GPU (held by pid" in caplog.text
    assert "voice service: got the GPU after waiting" in caplog.text
    assert _free(path)


def test_default_path_is_shared_without_config(monkeypatch):
    monkeypatch.delenv("GPU_LOCK_PATH")
    assert gpu_lock.default_path() == gpu_lock.DEFAULT_PATH
    assert gpu_lock.DEFAULT_PATH.parts[-2:] == (".ig-campaign", "gpu.lock")
    monkeypatch.setenv("GPU_LOCK_PATH", "/x/gpu.lock")
    assert str(gpu_lock.default_path()).replace("\\", "/") == "/x/gpu.lock"


def test_a_remotion_render_holds_the_gpu_only_while_it_runs(monkeypatch, tmp_path):
    seen = []

    def bundle():
        seen.append(("bundle", _free()))  # bundling is CPU work: GPU still free
        return tmp_path

    monkeypatch.setattr(motion, "bundle_dir", bundle)
    monkeypatch.setattr(motion, "_node", lambda *a, **k: seen.append(("render", _free())) or {})
    motion._render("Hello", {}, tmp_path / "out.mp4", tmp_path, timeout_s=10)
    assert seen == [("bundle", True), ("render", False)]
    assert _free()


def test_a_blender_render_holds_the_gpu_only_while_it_runs(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(cinematic, "find_blender", lambda: "blender.exe")
    monkeypatch.setattr(cinematic, "_run", lambda cmd, what, t: seen.append((what, _free())))
    p = cinematic.Props.model_validate(cinematic.validate(ONE_LINE)["props"])
    timings = cinematic._plan(p)[0]
    cinematic._blender(p, timings, cinematic.flap_cues(timings), 48, tmp_path)
    assert seen == [("Blender", False)]
    assert _free()
