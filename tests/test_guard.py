"""Step 166: the resource guard (src/studio/guard.py). Fakes everywhere, except dummy child
processes started here (never a real render, never a process this test did not start)."""

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
from src.studio import alerts, gpu_lock, guard

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
    assert not guard._running


def test_a_child_the_watchdog_killed_raises_stopped_with_the_reason():
    def kill_when_started():
        deadline = time.monotonic() + 30
        while not guard._running and time.monotonic() < deadline:
            time.sleep(0.02)
        pid = next(iter(guard._running))
        guard.KILLED[pid] = "stopped by the resource guard: free RAM 2.0 GB for 3 min"
        guard._act(pid, "kill")

    threading.Thread(target=kill_when_started, daemon=True).start()
    with pytest.raises(guard.Stopped, match="free RAM 2.0 GB"):
        guard.run([PY, "-c", "import time; time.sleep(60)"], timeout=60)
    assert not guard.KILLED


def test_suspend_and_resume_a_real_dummy_child(tmp_path):
    out = tmp_path / "ticks"
    child = subprocess.Popen([PY, "-c", (
        "import sys, time\n"
        "with open(sys.argv[1], 'a') as f:\n"
        "    while True:\n"
        "        f.write('.'); f.flush(); time.sleep(0.02)\n"), str(out)])
    try:
        deadline = time.monotonic() + 30
        while (not out.exists() or out.stat().st_size < 3) and time.monotonic() < deadline:
            time.sleep(0.05)
        guard._act(child.pid, "suspend")
        time.sleep(0.2)
        paused = out.stat().st_size
        time.sleep(0.4)
        assert out.stat().st_size == paused  # suspended: no tick
        guard._act(child.pid, "resume")
        deadline = time.monotonic() + 10
        while out.stat().st_size == paused and time.monotonic() < deadline:
            time.sleep(0.05)
        assert out.stat().st_size > paused
    finally:
        child.kill()
        child.wait()


def test_blockers_name_ram_vram_a_game_and_the_grace(monkeypatch):
    monkeypatch.setattr(guard, "free_ram_gb", lambda: 5.0)
    monkeypatch.setattr(guard, "gpu_status", lambda: {"free_vram_gb": 2.0, "temp_c": 60.0})
    monkeypatch.setattr(guard, "gpu_processes", lambda: {4242: 3.5, 7: 0.2, os.getpid(): 5.0})
    monkeypatch.setenv("GUARD_NOT_BEFORE", str(time.time() + 300))
    why = guard.blockers(3.0, 8.0)
    assert [w.split(":")[0] for w in why] == ["waiting for the startup grace", "waiting for RAM",
                                             "waiting for VRAM", "waiting for a game (another "
                                             "program on the GPU)"]
    assert "pid 4242 uses 3.5 GB" in why[3] and f"pid {os.getpid()}" not in why[3]
    monkeypatch.setenv("GUARD_NOT_BEFORE", "0")
    monkeypatch.setattr(guard, "free_ram_gb", lambda: 20.0)
    monkeypatch.setattr(guard, "gpu_status", lambda: {"free_vram_gb": 7.5, "temp_c": 60.0})
    monkeypatch.setattr(guard, "gpu_processes", lambda: {7: 0.2})
    assert guard.blockers(guard.VRAM_GB["voice"], 8.0) == []


def test_no_nvidia_smi_means_no_gpu_check(monkeypatch):
    monkeypatch.setattr(guard, "free_ram_gb", lambda: None)  # unknown: no RAM check either
    monkeypatch.setattr(guard, "gpu_processes", lambda: pytest.fail("no GPU to look at"))
    assert guard.gpu_status() is None  # conftest: GUARD_NVIDIA_SMI names nothing
    assert guard.blockers(7.0, 8.0) == []


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


# --- watchdog -----------------------------------------------------------------------------

class Box:
    """Probes are (free RAM, GPU °C) or a dict of Watchdog._probe's keys."""

    def __init__(self, *probes, log_path=None):
        self.probes, self.now, self.acts = list(probes), 0.0, []
        self.log_path = log_path

    def probe(self, heavy):
        r = self.probes.pop(0)
        return r if isinstance(r, dict) else {"ram": r[0], "temp": r[1]}

    def dog(self, children=(11, 12), theirs=(), holder="pid 7: Blender (dev)"):
        dog = guard.Watchdog(root=1, probe=self.probe,
                             children=lambda root, voice: list(children),
                             holder=lambda root: (holder, list(theirs)),
                             act=lambda pid, a: self.acts.append((a, pid)),
                             clock=lambda: self.now, log_path=self.log_path or Path(
                                 os.devnull))
        dog.started = lambda pid: {11: 100, 12: 200, 31: 300}.get(pid)  # 12 newer than 11
        dog._mark = lambda pid, why: self.acts.append(("mark", pid))
        return dog


@pytest.fixture(autouse=True)
def no_paused_time():
    guard._paused[:] = [0.0, None]
    yield
    guard._paused[:] = [0.0, None]


def test_watchdog_pauses_on_low_ram_and_resumes_when_it_is_back():
    box = Box((2.5, 60.0), (4.0, 60.0), (6.5, 60.0))
    dog = box.dog()
    assert dog.tick() == ["paused 2 heavy job process(es) (free RAM 2.5 GB): free RAM 2.5 GB, "
                          "GPU 60 °C"]
    assert dog.tick() == []  # between the marks: stays paused
    assert dog.tick() == ["resumed 2 paused process(es): free RAM 6.5 GB, GPU 60 °C"]
    assert box.acts == [("suspend", 11), ("suspend", 12), ("resume", 11), ("resume", 12)]


def test_watchdog_kills_the_newest_after_three_minutes_short_of_ram():
    box = Box((2.0, 60.0), (4.0, 60.0), (4.0, 60.0), (7.0, 60.0))
    dog = box.dog()
    assert dog.tick()[0].startswith("paused 2")
    box.now = guard.KILL_AFTER_S - 1
    assert dog.tick() == []
    box.now = guard.KILL_AFTER_S
    assert dog.tick() == ["stopped process 12: free RAM 4.0 GB, GPU 60 °C for 3 min"]
    assert dog.tick()[0].startswith("resumed 1")
    assert box.acts[2:] == [("mark", 12), ("kill", 12), ("resume", 11)]


def test_heat_pauses_at_83_resumes_at_74_and_never_kills():
    box = Box((20.0, 82.0), (20.0, 83.0), (20.0, 80.0), (20.0, 75.0), (20.0, 74.0))
    dog = box.dog()
    assert dog.tick() == []  # under the limit
    assert dog.tick()[0].startswith("paused 2 heavy job process(es) (GPU 83 °C)")
    box.now = 3600  # an hour hot: still paused, nothing killed (paused, it cools)
    assert dog.tick() == [] and dog.tick() == []
    assert dog.tick()[0].startswith("resumed 2")
    assert [a for a, _ in box.acts] == ["suspend", "suspend", "resume", "resume"]


def test_a_minute_at_the_gpu_power_limit_cools_three_minutes():
    hot = {"ram": 20.0, "temp": 70.0, "watts": 125.0, "limit": 130.0, "util": 99.0}
    box = Box(hot, {**hot, "watts": 100.0}, hot, hot, {**hot, "watts": 20.0},
              {**hot, "watts": 20.0})
    dog = box.dog()
    assert dog.tick() == []
    box.now = 30
    assert dog.tick() == []  # dipped under 95 %: the minute starts again
    box.now = 40
    assert dog.tick() == []
    box.now = 100
    assert dog.tick() == ["paused 2 heavy job process(es) (GPU at 96% of its 130 W limit for "
                          "60 s; cooling 3 min): free RAM 20.0 GB, GPU 70 °C"]
    box.now = 100 + guard.COOL_S - 1
    assert dog.tick() == []  # cooling
    box.now = 100 + guard.COOL_S
    assert dog.tick()[0].startswith("resumed 2")


def test_a_throttled_cpu_for_a_minute_cools_three_minutes():
    hot = {"ram": 20.0, "temp": 60.0, "perf": 62.0, "util": 50.0}
    box = Box(hot, hot)
    dog = box.dog()
    assert dog.tick() == []
    box.now = guard.SUSTAIN_S
    assert dog.tick()[0].startswith("paused 2 heavy job process(es) (CPU held back to 62 % "
                                    "(heat) for 60 s; cooling 3 min)")


def test_duty_cycle_cools_after_fifteen_busy_minutes():
    busy = {"ram": 20.0, "temp": 70.0, "util": 97.0}
    idle = {**busy, "util": 2.0}
    box = Box(busy, busy, busy, busy, busy, busy, idle, idle, busy)
    dog = box.dog()
    assert dog.max_busy_s == 15 * 60  # GUARD_MAX_BUSY_MIN default
    for t in (0, 600, 899):
        box.now = t
        assert dog.tick() == []
    box.now = 900
    assert "15 min of heavy work; cooling 3 min" in dog.tick()[0]
    box.now = 900 + guard.COOL_S
    assert dog.tick()[0].startswith("resumed 2")
    box.now = 1100
    assert dog.tick() == [] and dog.busy_since == 1100  # counting afresh
    box.now = 1200  # an idle GPU (a loaded voice model waiting) is no heavy work ...
    assert dog.tick() == []
    box.now = 1200 + guard.COOL_S  # ... and a rest as long as a cooling pause resets the count
    assert dog.tick() == [] and dog.busy_since is None
    box.now = 1500
    assert dog.tick() == [] and dog.busy_since == 1500


def test_watchdog_guards_the_gpu_lock_holders_processes():
    box = Box((2.0, 60.0), (9.0, 60.0))
    dog = box.dog(children=(), theirs=(31,))
    assert dog.tick()[0].startswith("paused 1")
    assert dog.tick()[0].startswith("resumed 1")
    assert box.acts == [("suspend", 31), ("resume", 31)]


def test_guard_log_has_a_line_per_action_and_every_30_s(tmp_path):
    log = tmp_path / "logs" / "guard.log"
    probe = {"ram": 18.2, "temp": 71.0, "watts": 98.0, "limit": 130.0, "util": 96.0,
             "perf": 100.0}
    box = Box(probe, probe, probe, {**probe, "temp": 84.0}, log_path=log)
    dog = box.dog(children=(11,))
    for t in (0, 10, 30, 31):
        box.now = t
        dog.tick()
    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3  # 0 s, 30 s, and the pause at 31 s
    assert lines[0].endswith("GPU 71 °C 98/130 W 96 % | CPU limit 100 % | RAM 18.2 GB free | "
                             "lock pid 7: Blender (dev) | heavy 1, paused 0")
    assert lines[2].endswith("GPU 84 °C 98/130 W 96 % | CPU limit 100 % | RAM 18.2 GB free | "
                             "lock pid 7: Blender (dev) | heavy 1, paused 1 | paused 1 heavy "
                             "job process(es) (GPU 84 °C): free RAM 18.2 GB, GPU 84 °C")


def test_guard_log_rotates(tmp_path, monkeypatch):
    log = tmp_path / "guard.log"
    monkeypatch.setattr(guard, "LOG_MAX_BYTES", 10)
    guard.write_log(log, "a" * 20)
    guard.write_log(log, "b")
    assert log.read_text(encoding="utf-8").endswith(" b\n")
    assert "a" * 20 in log.with_name("guard.log.1").read_text(encoding="utf-8")


def test_holder_tree_is_under_the_lock_holder_only(monkeypatch):
    born = {7: 10, 70: 20, 71: 21, 72: 22, 73: 5, 100: 1, 200: 30}
    monkeypatch.setattr("src.agent.proc.started", born.get)
    table = [(7, 1, "python"),  # a dev script holding the lock
             (70, 7, "blender"), (71, 70, "python"), (72, 7, "conhost"),
             (73, 7, "python"),  # older than the script: its real parent died
             (100, 1, "python"), (200, 100, "blender")]  # the studio and its own render
    monkeypatch.setattr(gpu_lock, "held_by", lambda path=None: "pid 7: Blender (dev) x")
    assert guard.holder_tree(100, table) == ("pid 7: Blender (dev) x", [70, 71])
    assert guard.holder_tree(7, table) == ("pid 7: Blender (dev) x", [])  # the studio: covered
    monkeypatch.setattr(gpu_lock, "held_by", lambda path=None: None)  # free: a stale .holder
    assert guard.holder_tree(100, table) == (None, [])


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


@pytest.mark.skipif(sys.platform == "darwin", reason="macOS has no CPU affinity")
def test_run_pins_the_child_to_the_first_cpus(monkeypatch):
    if (os.cpu_count() or 1) < 2:
        pytest.skip("one CPU: nothing to pin")
    monkeypatch.setenv("GUARD_CPU_SHARE", "0.5")
    n = guard.heavy_cpus()
    # A pinned process never spins up more than its CPUs
    out = guard.run([PY, "-c", AFFINITY], capture_output=True, text=True, timeout=60)
    assert int(out.stdout) == (1 << n) - 1  # CPUs 0..n-1


def test_tools_get_thread_counts_to_match(monkeypatch, tmp_path):
    from src.studio import cinematic, ffmpeg, motion

    monkeypatch.setenv("GUARD_CPU_SHARE", "0.5")
    monkeypatch.setattr(os, "cpu_count", lambda: 16)
    seen = []
    monkeypatch.setattr(guard, "run", lambda cmd, **k: seen.append([str(c) for c in cmd]) or
                        subprocess.CompletedProcess(cmd, 0, b"", b""))
    monkeypatch.setattr(cinematic, "find_blender", lambda: "blender")
    monkeypatch.setattr(guard, "gpu", lambda what, kind: contextlib.nullcontext())
    cinematic.blender(["-b", "-P", "x.py"], "Blender test", 60)
    assert seen[-1][:4] == ["blender", "-t", "8", "-b"]
    monkeypatch.setattr(ffmpeg, "find_ffmpeg", lambda: "ffmpeg")
    ffmpeg.run(["-i", "in.mp4", "-c:v", "libx264", "out.mp4"], timeout_s=60)
    assert seen[-1][-3:] == ["-threads", "8", "out.mp4"]
    assert motion._concurrency() == 4  # half of 8
    monkeypatch.setenv("GUARD_CPU_SHARE", "0.25")
    assert motion._concurrency() == 2


def test_run_timeout_skips_the_time_the_watchdog_kept_jobs_paused():
    guard._paused[:] = [0.0, time.monotonic()]  # a pause running now
    out = guard.run([PY, "-c", "import time; time.sleep(1.5); print('done')"],
                    capture_output=True, text=True, timeout=0.5)
    assert out.stdout.strip() == "done"


def test_watchdog_leaves_processes_alone_when_all_is_well():
    box = Box((None, None), (10.0, 70.0))
    dog = box.dog()
    assert dog.tick() == [] and dog.tick() == [] and box.acts == []


def test_watchdog_never_resumes_a_reused_pid():
    box = Box((2.0, None), (9.0, None))
    dog = box.dog(children=(11,))
    dog.tick()
    dog.started = lambda pid: 999  # 11 died and another process has the pid now
    assert dog.tick() == [] and box.acts == [("suspend", 11)]


def test_heavy_children_are_renderers_under_us_and_the_voice_worker(monkeypatch):
    born = {100: 50, 200: 60, 201: 60, 202: 60, 300: 70, 400: 80, 301: 85, 500: 90, 600: 10}
    monkeypatch.setattr("src.agent.proc.started", born.get)
    table = [(100, 1, "python"),  # the studio (root)
             (200, 100, "blender"), (201, 100, "python"),  # a render, the voice service
             (300, 201, "python"),  # its model worker
             (202, 100, "python"), (400, 202, "claude"), (301, 400, "python"),  # an agent run
             (500, 301, "blender"),  # its MCP server's preview
             (600, 100, "node"),  # older than the studio: its real parent died, not ours
             (700, 1, "blender"),  # the owner's own Blender
             (210, 100, "node"), (211, 210, "node")]  # the Reel downloader (no run() child)
    born.update({210: 60, 211: 61})
    assert sorted(guard.heavy_children(100, 300, table, ours={200})) == [200, 300, 500]
    assert sorted(guard.heavy_children(100, None, table, ours={200})) == [200, 500]  # unloaded


def test_process_table_has_this_process():
    table = {pid: (ppid, name) for pid, ppid, name in guard.processes()}
    if not table:
        pytest.skip("no process table on this OS")
    assert any(n in table[os.getpid()][1].lower() for n in ("python", "pytest"))  # Linux CI: "pytest"


async def test_watchdog_loop_raises_an_alert_and_resumes_on_stop(store):
    class Dog:
        resumed = 0

        def tick(self):
            return ["paused 1 heavy job process(es): free RAM 2.0 GB"]

        def resume_all(self):
            self.resumed += 1

    dog = Dog()
    task = asyncio.create_task(guard.watchdog_loop(store, every_s=3600, dog=dog))
    deadline = time.monotonic() + 5
    while not store.get_state(alerts.RAISED_KEY) and time.monotonic() < deadline:
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    raised = store.get_state(alerts.RAISED_KEY)["guard"]
    assert raised["title"] == "The resource guard stepped in" and "free RAM" in raised["detail"]
    assert dog.resumed == 1


# --- startup grace and catch-up -----------------------------------------------------------

async def test_no_render_or_agent_run_in_the_startup_grace(monkeypatch, settings, capsys):
    from src import scheduler

    started = []

    async def loop(store, settings):
        started.append("ran")

    monkeypatch.setattr(scheduler.worker, "render_loop", loop)
    monkeypatch.setattr(schedule, "catch_up_loop", loop)
    s = settings.model_copy(update={"guard_startup_grace_min": 1.0,
                                    "instagram_access_token": None})
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(scheduler._worker(s), 0.3)
    assert started == [] and "startup grace: no render or agent run for 1 min" in \
        capsys.readouterr().err


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
