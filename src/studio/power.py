"""
Keep the machine awake while long work runs: renders, and due slots (025a).

Windows: SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED) stops idle sleep until
the same thread calls it again with ES_CONTINUOUS alone. Holds are counted, so the render
loop and the slot hold don't release each other's: the first hold sets the flag, the last
release clears it. All holds of a process must be taken and released on one thread (the
worker's event loop thread). Elsewhere it does nothing.
"""

from __future__ import annotations

import ctypes
import sys
import threading
from contextlib import contextmanager
from typing import Iterator

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001

_lock = threading.Lock()
_holds = 0


def _set(flags: int) -> None:
    if sys.platform == "win32":
        ctypes.windll.kernel32.SetThreadExecutionState(flags)


def hold() -> None:
    global _holds
    with _lock:
        _holds += 1
        if _holds == 1:
            _set(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)


def release() -> None:
    global _holds
    with _lock:
        if _holds == 0:  # unbalanced release: nothing to undo
            return
        _holds -= 1
        if _holds == 0:
            _set(ES_CONTINUOUS)


@contextmanager
def keep_awake() -> Iterator[None]:
    hold()
    try:
        yield
    finally:
        release()
