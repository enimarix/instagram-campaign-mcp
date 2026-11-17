"""
Keep the machine awake while long work runs (renders now, due slots in 025a).

Windows: SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED) on enter stops idle
sleep until the same thread calls it again with ES_CONTINUOUS alone (on exit). Enter and
exit must run on one thread: the worker's event loop thread. Elsewhere it does nothing.
"""

from __future__ import annotations

import ctypes
import sys
from contextlib import contextmanager
from typing import Iterator

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


@contextmanager
def keep_awake() -> Iterator[None]:
    if sys.platform != "win32":
        yield
        return
    kernel32 = ctypes.windll.kernel32
    kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
    try:
        yield
    finally:
        kernel32.SetThreadExecutionState(ES_CONTINUOUS)
