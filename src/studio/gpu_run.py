"""Run one heavy command under the studio's GPU lock (step 173; was D:/lemo-films/gpu-run.py).

    python -m src.studio.gpu_run -- <command> [args...]
    python <repo>/src/studio/gpu_run.py -- <command> [args...]   (from any folder: a film's)

Waits for the lock and for free RAM / VRAM like the studio's own renders (gpu_lock.hold,
guard.admit), runs the command at below-normal priority (guard.run) and exits with its code.
Every heavy command of a Lemo film (render, still sheet, encode, mux, Whisper) goes through
it. Never the voice service call: that service takes the lock itself.
"""

from __future__ import annotations

import os
import sys

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


def main(argv: Optional[List[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    cmd = argv[argv.index("--") + 1:] if "--" in argv else argv
    if not cmd:
        print(USAGE, file=sys.stderr)
        return 2
    with gpu_lock.hold("lemo film: " + " ".join(cmd)[:80], need_vram_gb=NEED_VRAM_GB):
        return guard.run(cmd).returncode


if __name__ == "__main__":
    sys.exit(main())
