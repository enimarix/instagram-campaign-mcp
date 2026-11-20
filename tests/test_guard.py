"""Step 166: the resource guard (src/studio/guard.py). Fakes everywhere, except dummy child
processes started here (never a real render, never a process this test did not start)."""

from __future__ import annotations

import asyncio
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
        assert kw["preexec_fn"] is guard._nice


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


def test_the_gpu_lock_admits_while_holding_it(monkeypatch, tmp_path):
    path = tmp_path / "gpu.lock"
    seen = []

    def admit(what, need, floor):
        try:  # another process (or handle) can't take the lock meanwhile
            with gpu_lock.file_lock(path, timeout_s=0):
                held = False
        except gpu_lock.LockTimeout:
            held = True
        seen.append((what, need, floor, held))

    monkeypatch.setattr(gpu_lock.guard, "admit", admit)
    with gpu_lock.hold("voice service", path, need_vram_gb=7.0, min_free_ram_gb=8.0):
        pass
    assert seen == [("voice service", 7.0, 8.0, True)]


def test_studio_jobs_ask_for_their_vram(monkeypatch, settings):
    seen = []
    monkeypatch.setattr(gpu_lock.guard, "admit", lambda what, need, floor: seen.append(
        (what, need, floor)))
    monkeypatch.setattr("src.config.get_settings", lambda: settings.model_copy(
        update={"guard_min_free_ram_gb": 9.0}))
    with guard.gpu("Remotion Hello render", "remotion"):
        pass
    assert seen == [("Remotion Hello render", 1.5, 9.0)]


# --- watchdog -----------------------------------------------------------------------------

class Box:
    def __init__(self, *probes):
        self.probes, self.now, self.acts = list(probes), 0.0, []

    def dog(self, children=(11, 12)):
        dog = guard.Watchdog(root=1, probe=lambda: self.probes.pop(0),
                             children=lambda root, voice: list(children),
                             act=lambda pid, a: self.acts.append((a, pid)),
                             clock=lambda: self.now)
        dog.started = lambda pid: {11: 100, 12: 200}.get(pid)  # 12 is the newest
        dog._mark = lambda pid, why: self.acts.append(("mark", pid))
        return dog


def test_watchdog_pauses_on_low_ram_and_resumes_when_it_is_back():
    box = Box((2.5, 60.0), (4.0, 60.0), (6.5, 60.0))
    dog = box.dog()
    assert dog.tick() == ["paused 2 heavy job process(es): free RAM 2.5 GB, GPU 60 °C"]
    assert dog.tick() == []  # between the marks: stays paused
    assert dog.tick() == ["resumed 2 paused process(es): free RAM 6.5 GB, GPU 60 °C"]
    assert box.acts == [("suspend", 11), ("suspend", 12), ("resume", 11), ("resume", 12)]


def test_watchdog_kills_the_newest_after_three_minutes_of_heat():
    box = Box((20.0, 90.0), (20.0, 85.0), (20.0, 85.0), (20.0, 79.0))
    dog = box.dog()
    assert dog.tick()[0].startswith("paused 2")
    box.now = guard.KILL_AFTER_S - 1
    assert dog.tick() == []
    box.now = guard.KILL_AFTER_S
    assert dog.tick() == ["stopped process 12: free RAM 20.0 GB, GPU 85 °C for 3 min"]
    assert dog.tick()[0].startswith("resumed 1")
    assert box.acts[2:] == [("mark", 12), ("kill", 12), ("resume", 11)]


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
             (700, 1, "blender")]  # the owner's own Blender
    assert sorted(guard.heavy_children(100, 300, table)) == [200, 300, 500]
    assert sorted(guard.heavy_children(100, None, table)) == [200, 500]  # no model loaded


def test_process_table_has_this_process():
    table = {pid: (ppid, name) for pid, ppid, name in guard.processes()}
    if not table:
        pytest.skip("no process table on this OS")
    assert "python" in table[os.getpid()][1]


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
