"""
One heavy GPU job at a time on this machine (step 145, docs/DECISIONS.md 2026-11-19): the
owner's 8 GB laptop froze with the voice model resident and two Blender renders at once.

Every process that uses the GPU holds the same OS file lock while it does: Blender and
Remotion renders (src/studio/cinematic.py, motion.py: the worker, the MCP server's previews,
a dev's scratch studio) and the voice service (vendor/voxcpm_tts, in its own venv: it loads
this file by path, so stdlib only) for as long as its model is loaded. A real OS lock, not a
pid file: the OS releases it when the holder dies, even killed. Its path needs no config:
GPU_LOCK_PATH, else ~/.ig-campaign/gpu.lock. A waiter logs who holds it every LOG_EVERY_S.
A job also waits for free RAM and VRAM and for no game on the GPU (guard.admit, step 166),
without holding the lock while it does (175: a voice load waiting 47 min for VRAM held it,
and every small render queued behind it).
"""

from __future__ import annotations

import contextlib
import importlib.util
import itertools
import logging
import os
import sys
import time
from pathlib import Path
from typing import Callable, Iterator, Optional, Union

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

try:
    from . import guard
except ImportError:  # loaded by path (the voice service, in its own venv): guard.py by path too
    _spec = importlib.util.spec_from_file_location("guard", Path(__file__).with_name("guard.py"))
    guard = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(guard)

log = logging.getLogger("gpu_lock")
DEFAULT_PATH = Path.home() / ".ig-campaign" / "gpu.lock"
LOG_EVERY_S = 30.0
TICKET_STALE_S = 10.0  # a waiter touches its ticket every poll_s; older = it died
_tickets = itertools.count()


class LockTimeout(TimeoutError):
    """The lock was still held when the timeout ran out."""


def default_path() -> Path:
    return Path(os.environ.get("GPU_LOCK_PATH") or DEFAULT_PATH).expanduser()


def _try_lock(f) -> bool:
    try:
        if sys.platform == "win32":
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _unlock(f) -> None:
    if sys.platform == "win32":
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(f, fcntl.LOCK_UN)


@contextlib.contextmanager
def file_lock(path: Union[str, Path], *, timeout_s: Optional[float] = None,
              poll_s: float = 0.2, on_wait: Optional[Callable[[float], None]] = None
              ) -> Iterator[None]:
    """Hold an exclusive OS lock on `path` across processes (and across handles in one
    process, so threads too). Waits forever when timeout_s is None, else LockTimeout;
    on_wait(seconds waited) runs before each retry."""
    with open(path, "a+b") as f:
        start = time.monotonic()
        while not _try_lock(f):
            waited = time.monotonic() - start
            if timeout_s is not None and waited >= timeout_s:
                raise LockTimeout(f"{Path(path).name} still locked after {timeout_s:g} s")
            if on_wait:
                on_wait(waited)
            time.sleep(poll_s)
        try:
            yield
        finally:
            _unlock(f)


def held_by(path: Union[str, Path, None] = None) -> Optional[str]:
    """Who holds the GPU lock now ("pid N: what", "?" when unsaid), None while it is free (the
    .holder file outlives its holder: only the lock itself says it is held). Checks by taking
    the lock for an instant, so a job trying at that very moment retries next poll."""
    path = Path(path).expanduser() if path else default_path()
    if not path.exists():
        return None
    with open(path, "a+b") as f:
        if _try_lock(f):
            _unlock(f)
            return None
    try:
        return path.with_name(path.name + ".holder").read_text(encoding="utf-8") or "?"
    except OSError:
        return "?"


def _older_ready(queue: Path, mine: str) -> bool:
    """Is a live waiter that started before `mine` admitted too (its ticket fresh)? Stale
    tickets (a waiter that died) are removed."""
    try:
        names = sorted(n for n in os.listdir(queue) if n < mine)
    except OSError:
        return False
    for name in names:
        try:
            age = time.time() - (queue / name).stat().st_mtime
        except OSError:
            continue  # it just went
        if age < TICKET_STALE_S:
            return True
        with contextlib.suppress(OSError):
            (queue / name).unlink()
    return False


@contextlib.contextmanager
def hold(what: str, path: Union[str, Path, None] = None, *, timeout_s: Optional[float] = None,
         poll_s: float = 0.5, log_every_s: float = LOG_EVERY_S, need_vram_gb: float = 0.0,
         min_free_ram_gb: Optional[float] = None) -> Iterator[None]:
    """Hold the machine's GPU lock for `what` (shown to waiters, with this pid), once
    guard.blockers says it may start (need_vram_gb free, min_free_ram_gb free RAM: None =
    GUARD_MIN_FREE_RAM_GB). Waits for admission WITHOUT the lock (guard.admit, whatever
    timeout_s), then for the lock (LockTimeout past timeout_s of lock waiting), then checks
    again under it: still blocked, it lets the lock go and waits again (175). Of two waiters
    admitted at once, the one that started waiting first goes first (a ticket file each)."""
    path = Path(path).expanduser() if path else default_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    holder = path.with_name(path.name + ".holder")
    queue = path.with_name(path.name + ".queue")
    floor = guard.ram_floor(min_free_ram_gb)
    mine = f"{time.time_ns():020d}-{os.getpid()}-{next(_tickets)}"
    ticket = queue / mine
    next_log: Optional[float] = None
    start, lock_waited = time.monotonic(), 0.0

    def waiting(waited: float, ahead: bool) -> None:
        nonlocal next_log
        if next_log is None or waited >= next_log:
            next_log = waited + log_every_s
            try:
                by = holder.read_text(encoding="utf-8") or "?"
            except OSError:
                by = "?"
            by = "a job that waited longer" if ahead else by
            log.warning("%s: waiting for the GPU (held by %s) for %.0f s", what, by,
                        time.monotonic() - start)

    with open(path, "a+b") as f:
        while True:
            guard.admit(what, need_vram_gb, floor)  # the lock is free meanwhile
            queue.mkdir(exist_ok=True)
            ticket.touch()
            try:
                t0 = time.monotonic()
                while True:
                    ahead = _older_ready(queue, mine)
                    if not ahead and _try_lock(f):
                        break
                    waited = lock_waited + time.monotonic() - t0
                    if timeout_s is not None and waited >= timeout_s:
                        raise LockTimeout(f"{path.name} still locked after {timeout_s:g} s")
                    waiting(waited, ahead)
                    time.sleep(poll_s)
                    ticket.touch()  # still waiting: others see it fresh
                lock_waited += time.monotonic() - t0
            finally:
                with contextlib.suppress(OSError):
                    ticket.unlink()
            if not guard.blockers(need_vram_gb, floor):  # checked again, under the lock
                break
            _unlock(f)  # e.g. VRAM taken since: wait again without holding it
        try:
            holder.write_text(f"pid {os.getpid()}: {what}", encoding="utf-8")
            if next_log is not None:
                log.warning("%s: got the GPU after waiting %.0f s", what,
                            time.monotonic() - start)
            yield
        finally:
            _unlock(f)
