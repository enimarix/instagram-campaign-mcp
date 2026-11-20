"""
The resource guard (step 166, docs/DECISIONS.md 2026-11-20): the studio can never freeze the PC.

The owner's laptop (RTX 3070 Laptop, 8 GB VRAM, 32 GB RAM) froze hard twice: the voice model
and Blender on the GPU at once, everything at normal priority, heavy work right after logon.
Step 145's GPU lock (gpu_lock.py) keeps our own heavy jobs one at a time; this adds:

- Low priority: every heavy child (Blender, Remotion's node and its Chrome, ffmpeg, the voice
  service and its model worker, agent CLI runs) starts through run() / low_priority():
  Windows BELOW_NORMAL_PRIORITY_CLASS, POSIX nice 10, so the owner's input never starves.
- Admission: gpu_lock.hold() calls admit() once it has the lock. The job waits (and logs
  "waiting for RAM / VRAM / a game") while free RAM < GUARD_MIN_FREE_RAM_GB (8) and, when
  nvidia-smi answers, while free VRAM < the job's need (VRAM_GB) or another process (a game,
  a Blender started by hand) uses more than FOREIGN_VRAM_GB, or before GUARD_NOT_BEFORE (the
  voice service's copy of the studio's startup grace).
- Watchdog (studio side, the worker of `up`): every EVERY_S, free RAM < 3 GB or GPU > 88 °C
  suspends our heavy children; RAM > 6 GB and < 80 °C resumes them; still bad after 3 min, the
  newest is killed (its render fails with the reason and is retried; the voice model worker
  is just unloaded). Only processes under this one, named like a renderer or the voice
  model worker (its pid from the voice service's /health), are ever touched.

Stdlib only above the "studio side" line: the voice service (its own venv) loads this file by
path through gpu_lock.py. GUARD_NVIDIA_SMI overrides the nvidia-smi command (tests: none).
"""

from __future__ import annotations

import asyncio
import contextlib
import csv
import io
import logging
import os
import re
import signal
import subprocess
import sys
import time
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Set, Tuple

log = logging.getLogger("guard")

BELOW_NORMAL = 0x00004000  # Windows BELOW_NORMAL_PRIORITY_CLASS
NO_WINDOW = 0x08000000  # Windows CREATE_NO_WINDOW: probes flash no console
NICE = 10
# Free VRAM a job needs. Voice: VoxCPM2 + Whisper peaked at 6.83 GB allocated (tts.log,
# 2026-11-20) plus the CUDA context; Blender: the macro plates held 1.1 GB, MPFB troupes more;
# Remotion: Chrome's ANGLE. ponytail: constants, not measured per job.
VRAM_GB = {"voice": 7.0, "blender": 3.0, "remotion": 1.5}
FOREIGN_VRAM_GB = 1.0  # another process above this = a game: wait
MIN_FREE_RAM_GB = 8.0  # GUARD_MIN_FREE_RAM_GB overrides (0: no RAM check)
WAIT_POLL_S = 10.0
LOG_EVERY_S = 60.0
PROBE_TIMEOUT_S = 10.0
_QUIET = {"creationflags": NO_WINDOW} if sys.platform == "win32" else {}


def _nice() -> None:
    os.nice(NICE)


def low_priority(kwargs: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Popen keyword arguments `kwargs` plus a low CPU priority for the child (its own
    children inherit it)."""
    kw = dict(kwargs or {})
    if sys.platform == "win32":
        kw["creationflags"] = kw.get("creationflags", 0) | BELOW_NORMAL
    else:  # ponytail: preexec_fn calls only os.nice, no lock a thread could hold at fork
        kw["preexec_fn"] = _nice
    return kw


def lower_self() -> None:
    """This process, and the children it starts from now on, at low priority."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32")
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.SetPriorityClass.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        k32.SetPriorityClass(k32.GetCurrentProcess(), BELOW_NORMAL)
    else:
        os.setpriority(os.PRIO_PROCESS, 0, max(os.getpriority(os.PRIO_PROCESS, 0), NICE))


class Stopped(RuntimeError):
    """The watchdog killed this child: the machine was choking (the job is retried later)."""


KILLED: Dict[int, str] = {}  # run() child pid -> why the watchdog killed it (or its child)
_running: Set[int] = set()  # run() children alive in this process


def run(cmd: Sequence[Any], *, input: Any = None, timeout: Optional[float] = None,
        capture_output: bool = False, **kw: Any) -> subprocess.CompletedProcess:
    """subprocess.run at low priority (same arguments, TimeoutExpired kills the child).
    Raises Stopped when the watchdog killed the child or one of its children."""
    if capture_output:
        kw["stdout"] = kw["stderr"] = subprocess.PIPE
    if input is not None:
        kw["stdin"] = subprocess.PIPE
    with subprocess.Popen(cmd, **low_priority(kw)) as p:
        _running.add(p.pid)
        try:
            out, err = p.communicate(input, timeout=timeout)
        except subprocess.TimeoutExpired:
            p.kill()
            out, err = p.communicate()
            raise subprocess.TimeoutExpired(p.args, timeout, out, err) from None
        except BaseException:
            p.kill()
            raise
        finally:
            _running.discard(p.pid)
    reason = KILLED.pop(p.pid, None)
    if reason:
        raise Stopped(reason)
    return subprocess.CompletedProcess(p.args, p.returncode, out, err)


# --- probes -------------------------------------------------------------------------------

def free_ram_gb() -> Optional[float]:
    """Physical memory available now (GB), None when unknown."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class Status(ctypes.Structure):
            _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                        *[(f, ctypes.c_ulonglong) for f in (
                            "ullTotalPhys", "ullAvailPhys", "ullTotalPageFile",
                            "ullAvailPageFile", "ullTotalVirtual", "ullAvailVirtual",
                            "ullAvailExtendedVirtual")]]

        s = Status(dwLength=ctypes.sizeof(Status))
        ok = ctypes.WinDLL("kernel32").GlobalMemoryStatusEx(ctypes.byref(s))
        return s.ullAvailPhys / 2**30 if ok else None
    try:
        with open("/proc/meminfo", encoding="ascii") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / 2**20
    except (OSError, ValueError):
        pass
    return None  # e.g. macOS: no RAM check


def _smi(query: str) -> Optional[List[List[str]]]:
    exe = os.environ.get("GUARD_NVIDIA_SMI") or "nvidia-smi"
    try:
        out = subprocess.run([exe, query, "--format=csv,noheader,nounits"], capture_output=True,
                             text=True, timeout=PROBE_TIMEOUT_S, **_QUIET)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode:
        return None
    return [[c.strip() for c in line.split(",")] for line in out.stdout.splitlines()
            if line.strip()]


def gpu_status() -> Optional[Dict[str, float]]:
    """{free_vram_gb, temp_c} of the first NVIDIA GPU; None without nvidia-smi."""
    try:
        free, temp = (_smi("--query-gpu=memory.free,temperature.gpu") or [])[0][:2]
        return {"free_vram_gb": float(free) / 1024, "temp_c": float(temp)}
    except (IndexError, ValueError):
        return None


def gpu_processes() -> Dict[int, float]:
    """pid -> GB of dedicated VRAM, every process using the GPU; {} when unknown. Windows:
    the performance counters (WDDM hides per-process memory from nvidia-smi); elsewhere
    nvidia-smi's compute apps. ponytail: typeperf counter names are English-only."""
    used: Dict[int, float] = {}
    if sys.platform == "win32":
        try:
            out = subprocess.run(["typeperf", r"\GPU Process Memory(*)\Dedicated Usage",
                                  "-sc", "1"], capture_output=True, text=True,
                                 timeout=PROBE_TIMEOUT_S, **_QUIET).stdout
        except (OSError, subprocess.SubprocessError):
            return {}
        rows = [r for r in csv.reader(io.StringIO(out)) if len(r) > 1]
        if len(rows) < 2:
            return {}
        pairs = [(re.search(r"\(pid_(\d+)_", n), v) for n, v in zip(rows[0][1:], rows[1][1:])]
        gb = [(int(m[1]), v, 2**30) for m, v in pairs if m]
    else:
        gb = [(r[0], r[1], 1024) for r in _smi("--query-compute-apps=pid,used_memory") or []
              if len(r) > 1]
    for pid, value, unit in gb:
        with contextlib.suppress(ValueError):
            used[int(pid)] = used.get(int(pid), 0.0) + float(value) / unit
    return used


def blockers(need_vram_gb: float, min_free_ram_gb: float) -> List[str]:
    """Why a heavy job may not start now ([]: it may)."""
    why = []
    left = float(os.environ.get("GUARD_NOT_BEFORE") or 0) - time.time()
    if left > 0:
        why.append(f"waiting for the startup grace: {left / 60:.0f} min left")
    if min_free_ram_gb > 0:
        ram = free_ram_gb()
        if ram is not None and ram < min_free_ram_gb:
            why.append(f"waiting for RAM: {ram:.1f} GB free, {min_free_ram_gb:g} GB needed")
    gpu = gpu_status()
    if gpu is not None:
        if gpu["free_vram_gb"] < need_vram_gb:
            why.append(f"waiting for VRAM: {gpu['free_vram_gb']:.1f} GB free, "
                       f"{need_vram_gb:g} GB needed")
        games = [f"pid {pid} uses {gb:.1f} GB" for pid, gb in sorted(gpu_processes().items())
                 if gb > FOREIGN_VRAM_GB and pid != os.getpid()]
        if games:
            why.append(f"waiting for a game (another program on the GPU): {', '.join(games)}")
    return why


def admit(what: str, need_vram_gb: float = 0.0, min_free_ram_gb: Optional[float] = None, *,
          poll_s: float = WAIT_POLL_S, log_every_s: float = LOG_EVERY_S,
          check: Callable[[float, float], List[str]] = blockers) -> None:
    """Return once `what` may start (blockers() empty); wait and log meanwhile.
    min_free_ram_gb None: GUARD_MIN_FREE_RAM_GB, else MIN_FREE_RAM_GB."""
    if min_free_ram_gb is None:
        min_free_ram_gb = float(os.environ.get("GUARD_MIN_FREE_RAM_GB") or MIN_FREE_RAM_GB)
    start, next_log = time.monotonic(), 0.0
    while True:
        why = check(need_vram_gb, min_free_ram_gb)
        waited = time.monotonic() - start
        if not why:
            if next_log:
                log.warning("%s: starting after waiting %.0f s for resources", what, waited)
            return
        if waited >= next_log:
            next_log = waited + log_every_s
            log.warning("%s: %s", what, "; ".join(why))
        time.sleep(poll_s)


# --- studio side (the studio package; never reached from the voice service) ---------------

HEAVY_NAMES = {"blender", "ffmpeg", "node", "chrome", "chrome-headless-shell",
               "headless_shell", "rhubarb"}
EVERY_S = 10.0
SUSPEND_RAM_GB, RESUME_RAM_GB = 3.0, 6.0
SUSPEND_TEMP_C, RESUME_TEMP_C = 88.0, 80.0
KILL_AFTER_S = 180.0


@contextlib.contextmanager
def gpu(what: str, kind: str) -> Iterator[None]:
    """The machine's GPU lock, admitted for a studio job of `kind` (VRAM_GB)."""
    from ..config import get_settings
    from . import gpu_lock

    s = get_settings()
    with gpu_lock.hold(what, s.gpu_lock_path, need_vram_gb=VRAM_GB[kind],
                       min_free_ram_gb=s.guard_min_free_ram_gb):
        yield


def processes() -> List[Tuple[int, int, str]]:
    """(pid, parent pid, lower-case name without .exe) of every process; [] when unknown."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class Entry(ctypes.Structure):
            _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                        ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                        ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                        ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                        ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]

        k32 = ctypes.WinDLL("kernel32")
        k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        k32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
        for f in (k32.Process32FirstW, k32.Process32NextW):
            f.argtypes = (wintypes.HANDLE, ctypes.POINTER(Entry))
        k32.CloseHandle.argtypes = (wintypes.HANDLE,)
        snap = k32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
        if not snap or snap == ctypes.c_void_p(-1).value:
            return []
        out, e = [], Entry(dwSize=ctypes.sizeof(Entry))
        try:
            ok = k32.Process32FirstW(snap, ctypes.byref(e))
            while ok:
                name = e.szExeFile.lower()
                out.append((e.th32ProcessID, e.th32ParentProcessID,
                            name[:-4] if name.endswith(".exe") else name))
                ok = k32.Process32NextW(snap, ctypes.byref(e))
        finally:
            k32.CloseHandle(snap)
        return out
    out = []
    for stat in os.listdir("/proc") if os.path.isdir("/proc") else ():
        if stat.isdigit():
            with contextlib.suppress(OSError, ValueError, IndexError):
                with open(f"/proc/{stat}/stat", encoding="utf-8", errors="replace") as f:
                    text = f.read()
                name, rest = text[text.index("(") + 1:].rsplit(")", 1)
                out.append((int(stat), int(rest.split()[1]), name.lower()))
    return out


def heavy_children(root: int, voice_pid: Optional[int] = None,
                   table: Optional[List[Tuple[int, int, str]]] = None) -> List[int]:
    """Our heavy processes: under `root`, named like a renderer (HEAVY_NAMES), or the voice
    model worker `voice_pid` (and its children; never the voice service itself). A child must
    be younger than its parent: Windows keeps a dead parent's pid in its children, and pids
    get reused."""
    from ..agent.proc import started

    kids: Dict[int, List[Tuple[int, str]]] = {}
    for pid, ppid, name in processes() if table is None else table:
        if pid != ppid:
            kids.setdefault(ppid, []).append((pid, name))
    out, seen = [], {root}
    todo = [(root, False)]
    while todo:
        parent, in_voice = todo.pop()
        born = started(parent)
        for pid, name in kids.get(parent, ()):
            if pid in seen:
                continue
            child_born = started(pid)
            if born and child_born and child_born < born:
                continue  # the pid's real parent died: not ours
            seen.add(pid)
            voice = in_voice or pid == voice_pid
            if voice or name in HEAVY_NAMES:
                out.append(pid)
            todo.append((pid, voice))
    return out


def _act(pid: int, action: str) -> None:
    """suspend | resume | kill one process. OSError when it can't."""
    if action == "kill":
        os.kill(pid, signal.SIGTERM if sys.platform == "win32" else signal.SIGKILL)
        return  # Windows: SIGTERM = TerminateProcess, a suspended process included
    if sys.platform != "win32":
        os.kill(pid, signal.SIGSTOP if action == "suspend" else signal.SIGCONT)
        return
    import ctypes
    from ctypes import wintypes

    k32, nt = ctypes.WinDLL("kernel32", use_last_error=True), ctypes.WinDLL("ntdll")
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    k32.CloseHandle.argtypes = (wintypes.HANDLE,)
    call = nt.NtSuspendProcess if action == "suspend" else nt.NtResumeProcess
    call.argtypes = (wintypes.HANDLE,)
    handle = k32.OpenProcess(0x0800, False, pid)  # PROCESS_SUSPEND_RESUME
    if not handle:
        raise OSError(ctypes.get_last_error(), f"cannot open process {pid}")
    try:
        status = call(handle)
    finally:
        k32.CloseHandle(handle)
    if status:
        raise OSError(f"{action} of process {pid}: NTSTATUS {status & 0xFFFFFFFF:#x}")


class Watchdog:
    """Pauses our heavy children while the machine chokes (see the module doc). tick() every
    EVERY_S returns what it did (for an alert); resume_all() when the studio stops."""

    def __init__(self, root: Optional[int] = None,
                 voice_pid: Callable[[], Optional[int]] = lambda: None, *,
                 probe: Optional[Callable[[], Tuple[Optional[float], Optional[float]]]] = None,
                 children: Callable[..., List[int]] = heavy_children,
                 act: Callable[[int, str], None] = _act,
                 clock: Callable[[], float] = time.monotonic):
        from ..agent.proc import started

        self.root, self.voice_pid, self.children, self.act = (
            root or os.getpid(), voice_pid, children, act)
        self.probe, self.clock, self.started = probe or self._probe, clock, started
        self.suspended: Dict[int, int] = {}  # pid -> creation time (pid reuse check)
        self.since: Optional[float] = None  # when the current bad spell paused something

    @staticmethod
    def _probe() -> Tuple[Optional[float], Optional[float]]:
        g = gpu_status()
        return free_ram_gb(), g and g["temp_c"]

    def _ours(self, pid: int) -> bool:
        born = self.suspended.get(pid)
        return born is not None and self.started(pid) == born

    def resume_all(self) -> int:
        n = 0
        for pid in list(self.suspended):
            if self._ours(pid):
                with contextlib.suppress(OSError):
                    self.act(pid, "resume")
                    n += 1
        self.suspended.clear()
        self.since = None
        return n

    def tick(self) -> List[str]:
        ram, temp = self.probe()
        state = ", ".join([*([f"free RAM {ram:.1f} GB"] if ram is not None else []),
                           *([f"GPU {temp:.0f} °C"] if temp is not None else [])])
        bad = (ram is not None and ram < SUSPEND_RAM_GB) or (
            temp is not None and temp > SUSPEND_TEMP_C)
        good = (ram is None or ram > RESUME_RAM_GB) and (temp is None or temp < RESUME_TEMP_C)
        self.suspended = {p: t for p, t in self.suspended.items() if self._ours(p)}
        done = []
        if bad:
            paused = 0
            for pid in self.children(self.root, self.voice_pid()):
                born = self.started(pid)
                if pid in self.suspended or born is None:
                    continue
                with contextlib.suppress(OSError):
                    self.act(pid, "suspend")
                    self.suspended[pid] = born
                    paused += 1
            if paused:
                done.append(f"paused {paused} heavy job process(es): {state}")
        if self.suspended and good:
            done.append(f"resumed {self.resume_all()} paused process(es): {state}")
        elif self.suspended:
            now = self.clock()
            self.since = self.since if self.since is not None else now
            if now - self.since >= KILL_AFTER_S:
                newest = max(self.suspended, key=self.suspended.__getitem__)
                why = (f"stopped by the resource guard: {state} for "
                       f"{KILL_AFTER_S / 60:g} min; retried later")
                self._mark(newest, why)
                with contextlib.suppress(OSError):
                    self.act(newest, "kill")
                del self.suspended[newest]
                self.since = now  # the next one gets as long
                done.append(f"stopped process {newest}: {state} for {KILL_AFTER_S / 60:g} min")
        return done

    def _mark(self, pid: int, why: str) -> None:
        """Tell the run() waiting on `pid`, or on one of its parents, why it ends."""
        parent = {p: pp for p, pp, _ in processes()}
        while pid and pid != self.root:
            if pid in _running:
                KILLED[pid] = why
            pid = parent.get(pid, 0)


async def watchdog_loop(store: Any, voice_pid: Callable[[], Optional[int]] = lambda: None,
                        every_s: float = EVERY_S, dog: Optional[Watchdog] = None) -> None:
    """The `up` worker's watchdog: a tick (in a thread: nvidia-smi may be slow) every
    `every_s`, an alert on the website each time it acts; resumes what it paused when it
    stops."""
    from ..store import utcnow
    from .alerts import raise_alert

    dog = dog or Watchdog(voice_pid=voice_pid)
    tick: Optional[asyncio.Future] = None
    try:
        while True:
            tick = asyncio.ensure_future(asyncio.to_thread(dog.tick))
            done = await asyncio.shield(tick)  # a thread can't be cancelled: awaited below
            if done:
                log.warning("resource guard: %s", "; ".join(done))
                with contextlib.suppress(Exception):  # e.g. database locked: still guarding
                    raise_alert(store, "guard", None, "warn", "The resource guard stepped in",
                                "; ".join(done), "/settings", utcnow(), renew=True)
            await asyncio.sleep(every_s)
    finally:
        if tick is not None and not tick.done():
            await asyncio.wait({tick})
        dog.resume_all()
