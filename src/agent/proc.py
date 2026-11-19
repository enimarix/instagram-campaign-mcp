"""Is the process that started an agent run still there? (155)

started(pid) -> None when no such process runs, else an opaque creation time (0 when it
can't be read) to compare with the one stored at the run's start: another value means the
pid was reused by another process. No dependency: ctypes on Windows, /proc elsewhere.
Never os.kill(pid, 0) on Windows: there it terminates the process.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

STILL_ACTIVE = 259
ACCESS_DENIED = 5
QUERY_LIMITED_INFORMATION = 0x1000


def _windows(pid: int) -> Optional[int]:
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    k32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    k32.GetProcessTimes.argtypes = (wintypes.HANDLE, *[ctypes.POINTER(wintypes.FILETIME)] * 4)
    k32.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = k32.OpenProcess(QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:  # gone (invalid parameter), or there but not ours to look at
        return 0 if ctypes.get_last_error() == ACCESS_DENIED else None
    try:
        code = wintypes.DWORD()
        if k32.GetExitCodeProcess(handle, ctypes.byref(code)) and code.value != STILL_ACTIVE:
            return None  # exited; someone still holds a handle on it
        times = [wintypes.FILETIME() for _ in range(4)]  # creation, exit, kernel, user
        if not k32.GetProcessTimes(handle, *map(ctypes.byref, times)):
            return 0
        return times[0].dwHighDateTime << 32 | times[0].dwLowDateTime
    finally:
        k32.CloseHandle(handle)


def _posix(pid: int) -> Optional[int]:
    try:
        os.kill(pid, 0)  # signal 0: only asks whether it exists
    except ProcessLookupError:
        return None
    except PermissionError:
        pass  # another user's process: it exists
    try:  # field 22, starttime (clock ticks after boot); the name in () may hold spaces
        return int(Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19])
    except (OSError, ValueError, IndexError):
        return 0  # no /proc (macOS): alive, start unknown


def started(pid: int) -> Optional[int]:
    """None when process `pid` is gone, else its creation time (0 = unknown)."""
    # ponytail: a pid reused by a process we may not open reads as alive with an unknown
    # start, so that row waits for the 24 h rule; psutil would see more, it's not a dep.
    if pid <= 0:
        return None
    return _windows(pid) if sys.platform == "win32" else _posix(pid)


def is_gone(pid: Optional[int], pid_started: Optional[int]) -> bool:
    """True when the recorded runner is surely dead: no such process, or another process
    has the pid now (creation time differs). Unknown pid: False (can't tell)."""
    if not pid:
        return False
    now = started(pid)
    return now is None or bool(pid_started and now and now != pid_started)
