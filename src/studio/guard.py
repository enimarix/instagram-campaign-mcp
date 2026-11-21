"""
The resource guard (step 166, docs/DECISIONS.md 2026-11-20): the studio can never freeze the PC.

The owner's laptop (RTX 3070 Laptop, 8 GB VRAM, 32 GB RAM) froze hard twice: the voice model
and Blender on the GPU at once, everything at normal priority, heavy work right after logon.
Step 145's GPU lock (gpu_lock.py) keeps our own heavy jobs one at a time; this adds:

- Low priority: every heavy child (Blender, Remotion's node and its Chrome, ffmpeg, the voice
  service and its model worker, agent CLI runs) starts through run() / low_priority():
  Windows BELOW_NORMAL_PRIORITY_CLASS, POSIX nice 10, so the owner's input never starves.
- Admission: gpu_lock.hold() calls admit() before it takes the lock (and blockers() again
  once it has it, 175: a waiting job never holds the lock). The job waits (and logs
  "waiting for RAM / VRAM / a game") while free RAM < GUARD_MIN_FREE_RAM_GB (8) and, when
  nvidia-smi answers, while free VRAM < the job's need (VRAM_GB) or another process (a game,
  a Blender started by hand) uses more than FOREIGN_VRAM_GB, or before GUARD_NOT_BEFORE (the
  voice service's copy of the studio's startup grace).
- Watchdog (studio side, the worker of `up`): every EVERY_S, free RAM < 3 GB (or the heat
  below) suspends our heavy children; RAM > 6 GB (and cool) resumes them; RAM still short
  after 3 min, the newest is killed (its render fails with the reason and is retried; the
  voice model worker is just unloaded). Only processes under this one, named like a renderer
  or the voice model worker (its pid from the voice service's /health), and (171) the
  processes under the GPU lock's holder are ever touched.

Heat budget (step 171, docs/DECISIONS.md 2026-11-21): the laptop powered itself off under ONE
long Blender render (16 CPU threads + the GPU at its 130 W limit, ~220 W on a 230 W adapter).

- Less heat per job: every heavy child runs on the first GUARD_CPU_SHARE of the logical CPUs
  (pin(), inherited by its own children) and the tools' thread counts match heavy_cpus()
  (Blender -t, ffmpeg -threads, Remotion --concurrency, the voice's torch and Whisper).
- The watchdog also guards whoever holds the GPU lock (a dev script, gpu-run.py) and cools:
  GPU >= GUARD_SUSPEND_TEMP_C (83) until <= GUARD_RESUME_TEMP_C (74); 60 s at >= 95 % of the
  GPU power limit, or CPU throttling (% Performance Limit < 80) -> a COOL_S pause; after
  GUARD_MAX_BUSY_MIN of continuous heavy work, the same pause (duty cycle). It writes
  data/logs/guard.log, synced line by line so it survives a power cut. Heat never kills a job
  (paused, it cools down); only RAM still short after 3 min does. run() timeouts skip paused
  time.

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
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Set, Tuple

log = logging.getLogger("guard")

BELOW_NORMAL = 0x00004000  # Windows BELOW_NORMAL_PRIORITY_CLASS
NO_WINDOW = 0x08000000  # Windows CREATE_NO_WINDOW: probes flash no console
NICE = 10
# Free VRAM a job needs. Voice: VoxCPM2 + Whisper peaked at 6.83 GB allocated (tts.log,
# 2026-11-20) plus the CUDA context; Blender: the macro plates held 1.1 GB, MPFB troupes more;
# Remotion: Chrome's ANGLE. ponytail: constants, not measured per job.
# voice: ~5.8 GB loaded (6.7 GB card total with the ~0.9 GB desktop); 7.0 never fit beside the
# owner's open apps, so no voiced render could start (170)
VRAM_GB = {"voice": 6.0, "blender": 3.0, "remotion": 1.5}
FOREIGN_VRAM_GB = 1.0  # another process above this = a game: wait
MIN_FREE_RAM_GB = 8.0  # GUARD_MIN_FREE_RAM_GB overrides (0: no RAM check)
WAIT_POLL_S = 10.0
LOG_EVERY_S = 60.0
PROBE_TIMEOUT_S = 10.0
_QUIET = {"creationflags": NO_WINDOW} if sys.platform == "win32" else {}
CPU_SHARE = 0.5  # GUARD_CPU_SHARE overrides (171)


def cpu_share() -> float:
    """The share of the logical CPUs a heavy job may use: GUARD_CPU_SHARE, else the studio's
    setting (the voice service, loaded by path, gets the env var from the studio)."""
    if os.environ.get("GUARD_CPU_SHARE"):
        return float(os.environ["GUARD_CPU_SHARE"])
    if __package__:  # the studio package
        from ..config import get_settings
        return get_settings().guard_cpu_share
    return CPU_SHARE


def heavy_cpus() -> int:
    """How many logical CPUs (and threads) a heavy job gets: 8 of 16 by default."""
    total = os.cpu_count() or 1
    return max(1, min(total, round(total * cpu_share())))


def pin(pid: int = 0, n: Optional[int] = None) -> None:
    """Keep process `pid` (0: this one) on the first `n` logical CPUs (default heavy_cpus());
    the children it starts later inherit it. The first ones: Windows and Linux number a
    core's two hyperthreads side by side, so fewer physical cores heat up (8 of 16 = 4 cores).
    OSError when it can't (the process is gone). ponytail: one processor group (<= 64 CPUs)."""
    n = n or heavy_cpus()
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        k32.SetProcessAffinityMask.argtypes = (wintypes.HANDLE, ctypes.c_size_t)
        k32.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = k32.OpenProcess(0x0200, False, pid or os.getpid())  # PROCESS_SET_INFORMATION
        if not handle:
            raise OSError(ctypes.get_last_error(), f"cannot open process {pid}")
        try:
            if not k32.SetProcessAffinityMask(handle, (1 << min(n, 64)) - 1):
                raise OSError(ctypes.get_last_error(), f"cannot pin process {pid}")
        finally:
            k32.CloseHandle(handle)
    elif hasattr(os, "sched_setaffinity"):  # macOS has none: no pinning there
        os.sched_setaffinity(pid, range(n))


def low_priority(kwargs: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Popen keyword arguments `kwargs` plus a low CPU priority for the child (its own
    children inherit it); POSIX: pinned to heavy_cpus() too (Windows: run() pins it)."""
    kw = dict(kwargs or {})
    if sys.platform == "win32":
        kw["creationflags"] = kw.get("creationflags", 0) | BELOW_NORMAL
    else:  # ponytail: preexec_fn calls only os.nice / sched_setaffinity, no lock at fork
        n = heavy_cpus()  # read here: never load settings in the forked child

        def lower() -> None:
            os.nice(NICE)
            with contextlib.suppress(OSError):
                pin(0, n)

        kw["preexec_fn"] = lower
    return kw


def lower_self() -> None:
    """This process, and the children it starts from now on, at low priority on
    heavy_cpus()."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32")
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.SetPriorityClass.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        k32.SetPriorityClass(k32.GetCurrentProcess(), BELOW_NORMAL)
    else:
        os.setpriority(os.PRIO_PROCESS, 0, max(os.getpriority(os.PRIO_PROCESS, 0), NICE))
    with contextlib.suppress(OSError):
        pin()


class Stopped(RuntimeError):
    """The watchdog killed this child: the machine was choking (the job is retried later)."""


KILLED: Dict[int, str] = {}  # run() child pid -> why the watchdog killed it (or its child)
_running: Set[int] = set()  # run() children alive in this process
_paused: List[Any] = [0.0, None]  # [s the watchdog kept jobs paused, monotonic start of a pause]


def paused_s() -> float:
    """Seconds this process's watchdog has kept heavy jobs paused, so far."""
    total, since = _paused
    return total + (time.monotonic() - since if since is not None else 0.0)


def run(cmd: Sequence[Any], *, input: Any = None, timeout: Optional[float] = None,
        capture_output: bool = False, **kw: Any) -> subprocess.CompletedProcess:
    """subprocess.run at low priority on heavy_cpus() (same arguments, TimeoutExpired kills
    the child; time the watchdog kept it paused does not count). Raises Stopped when the
    watchdog killed the child or one of its children."""
    if capture_output:
        kw["stdout"] = kw["stderr"] = subprocess.PIPE
    if input is not None:
        kw["stdin"] = subprocess.PIPE
    with subprocess.Popen(cmd, **low_priority(kw)) as p:
        _running.add(p.pid)
        start, paused0, left = time.monotonic(), paused_s(), timeout
        try:
            if sys.platform == "win32":
                with contextlib.suppress(OSError):  # it may have exited already
                    pin(p.pid)
            while True:
                try:
                    out, err = p.communicate(input, timeout=left)
                    break
                except subprocess.TimeoutExpired:  # paused meanwhile: it gets that time back
                    left = start + timeout + paused_s() - paused0 - time.monotonic()
                    input = None  # sent already
                    if left <= 0:
                        raise
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


def _num(text: str) -> Optional[float]:
    try:
        return float(text)
    except ValueError:  # "[N/A]": a laptop GPU may not report it
        return None


def gpu_status() -> Optional[Dict[str, Optional[float]]]:
    """{free_vram_gb, temp_c, power_w, power_limit_w, util_pct} of the first NVIDIA GPU (the
    last three None when it does not say); None without nvidia-smi."""
    try:
        free, temp, *rest = (_smi("--query-gpu=memory.free,temperature.gpu,power.draw,"
                                  "enforced.power.limit,utilization.gpu") or [])[0][:5]
        power, limit, util = (*map(_num, rest), None, None, None)[:3]
        return {"free_vram_gb": float(free) / 1024, "temp_c": float(temp), "power_w": power,
                "power_limit_w": limit, "util_pct": util}
    except (IndexError, ValueError):
        return None


def cpu_perf_limit() -> Optional[float]:
    """Windows' % Performance Limit of the CPUs (100: not held back; lower: throttled by heat
    or power), None elsewhere or when unknown. Windows gives no CPU temperature without admin
    drivers (the ACPI zone reads a fixed 28 °C on the owner's laptop): this is the CPU's heat
    signal. ponytail: typeperf counter names are English-only."""
    if sys.platform != "win32":
        return None
    try:
        out = subprocess.run(["typeperf", r"\Processor Information(_Total)\% Performance Limit",
                              "-sc", "1"], capture_output=True, text=True,
                             timeout=PROBE_TIMEOUT_S, **_QUIET).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    rows = [r for r in csv.reader(io.StringIO(out)) if len(r) > 1]
    return _num(rows[1][1]) if len(rows) > 1 else None


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


def ram_floor(min_free_ram_gb: Optional[float] = None) -> float:
    """The free RAM a job needs: min_free_ram_gb, else GUARD_MIN_FREE_RAM_GB, else
    MIN_FREE_RAM_GB."""
    if min_free_ram_gb is not None:
        return min_free_ram_gb
    return float(os.environ.get("GUARD_MIN_FREE_RAM_GB") or MIN_FREE_RAM_GB)


def admit(what: str, need_vram_gb: float = 0.0, min_free_ram_gb: Optional[float] = None, *,
          poll_s: float = WAIT_POLL_S, log_every_s: float = LOG_EVERY_S,
          check: Optional[Callable[[float, float], List[str]]] = None) -> None:
    """Return once `what` may start (check, default blockers(), empty); wait and log
    meanwhile. min_free_ram_gb: see ram_floor()."""
    check = check or blockers
    min_free_ram_gb = ram_floor(min_free_ram_gb)
    start, next_log = time.monotonic(), None
    while True:
        why = check(need_vram_gb, min_free_ram_gb)
        waited = time.monotonic() - start
        if not why:
            if next_log is not None:
                log.warning("%s: starting after waiting %.0f s for resources", what, waited)
            return
        if next_log is None or waited >= next_log:
            next_log = waited + log_every_s
            log.warning("%s: %s", what, "; ".join(why))
        time.sleep(poll_s)


# --- studio side (the studio package; never reached from the voice service) ---------------

HEAVY_NAMES = {"blender", "ffmpeg", "node", "chrome", "chrome-headless-shell",
               "headless_shell", "rhubarb"}
EVERY_S = 10.0
SUSPEND_RAM_GB, RESUME_RAM_GB = 3.0, 6.0
KILL_AFTER_S = 180.0  # RAM still short this long while paused: the newest job is killed
# Heat (171). The temperatures and the duty cycle are settings (GUARD_SUSPEND_TEMP_C, ...).
POWER_SHARE = 0.95  # GPU draw / its power limit at or above this ...
CPU_LIMIT_PCT = 80.0  # ... or the CPU's % Performance Limit under this ...
SUSTAIN_S = 60.0  # ... this long while heavy work runs: cool for COOL_S
COOL_S = 180.0
BUSY_UTIL_PCT = 30.0  # GPU utilisation that counts as heavy work for the duty cycle
STATE_EVERY_S = 30.0  # a guard.log state line this often while heavy work runs
LOG_MAX_BYTES = 4 * 2**20  # then guard.log -> guard.log.1
SKIP_NAMES = {"conhost"}  # a console host under a lock holder: never paused


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
                   table: Optional[List[Tuple[int, int, str]]] = None,
                   ours: Optional[Set[int]] = None) -> List[int]:
    """Our heavy processes under `root`: its own children that run() started (`ours`), the
    processes named like a renderer (HEAVY_NAMES) deeper down (Remotion's Chrome, an agent
    run's previews), and the voice model worker `voice_pid` with its children (never the
    voice service itself, nor the Reel downloader's node). A child must be younger than its
    parent: Windows keeps a dead parent's pid in its children, and pids get reused."""
    from ..agent.proc import started

    ours = _running if ours is None else ours
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
            if parent == root and pid not in ours and name in HEAVY_NAMES:
                continue  # a service of ours (the Reel downloader's node), not a job
            if voice or pid in ours or name in HEAVY_NAMES:
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


def holder_tree(root: int, table: Optional[List[Tuple[int, int, str]]] = None
                ) -> Tuple[Optional[str], List[int]]:
    """(who holds the GPU lock now, None when free; the processes under that holder): a dev
    script's Blender, gpu-run.py's command, the voice model worker. Never the holder itself
    (a script, the voice service: it serves, the work is below it), and none when the holder
    is the studio `root` (heavy_children covers it). Younger than their parent, as there."""
    from ..agent.proc import started
    from ..config import get_settings
    from . import gpu_lock

    by = gpu_lock.held_by(get_settings().gpu_lock_path)
    m = re.match(r"pid (\d+):", by or "")
    if not m or int(m[1]) == root:
        return by, []
    kids: Dict[int, List[Tuple[int, str]]] = {}
    for pid, ppid, name in processes() if table is None else table:
        if pid != ppid:
            kids.setdefault(ppid, []).append((pid, name))
    out, seen, todo = [], {int(m[1])}, [int(m[1])]
    while todo:
        parent = todo.pop()
        born = started(parent)
        for pid, name in kids.get(parent, ()):
            child_born = started(pid)
            if pid in seen or (born and child_born and child_born < born):
                continue
            seen.add(pid)
            if name not in SKIP_NAMES:
                out.append(pid)
            todo.append(pid)
    return by, out


def write_log(path: Path, text: str) -> None:
    """One line into guard.log, on disk at once (fsync: it must survive a power cut); the
    file moves to guard.log.1 past LOG_MAX_BYTES."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        if path.stat().st_size > LOG_MAX_BYTES:
            os.replace(path, path.with_name(path.name + ".1"))
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{stamp} {text}\n")
        f.flush()
        os.fsync(f.fileno())


def _n(value: Optional[float], spec: str = ".0f") -> str:
    return "?" if value is None else format(value, spec)


class Watchdog:
    """Pauses our heavy children, and the GPU lock holder's, while the machine chokes or heats
    (see the module doc). tick() every EVERY_S returns what it did (for an alert);
    resume_all() when the studio stops."""

    def __init__(self, root: Optional[int] = None,
                 voice_pid: Callable[[], Optional[int]] = lambda: None, *,
                 probe: Optional[Callable[[bool], Dict[str, Optional[float]]]] = None,
                 children: Callable[..., List[int]] = heavy_children,
                 holder: Callable[[int], Tuple[Optional[str], List[int]]] = holder_tree,
                 act: Callable[[int, str], None] = _act,
                 clock: Callable[[], float] = time.monotonic,
                 log_path: Optional[Path] = None):
        from ..agent.proc import started
        from ..config import APP_HOME, get_settings

        s = get_settings()
        self.root, self.voice_pid, self.children, self.holder, self.act = (
            root or os.getpid(), voice_pid, children, holder, act)
        self.probe, self.clock, self.started = probe or self._probe, clock, started
        self.suspend_temp_c, self.resume_temp_c = s.guard_suspend_temp_c, s.guard_resume_temp_c
        self.max_busy_s = s.guard_max_busy_min * 60
        self.log_path = Path(log_path) if log_path else APP_HOME / "data" / "logs" / "guard.log"
        self.suspended: Dict[int, int] = {}  # pid -> creation time (pid reuse check)
        self.since: Optional[float] = None  # RAM still short while paused, since
        self.cool_until: Optional[float] = None  # a cooling pause lasts until then
        self.busy_since: Optional[float] = None  # the GPU working unpaused since
        self.idle_since: Optional[float] = None  # ... and resting since
        self.hot: Dict[str, float] = {}  # "power" | "cpu" -> held since
        self.next_line: Optional[float] = None  # next guard.log state line

    @staticmethod
    def _probe(heavy: bool) -> Dict[str, Optional[float]]:
        g = gpu_status() or {}
        return {"ram": free_ram_gb(), "temp": g.get("temp_c"), "watts": g.get("power_w"),
                "limit": g.get("power_limit_w"), "util": g.get("util_pct"),
                "perf": cpu_perf_limit() if heavy else None}  # typeperf: only when it matters

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
        if _paused[1] is not None:  # run() timeouts get this pause back
            _paused[0] += time.monotonic() - _paused[1]
            _paused[1] = None
        return n

    def tick(self) -> List[str]:
        now = self.clock()
        by, theirs = self.holder(self.root)
        targets = list(dict.fromkeys([*self.children(self.root, self.voice_pid()), *theirs]))
        self.suspended = {p: t for p, t in self.suspended.items() if self._ours(p)}
        r = self.probe(bool(targets))
        ram, temp, watts, limit, perf = (r.get(k) for k in ("ram", "temp", "watts", "limit",
                                                            "perf"))
        working = bool(targets) and not self.suspended
        util = r.get("util")
        if self.suspended:  # paused = cooling: the duty cycle counts afresh after
            self.busy_since = self.idle_since = None
        elif working and (util is None or util >= BUSY_UTIL_PCT):  # not an idle voice model
            self.idle_since = None
            self.busy_since = now if self.busy_since is None else self.busy_since
        elif self.busy_since is not None:  # a break as long as a cooling pause resets it
            self.idle_since = now if self.idle_since is None else self.idle_since
            if now - self.idle_since >= COOL_S:
                self.busy_since = self.idle_since = None
        for key, on in (("power", working and watts is not None and bool(limit)
                         and watts >= POWER_SHARE * limit),
                        ("cpu", working and perf is not None and perf < CPU_LIMIT_PCT)):
            if on:
                self.hot.setdefault(key, now)
            else:
                self.hot.pop(key, None)
        why = [*([f"free RAM {ram:.1f} GB"] if ram is not None and ram < SUSPEND_RAM_GB else []),
               *([f"GPU {temp:.0f} °C"] if temp is not None and temp >= self.suspend_temp_c
                 else [])]
        cool = []  # these pause for COOL_S
        if now - self.hot.get("power", now) >= SUSTAIN_S:
            cool.append(f"GPU at {watts / limit:.0%} of its {limit:.0f} W limit for "
                        f"{SUSTAIN_S:g} s")
        if now - self.hot.get("cpu", now) >= SUSTAIN_S:
            cool.append(f"CPU held back to {perf:.0f} % (heat) for {SUSTAIN_S:g} s")
        if (working and self.max_busy_s and self.busy_since is not None
                and now - self.busy_since >= self.max_busy_s):
            cool.append(f"{self.max_busy_s / 60:g} min of heavy work")
        if cool:
            self.cool_until = now + COOL_S
            why += [*cool, f"cooling {COOL_S / 60:g} min"]
        cooling = self.cool_until is not None and now < self.cool_until
        state = ", ".join([*([f"free RAM {ram:.1f} GB"] if ram is not None else []),
                           *([f"GPU {temp:.0f} °C"] if temp is not None else [])])
        done = []
        if why or cooling:
            paused = 0
            for pid in targets:
                born = self.started(pid)
                if pid in self.suspended or born is None:
                    continue
                with contextlib.suppress(OSError):
                    self.act(pid, "suspend")
                    self.suspended[pid] = born
                    paused += 1
            if paused:
                if _paused[1] is None:
                    _paused[1] = time.monotonic()
                done.append(f"paused {paused} heavy job process(es) ({'; '.join(why) or 'cooling'})"
                            f": {state}")
        ram_ok = ram is None or ram > RESUME_RAM_GB
        if self.suspended and ram_ok and not cooling and (
                temp is None or temp <= self.resume_temp_c):
            done.append(f"resumed {self.resume_all()} paused process(es): {state}")
        elif self.suspended and not ram_ok:  # heat passes while paused; RAM may not
            self.since = self.since if self.since is not None else now
            if now - self.since >= KILL_AFTER_S:
                newest = max(self.suspended, key=self.suspended.__getitem__)
                why_killed = (f"stopped by the resource guard: {state} for "
                              f"{KILL_AFTER_S / 60:g} min; retried later")
                self._mark(newest, why_killed)
                with contextlib.suppress(OSError):
                    self.act(newest, "kill")
                del self.suspended[newest]
                self.since = now  # the next one gets as long
                done.append(f"stopped process {newest}: {state} for {KILL_AFTER_S / 60:g} min")
        else:
            self.since = None
        if done or ((targets or self.suspended)
                    and (self.next_line is None or now >= self.next_line)):
            self.next_line = now + STATE_EVERY_S
            line = (f"GPU {_n(temp)} °C {_n(watts)}/{_n(limit)} W {_n(util)} % | "
                    f"CPU limit {_n(perf)} % | RAM {_n(ram, '.1f')} GB free | "
                    f"lock {by or 'free'} | heavy {len(targets)}, paused {len(self.suspended)}"
                    + "".join(f" | {d}" for d in done))
            with contextlib.suppress(OSError):  # a full disk never stops the guarding
                write_log(self.log_path, line)
        elif not targets and not self.suspended:
            self.next_line = None
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
