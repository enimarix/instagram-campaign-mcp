"""Run one heavy command under the studio's GPU lock (step 173; was D:/lemo-films/gpu-run.py).

    python -m src.studio.gpu_run -- <command> [args...]
    python <repo>/src/studio/gpu_run.py -- <command> [args...]   (from any folder: a film's)

Waits for the lock and for free RAM / VRAM like the studio's own renders (gpu_lock.hold,
guard.admit), runs the command at below-normal priority (guard.run) and exits with its code.
Every heavy command of a Lemo film (render, still sheet, encode, mux, Whisper) goes through
it. Never the voice service call: that service takes the lock itself.

Inside a film, WAIT_FILE_ENV names a file it touches every BEAT_S while it waits for the
lock or the machine: the film runner stops the film's clock while that file is fresh
(film.waiting_for_machine), so a wait for RAM never eats the film's time.
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

if not __package__:  # run by path from a film's folder: the repo root replaces this folder
    # on the path before any other import (src/studio/token.py, calendar.py ... would shadow
    # the stdlib's)
    sys.path[0] = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from typing import List, Optional  # noqa: E402

if __package__:
    from . import gpu_lock, guard
else:
    from src.studio import gpu_lock, guard

NEED_VRAM_GB = 1.5  # a film's headless Chrome + encode (~33 W, measured on the 3 test films)
USAGE = "usage: gpu_run -- <command> [args...]"
WAIT_FILE_ENV = "LEMO_FILM_WAIT_FILE"
BEAT_S = 5.0


def _beat(path: Path, stop: threading.Event) -> None:
    """Touch `path` now and every BEAT_S until `stop` (dies with the process if killed)."""
    while True:
        try:
            path.touch()
        except OSError:
            pass
        if stop.wait(BEAT_S):
            return


def main(argv: Optional[List[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    cmd = argv[argv.index("--") + 1:] if "--" in argv else argv
    if not cmd:
        print(USAGE, file=sys.stderr)
        return 2
    stop = threading.Event()
    if os.environ.get(WAIT_FILE_ENV):
        threading.Thread(target=_beat, args=(Path(os.environ[WAIT_FILE_ENV]), stop),
                         daemon=True).start()
    try:
        with gpu_lock.hold("lemo film: " + " ".join(cmd)[:80], need_vram_gb=NEED_VRAM_GB):
            stop.set()  # admitted: the film's clock runs again
            return guard.run(cmd).returncode
    finally:
        stop.set()


if __name__ == "__main__":
    sys.exit(main())
