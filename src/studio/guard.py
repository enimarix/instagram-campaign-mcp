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
  nvidia-smi answers, while free VRAM < the job's need (VRAM_GB) or the card is busy above
  GAME_GPU_PCT (a game, a Blender started by hand: nothing of ours runs before admission).

Heat budget (step 171, docs/DECISIONS.md 2026-11-21): the laptop powered itself off under ONE
long Blender render (16 CPU threads + the GPU at its 130 W limit, ~220 W on a 230 W adapter).
Every heavy child runs on GUARD_CPU_SHARE of the logical CPUs, CPU 1 onward (pin(), inherited
by its own children; CPU 0 takes most interrupts and driver DPCs, 177: left to Windows) and
the tools' thread counts match heavy_cpus() (Blender -t, ffmpeg -threads, Remotion
--concurrency, the voice's torch and Whisper).

2026-11-25 (docs/DECISIONS.md): the watchdog that paused and killed running jobs (low RAM,
GPU heat and power, CPU throttling, the 15-min duty cycle) and the startup grace are gone:
the GPU clock cap (1500 MHz) keeps the card cool, and the RAM kill stopped a voice model
mid-load. The worker of `up` still writes data/logs/guard.log (log_loop: GPU heat, power,
VRAM, graphics clock, CPU limit, RAM, the lock holder) while the GPU lock is held, synced
line by line so it survives a power cut.

Stdlib only above the "studio side" line: the voice service (its own venv) loads this file by
path through gpu_lock.py. GUARD_NVIDIA_SMI overrides the nvidia-smi command (tests: none).
"""

from __future__ import annotations

import asyncio
import contextlib
import csv
import ctypes
import io
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence

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
# 2026-11-23: the GPU busy above this = a game: wait. Not Windows' per-process "GPU Process
# Memory" counters: they gave Discord 3.4 GB and dwm 1.5 GB while the whole card used 0.9 GB,
# so every voice waited forever. ponytail: one sample, a spike only costs a WAIT_POLL_S.
GAME_GPU_PCT = 40.0
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


def cpu_set(n: int) -> range:
    """The logical CPUs a heavy job runs on: `n` of them from CPU 1 (CPU 0 takes most
    interrupts and the NVIDIA driver's DPCs, whose stall bluescreened the laptop, 177), side
    by side: Windows and Linux number a core's two hyperthreads together, so fewer physical
    cores heat up. All of them (from 0) when `n` is every CPU."""
    total = os.cpu_count() or 1
    first = 1 if n < total else 0
    return range(first, first + min(n, total))


def pin(pid: int = 0, n: Optional[int] = None) -> None:
    """Keep process `pid` (0: this one) on cpu_set(`n`) (default heavy_cpus()); the children
    it starts later inherit it. OSError when it can't (the process is gone). ponytail: one
    processor group (<= 64 CPUs)."""
    cpus = cpu_set(n or heavy_cpus())
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
            mask = sum(1 << c for c in cpus if c < 64)
            if not k32.SetProcessAffinityMask(handle, mask):
                raise OSError(ctypes.get_last_error(), f"cannot pin process {pid}")
        finally:
            k32.CloseHandle(handle)
    elif hasattr(os, "sched_setaffinity"):  # macOS has none: no pinning there
        os.sched_setaffinity(pid, cpus)


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


class _JobLimits(ctypes.Structure):  # JOBOBJECT_EXTENDED_LIMIT_INFORMATION
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", ctypes.c_uint32), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", ctypes.c_uint32),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", ctypes.c_uint32),
                ("SchedulingClass", ctypes.c_uint32), ("IoInfo", ctypes.c_uint64 * 6),
                ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]


def _k32() -> Any:
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateJobObjectW.restype = wintypes.HANDLE
    k32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
    k32.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                            wintypes.DWORD)
    k32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    k32.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
    k32.CloseHandle.argtypes = (wintypes.HANDLE,)
    return k32


def _job(p: subprocess.Popen) -> Optional[int]:
    """Windows: a Job Object holding child `p` and every process it starts, all killed when the
    job is closed: by run() at the end, or by the OS when this process dies, even killed (the
    GPU lock, an OS lock, is free then: no Blender or Remotion Chrome may run on, 2026-11-25).
    None elsewhere or when Windows refuses (a kill then falls back to taskkill /T).
    ponytail: a grandchild started in the child's first instant, before the assignment,
    escapes; CREATE_SUSPENDED + resume closes that gap if it ever bites."""
    if sys.platform != "win32":
        return None
    k32 = _k32()
    job = k32.CreateJobObjectW(None, None)
    if not job:
        return None
    info = _JobLimits(LimitFlags=0x2000)  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if (k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))  # extended
            and k32.AssignProcessToJobObject(job, int(p._handle))):  # Popen's process handle
        return job
    k32.CloseHandle(job)
    return None


def _kill_tree(p: subprocess.Popen, job: Optional[int]) -> None:
    """Kill the child and everything it started (Remotion's node starts Chrome)."""
    if job:
        _k32().TerminateJobObject(job, 1)
    elif sys.platform == "win32":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True, **_QUIET)
    else:
        with contextlib.suppress(OSError):  # it may have exited already
            os.killpg(p.pid, signal.SIGKILL)
    p.kill()


def run(cmd: Sequence[Any], *, input: Any = None, timeout: Optional[float] = None,
        capture_output: bool = False, **kw: Any) -> subprocess.CompletedProcess:
    """subprocess.run at low priority on heavy_cpus() (same arguments; TimeoutExpired kills
    the child). The child's whole process tree is killed with it, and on Windows (_job) dies
    when the run ends or this process dies."""
    if capture_output:
        kw["stdout"] = kw["stderr"] = subprocess.PIPE
    if input is not None:
        kw["stdin"] = subprocess.PIPE
    if sys.platform != "win32":
        kw.setdefault("start_new_session", True)  # its own process group: killpg
    with subprocess.Popen(cmd, **low_priority(kw)) as p:
        job = _job(p)
        try:
            if sys.platform == "win32":
                with contextlib.suppress(OSError):  # it may have exited already
                    pin(p.pid)
            out, err = p.communicate(input, timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_tree(p, job)
            out, err = p.communicate()
            raise subprocess.TimeoutExpired(p.args, timeout, out, err) from None
        except BaseException:
            _kill_tree(p, job)
            raise
        finally:
            if job:
                _k32().CloseHandle(job)  # kills what it left running
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
    """{free_vram_gb, temp_c, power_w, power_limit_w, util_pct, used_vram_gb, total_vram_gb,
    clock_mhz} of the first NVIDIA GPU (the last six None when it does not say); None without
    nvidia-smi. clock_mhz is the graphics clock: above ~1600 the owner's clock cap is missing
    (177: an uncapped 2100 MHz boost crashed the PC)."""
    try:
        free, temp, *rest = (_smi("--query-gpu=memory.free,temperature.gpu,power.draw,"
                                  "enforced.power.limit,utilization.gpu,memory.used,"
                                  "memory.total,clocks.gr") or [])[0][:8]
        power, limit, util, used, total, clock = (*map(_num, rest), *[None] * 6)[:6]
        return {"free_vram_gb": float(free) / 1024, "temp_c": float(temp), "power_w": power,
                "power_limit_w": limit, "util_pct": util,
                "used_vram_gb": None if used is None else used / 1024,
                "total_vram_gb": None if total is None else total / 1024, "clock_mhz": clock}
    except (IndexError, ValueError):
        return None


def vram_used_gb() -> Optional[float]:
    """The first NVIDIA GPU's used VRAM (GB, every process), None without nvidia-smi: one
    quick query, for sampling (troupe.measure)."""
    try:
        return float((_smi("--query-gpu=memory.used") or [])[0][0]) / 1024
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


def blockers(need_vram_gb: float, min_free_ram_gb: float) -> List[str]:
    """Why a heavy job may not start now ([]: it may)."""
    why = []
    if min_free_ram_gb > 0:
        ram = free_ram_gb()
        if ram is not None and ram < min_free_ram_gb:
            why.append(f"waiting for RAM: {ram:.1f} GB free, {min_free_ram_gb:g} GB needed")
    gpu = gpu_status()
    if gpu is not None:
        if gpu["free_vram_gb"] < need_vram_gb:
            why.append(f"waiting for VRAM: {gpu['free_vram_gb']:.1f} GB free, "
                       f"{need_vram_gb:g} GB needed")
        if (gpu.get("util_pct") or 0) > GAME_GPU_PCT:
            why.append(f"waiting for a game (the GPU is busy): {gpu['util_pct']:.0f} %")
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
            path = wait_log_path()
            if path:  # where the owner looks (2026-11-25: a wait for RAM showed nowhere)
                with contextlib.suppress(OSError):
                    write_log(path, f"{what}: {'; '.join(why)}")
        time.sleep(poll_s)


def wait_log_path() -> Optional[Path]:
    """guard.log for admission waits (None: none written): GUARD_LOG_PATH (the voice service
    gets it from the studio), else the studio's own when its guard_log setting is on."""
    if os.environ.get("GUARD_LOG_PATH"):
        return Path(os.environ["GUARD_LOG_PATH"])
    if __package__:  # the studio package
        from ..config import APP_HOME, get_settings
        if get_settings().guard_log:
            return APP_HOME / "data" / "logs" / "guard.log"
    return None


# --- studio side (the studio package; never reached from the voice service) ---------------

STATE_EVERY_S = 30.0  # a guard.log state line this often while the GPU lock is held
LOG_MAX_BYTES = 4 * 2**20  # then guard.log -> guard.log.1


@contextlib.contextmanager
def gpu(what: str, kind: str) -> Iterator[None]:
    """The machine's GPU lock, admitted for a studio job of `kind` (VRAM_GB)."""
    from ..config import get_settings
    from . import gpu_lock

    s = get_settings()
    with gpu_lock.hold(what, s.gpu_lock_path, need_vram_gb=VRAM_GB[kind],
                       min_free_ram_gb=s.guard_min_free_ram_gb):
        yield


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


def state_line(by: str) -> str:
    """The machine now, for guard.log: GPU heat, power, use, VRAM, graphics clock (above
    ~1600 MHz the owner's clock cap is missing, 177), CPU limit, free RAM, the lock holder."""
    g = gpu_status() or {}
    return (f"GPU {_n(g.get('temp_c'))} °C {_n(g.get('power_w'))}/{_n(g.get('power_limit_w'))} W "
            f"{_n(g.get('util_pct'))} % | VRAM {_n(g.get('used_vram_gb'), '.1f')}/"
            f"{_n(g.get('total_vram_gb'), '.1f')} GB used, clock {_n(g.get('clock_mhz'))} MHz | "
            f"CPU limit {_n(cpu_perf_limit())} % | RAM {_n(free_ram_gb(), '.1f')} GB free | "
            f"lock {by}")


async def log_loop(every_s: float = STATE_EVERY_S, log_path: Optional[Path] = None) -> None:
    """The `up` worker's guard.log: a state line every `every_s` while the GPU lock is held
    (2026-11-25: it only watches now; nothing pauses or stops a job, docs/DECISIONS.md)."""
    from ..config import APP_HOME, get_settings
    from . import gpu_lock

    path = Path(log_path) if log_path else APP_HOME / "data" / "logs" / "guard.log"
    while True:
        by = await asyncio.to_thread(gpu_lock.held_by, get_settings().gpu_lock_path)
        if by:
            line = await asyncio.to_thread(state_line, by)  # nvidia-smi, typeperf: slow
            with contextlib.suppress(OSError):  # a full disk never stops the studio
                write_log(path, line)
        await asyncio.sleep(every_s)
