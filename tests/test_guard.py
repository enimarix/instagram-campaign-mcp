"""Step 166: the resource guard (src/studio/guard.py). Fakes everywhere, except dummy child
processes started here (never a real render). 2026-11-25: the watchdog and the startup grace
are gone; guard.log stays."""

from __future__ import annotations

import asyncio
import contextlib
import functools
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.agent import schedule
from src.studio import gpu_lock, guard

ROOT = Path(__file__).resolve().parents[1]
# A venv's python.exe on Windows is a launcher that runs the real interpreter as its child:
# suspend or kill that and the interpreter runs on. The base interpreter is one process.
PY = getattr(sys, "_base_executable", None) or sys.executable
PRIORITY = ("import ctypes, os, sys\n"
            "if sys.platform == 'win32':\n"
            "    k = ctypes.WinDLL('kernel32'); k.GetCurrentProcess.restype = ctypes.c_void_p\n"
            "    k.GetPriorityClass.argtypes = (ctypes.c_void_p,)\n"
            "    print(k.GetPriorityClass(k.GetCurrentProcess()))\n"
            "else:\n"
            "    print(os.getpriority(os.PRIO_PROCESS, 0))\n")


def test_run_starts_the_child_at_low_priority():
    out = guard.run([sys.executable, "-c", PRIORITY], capture_output=True, text=True, timeout=60)
    value = int(out.stdout)
    assert value == guard.BELOW_NORMAL if sys.platform == "win32" else value >= guard.NICE


def test_low_priority_keeps_the_callers_flags():
    kw = guard.low_priority({"cwd": "x", "creationflags": 0x8})
    assert kw["cwd"] == "x"
    if sys.platform == "win32":
        assert kw["creationflags"] == 0x8 | guard.BELOW_NORMAL
    else:
        assert callable(kw["preexec_fn"])


def test_run_timeout_kills_the_child():
    with pytest.raises(subprocess.TimeoutExpired):
        guard.run([PY, "-c", "import time; time.sleep(60)"], timeout=0.5)


def test_blockers_name_ram_vram_and_a_game(monkeypatch):
    monkeypatch.setattr(guard, "free_ram_gb", lambda: 5.0)
    monkeypatch.setattr(guard, "gpu_status", lambda: {"free_vram_gb": 2.0, "temp_c": 60.0,
                                                      "util_pct": 97.0})
    why = guard.blockers(3.0, 8.0)
    assert [w.split(":")[0] for w in why] == ["waiting for RAM", "waiting for VRAM",
                                             "waiting for a game (the GPU is busy)"]
    assert why[2].endswith("97 %")
    monkeypatch.setattr(guard, "free_ram_gb", lambda: 20.0)
    # 2026-11-23: an idle card is no game, whatever the desktop apps hold (Discord / dwm made
    # every voice wait forever through Windows' per-process counters); util unknown: no game
    for util in (0.0, guard.GAME_GPU_PCT, None):
        monkeypatch.setattr(guard, "gpu_status", lambda u=util: {"free_vram_gb": 7.2,
                                                                 "temp_c": 50.0, "util_pct": u})
        assert guard.blockers(guard.VRAM_GB["voice"], 8.0) == []


def test_gpu_status_reads_used_vram(monkeypatch):
    """177: guard.log shows the used VRAM; troupe.measure samples it."""
    rows = {"--query-gpu=memory.used": [["2150"]]}
    monkeypatch.setattr(guard, "_smi", lambda q: rows.get(q, [["5000", "61", "98.5", "130.0",
                                                               "96", "3192", "8192", "1500"]]))
    g = guard.gpu_status()
    assert g["free_vram_gb"] == pytest.approx(5000 / 1024) and g["power_w"] == 98.5
    assert (g["used_vram_gb"], g["total_vram_gb"]) == pytest.approx((3192 / 1024, 8.0))
    assert g["clock_mhz"] == 1500  # 177: shows whether the owner's clock cap is on
    assert guard.vram_used_gb() == pytest.approx(2150 / 1024)
    monkeypatch.setattr(guard, "_smi", lambda q: [["5000", "61", "[N/A]", "[N/A]", "[N/A]"]])
    old = guard.gpu_status()  # an older nvidia-smi answer
    assert old["used_vram_gb"] is None and old["clock_mhz"] is None


def test_no_nvidia_smi_means_no_gpu_check(monkeypatch):
    monkeypatch.setattr(guard, "free_ram_gb", lambda: None)  # unknown: no RAM check either
    assert guard.gpu_status() is None  # conftest: GUARD_NVIDIA_SMI names nothing
    assert guard.blockers(7.0, 8.0) == []
    assert guard.vram_used_gb() is None


def test_admit_waits_and_says_why(caplog):
    answers = [["waiting for RAM: 5.0 GB free, 8 GB needed"], ["waiting for a game: pid 9"], []]
    seen = []

    def check(need, floor):
        seen.append((need, floor))
        return answers.pop(0)

    caplog.set_level("WARNING", "guard")
    guard.admit("Blender render", 3.0, 8.0, poll_s=0.01, log_every_s=0, check=check)
    assert seen == [(3.0, 8.0)] * 3
    text = caplog.text
    assert "Blender render: waiting for RAM" in text and "waiting for a game" in text
    assert "starting after waiting" in text


def test_admit_floor_defaults_to_the_env(monkeypatch):
    seen = []
    monkeypatch.setenv("GUARD_MIN_FREE_RAM_GB", "12")
    guard.admit("x", check=lambda need, floor: seen.append(floor) or [])
    monkeypatch.delenv("GUARD_MIN_FREE_RAM_GB")
    guard.admit("x", check=lambda need, floor: seen.append(floor) or [])
    assert seen == [12.0, guard.MIN_FREE_RAM_GB]


def _held(path):
    """True when another handle (like another process) can't take the lock right now."""
    try:
        with gpu_lock.file_lock(path, timeout_s=0):
            return False
    except gpu_lock.LockTimeout:
        return True


def _fast_admit(monkeypatch):
    monkeypatch.setattr(gpu_lock.guard, "admit", functools.partial(guard.admit, poll_s=0.01))


def test_the_gpu_lock_admits_before_taking_it_then_checks_again(monkeypatch, tmp_path):
    path = tmp_path / "gpu.lock"
    seen = []

    def admit(what, need, floor):
        seen.append(("admit", what, need, floor, _held(path)))

    def blockers(need, floor):
        seen.append(("check", need, floor, _held(path)))
        return []

    monkeypatch.setattr(gpu_lock.guard, "admit", admit)
    monkeypatch.setattr(gpu_lock.guard, "blockers", blockers)
    with gpu_lock.hold("voice service", path, need_vram_gb=7.0, min_free_ram_gb=8.0):
        assert _held(path)
    assert seen == [("admit", "voice service", 7.0, 8.0, False), ("check", 7.0, 8.0, True)]


def test_blocked_again_under_the_lock_lets_it_go_and_waits(monkeypatch, tmp_path):
    path = tmp_path / "gpu.lock"
    answers, seen = [[], ["waiting for VRAM: 1.0 GB free, 6 GB needed"], [], []], []

    def blockers(need, floor):
        seen.append(_held(path))
        return answers.pop(0)

    _fast_admit(monkeypatch)
    monkeypatch.setattr(gpu_lock.guard, "blockers", blockers)
    with gpu_lock.hold("voice service", path, need_vram_gb=6.0, poll_s=0.01):
        pass
    # admit (free), under the lock (blocked: let go), admit again (free), under the lock (ok)
    assert seen == [False, True, False, True] and not answers


def test_a_job_waiting_for_vram_never_blocks_the_others(monkeypatch, tmp_path, caplog):
    path = tmp_path / "gpu.lock"
    vram_back, entered = threading.Event(), []
    monkeypatch.setattr(gpu_lock.guard, "blockers", lambda need, floor: (
        ["waiting for VRAM: 2.0 GB free, 6 GB needed"] if need == 6.0 and not vram_back.is_set()
        else []))
    _fast_admit(monkeypatch)
    caplog.set_level("WARNING", "guard")

    def voice():
        with gpu_lock.hold("voice service", path, need_vram_gb=6.0, poll_s=0.01):
            entered.append("voice")

    t = threading.Thread(target=voice)
    t.start()
    try:
        time.sleep(0.2)  # the voice waits for VRAM ...
        with gpu_lock.hold("Remotion render", path, need_vram_gb=1.5, timeout_s=1):
            entered.append("render")  # ... and a small render goes meanwhile
    finally:
        vram_back.set()
        t.join(5)
    assert entered == ["render", "voice"]
    assert "voice service: waiting for VRAM" in caplog.text


def test_of_two_admitted_waiters_the_older_goes_first(monkeypatch, tmp_path):
    path = tmp_path / "gpu.lock"
    monkeypatch.setattr(gpu_lock.guard, "blockers", lambda need, floor: [])
    release, order = threading.Event(), []

    def first():
        with gpu_lock.hold("Blender render", path):
            order.append("holder")
            release.wait(5)

    def waiter(name, poll_s):
        with gpu_lock.hold(name, path, poll_s=poll_s):
            order.append(name)

    threads = [threading.Thread(target=first)]
    threads[0].start()
    while not order:
        time.sleep(0.01)
    # the older one polls slowly: without its ticket the younger would always win
    threads += [threading.Thread(target=waiter, args=("older", 0.3))]
    threads[1].start()
    time.sleep(0.1)
    threads += [threading.Thread(target=waiter, args=("younger", 0.01))]
    threads[2].start()
    time.sleep(0.2)
    release.set()
    for t in threads:
        t.join(5)
    assert order == ["holder", "older", "younger"]
    assert not list((tmp_path / "gpu.lock.queue").iterdir())  # tickets cleaned up


def test_a_dead_waiters_ticket_does_not_hold_the_queue(monkeypatch, tmp_path):
    path = tmp_path / "gpu.lock"
    queue = tmp_path / "gpu.lock.queue"
    queue.mkdir()
    dead = queue / f"{0:020d}-1-0"
    dead.touch()
    old = time.time() - gpu_lock.TICKET_STALE_S - 1
    os.utime(dead, (old, old))
    monkeypatch.setattr(gpu_lock.guard, "blockers", lambda need, floor: [])
    with gpu_lock.hold("Remotion render", path, timeout_s=0):
        pass
    assert not dead.exists()


def test_studio_jobs_ask_for_their_vram(monkeypatch, settings):
    seen = []
    monkeypatch.setattr(gpu_lock.guard, "admit", lambda what, need, floor: seen.append(
        (what, need, floor)))
    monkeypatch.setattr(gpu_lock.guard, "blockers", lambda need, floor: [])
    monkeypatch.setattr("src.config.get_settings", lambda: settings.model_copy(
        update={"guard_min_free_ram_gb": 9.0}))
    with guard.gpu("Remotion Hello render", "remotion"):
        pass
    assert seen == [("Remotion Hello render", 1.5, 9.0)]


# --- guard.log ----------------------------------------------------------------------------

def test_state_line_shows_the_machine_and_the_lock(monkeypatch):
    monkeypatch.setattr(guard, "gpu_status", lambda: {
        "temp_c": 71.0, "power_w": 98.0, "power_limit_w": 130.0, "util_pct": 96.0,
        "used_vram_gb": 2.14, "total_vram_gb": 8.0, "clock_mhz": 1500.0})
    monkeypatch.setattr(guard, "cpu_perf_limit", lambda: 100.0)
    monkeypatch.setattr(guard, "free_ram_gb", lambda: 18.2)
    assert guard.state_line("pid 7: Blender (dev)") == (
        "GPU 71 °C 98/130 W 96 % | VRAM 2.1/8.0 GB used, clock 1500 MHz | CPU limit 100 % | "
        "RAM 18.2 GB free | lock pid 7: Blender (dev)")


async def test_log_loop_writes_only_while_the_lock_is_held(monkeypatch, tmp_path):
    log, holders = tmp_path / "logs" / "guard.log", ["pid 7: Blender (dev)", None]
    monkeypatch.setattr(gpu_lock, "held_by", lambda path=None: holders.pop(0) if holders else None)
    monkeypatch.setattr(guard, "state_line", lambda by: f"state | lock {by}")
    task = asyncio.create_task(guard.log_loop(every_s=0.01, log_path=log))
    deadline = time.monotonic() + 5
    while holders and time.monotonic() < deadline:
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1 and lines[0].endswith("state | lock pid 7: Blender (dev)")


def test_guard_log_rotates(tmp_path, monkeypatch):
    log = tmp_path / "guard.log"
    monkeypatch.setattr(guard, "LOG_MAX_BYTES", 10)
    guard.write_log(log, "a" * 20)
    guard.write_log(log, "b")
    assert log.read_text(encoding="utf-8").endswith(" b\n")
    assert "a" * 20 in log.with_name("guard.log.1").read_text(encoding="utf-8")


def test_held_by_reads_the_lock_not_the_stale_holder_file(tmp_path, monkeypatch):
    monkeypatch.setattr(gpu_lock.guard, "admit", lambda *a: None)
    path = tmp_path / "gpu.lock"
    assert gpu_lock.held_by(path) is None
    with gpu_lock.hold("Blender troupe shots", path):
        assert gpu_lock.held_by(path) == f"pid {os.getpid()}: Blender troupe shots"
    assert path.with_name("gpu.lock.holder").exists() and gpu_lock.held_by(path) is None


# --- heat budget: CPUs and threads (171) --------------------------------------------------

AFFINITY = ("import ctypes, os, sys\n"
            "if sys.platform == 'win32':\n"
            "    k = ctypes.WinDLL('kernel32'); k.GetCurrentProcess.restype = ctypes.c_void_p\n"
            "    m, s = ctypes.c_size_t(), ctypes.c_size_t()\n"
            "    k.GetProcessAffinityMask.argtypes = (ctypes.c_void_p, ctypes.c_void_p,"
            " ctypes.c_void_p)\n"
            "    k.GetProcessAffinityMask(k.GetCurrentProcess(), ctypes.byref(m),"
            " ctypes.byref(s))\n"
            "    print(m.value)\n"
            "else:\n"
            "    print(sum(1 << c for c in os.sched_getaffinity(0)))\n")


def test_heavy_cpus_is_the_share_of_the_logical_cpus(monkeypatch):
    monkeypatch.setattr(os, "cpu_count", lambda: 16)
    assert guard.heavy_cpus() == 8  # GUARD_CPU_SHARE default 0.5
    monkeypatch.setenv("GUARD_CPU_SHARE", "0.25")
    assert guard.heavy_cpus() == 4
    monkeypatch.setenv("GUARD_CPU_SHARE", "0.01")
    assert guard.heavy_cpus() == 1


def test_heavy_jobs_leave_cpu_0_to_windows(monkeypatch):
    """177: CPU 0 takes most interrupts and the NVIDIA driver's DPCs (the bluescreen's)."""
    monkeypatch.setattr(os, "cpu_count", lambda: 16)
    assert guard.cpu_set(8) == range(1, 9)
    assert guard.cpu_set(15) == range(1, 16)
    assert guard.cpu_set(16) == range(0, 16)  # every CPU: CPU 0 too
    monkeypatch.setattr(os, "cpu_count", lambda: 1)
    assert guard.cpu_set(1) == range(0, 1)


@pytest.mark.skipif(sys.platform == "darwin", reason="macOS has no CPU affinity")
def test_run_pins_the_child_to_cpus_after_cpu_0(monkeypatch):
    if (os.cpu_count() or 1) < 2:
        pytest.skip("one CPU: nothing to pin")
    monkeypatch.setenv("GUARD_CPU_SHARE", "0.5")
    n = guard.heavy_cpus()
    # A pinned process never spins up more than its CPUs
    out = guard.run([PY, "-c", AFFINITY], capture_output=True, text=True, timeout=60)
    assert int(out.stdout) == ((1 << n) - 1) << 1  # CPUs 1..n


def test_tools_get_thread_counts_to_match(monkeypatch, tmp_path):
    from src.studio import cinematic, ffmpeg, motion

    monkeypatch.setenv("GUARD_CPU_SHARE", "0.5")
    monkeypatch.setattr(os, "cpu_count", lambda: 16)
    seen = []
    monkeypatch.setattr(guard, "run", lambda cmd, **k: seen.append([str(c) for c in cmd]) or
                        subprocess.CompletedProcess(cmd, 0, b"", b""))
    monkeypatch.setattr(cinematic, "find_blender", lambda: "blender")
    monkeypatch.setattr(guard, "gpu", lambda what, kind: contextlib.nullcontext())
    monkeypatch.setattr(cinematic, "GPU_BACKEND", "vulkan")
    cinematic.blender(["-b", "-P", "x.py"], "Blender test", 60)
    assert seen[-1][:6] == ["blender", "--gpu-backend", "vulkan", "-t", "8", "-b"]  # 176
    monkeypatch.setattr(ffmpeg, "find_ffmpeg", lambda: "ffmpeg")
    ffmpeg.run(["-i", "in.mp4", "-c:v", "libx264", "out.mp4"], timeout_s=60)
    assert seen[-1][-3:] == ["-threads", "8", "out.mp4"]
    assert motion._concurrency() == 4  # half of 8
    monkeypatch.setenv("GUARD_CPU_SHARE", "0.25")
    assert motion._concurrency() == 2


# --- catch-up ------------------------------------------------------------------------------

def test_catch_up_starts_one_run_then_waits_for_it_and_its_renders(store, settings, tmp_path,
                                                                   monkeypatch):
    from src.agent.proc import started as process_started

    books = tmp_path / "agent" / "playbooks"
    books.mkdir(parents=True)
    for name in ("daily-learn", "daily-produce"):
        (books / f"{name}.md").write_text("Go.\n")
    monkeypatch.setattr(schedule, "AGENT_DIR", tmp_path / "agent")
    s = settings.model_copy(update={"agent_schedule": "daily-learn@02:00,daily-produce@03:00",
                                    "timezone": "Europe/Paris"})
    now = lambda: datetime(2026, 11, 17, 4, 0, tzinfo=timezone.utc)  # noqa: E731 (05:00 Paris)
    started = []
    run = lambda st, se, pb: started.append(pb)  # noqa: E731
    assert schedule.catch_up(store, s, start=run, now=now) == ["daily-learn"]  # one, not two
    row = store.start_agent_run("daily-learn", os.getpid(), process_started(os.getpid()))
    assert schedule.busy(store) == "an agent run is running"
    assert schedule.catch_up(store, s, start=run, now=now) == []  # the next waits for it
    store.finish_agent_run(row["id"], "succeeded")
    job = store.add_render_job(store.add_asset(store.add_idea("motion")["id"])["id"], "k1")
    assert schedule.busy(store) == "renders are waiting"
    assert schedule.catch_up(store, s, start=run, now=now) == []  # ... and for its renders
    store.update_render_job(job["id"], state="done")
    assert schedule.busy(store) is None
    assert schedule.catch_up(store, s, start=run, now=now) == ["daily-produce"]
    assert started == ["daily-learn", "daily-produce"]


# --- every Blender / Remotion launch goes through the wrappers -----------------------------

LAUNCH = re.compile(r"blender\.exe|find_blender\(|render\.mjs")
# file -> why it may name Blender / Remotion
ALLOWED = {
    "src/studio/cinematic.py": "the Blender wrapper: blender()",
    "src/studio/motion.py": "the Remotion wrapper: _node() / _render()",
    "src/studio/doctor.py": "shows find_blender()'s path, launches nothing",
    "cinematic/setup.py": "downloads Blender, enables the add-on once (no render)",
}


def test_blender_and_remotion_launch_only_through_the_wrappers():
    files = [p for d in ("src", "cinematic", "vendor", "agent") for p in (ROOT / d).rglob("*.py")
             if "node_modules" not in p.parts and "tools" not in p.parts]
    offenders = [str(p.relative_to(ROOT)).replace("\\", "/") for p in files
                 if LAUNCH.search(p.read_text(encoding="utf-8", errors="replace"))]
    assert offenders and set(offenders) <= set(ALLOWED), offenders
    source = (ROOT / "src/studio/cinematic.py").read_text(encoding="utf-8")
    callers = re.findall(r"\ndef (\w+)\((?:(?!\ndef ).)*?find_blender\(\)", source, re.S)
    assert callers == ["blender"], callers  # in cinematic.py too, only the wrapper launches
    motion = (ROOT / "src/studio/motion.py").read_text(encoding="utf-8")
    assert "subprocess.run(" not in motion and "Popen(" not in motion
