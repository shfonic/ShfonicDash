"""
Logging setup — console + size-capped rotating file.

The Pi launches via startx with no visible console, so print() output is lost;
diagnostics from real sessions (the hardest bugs to reproduce) need to land in
a file. RotatingFileHandler caps total disk usage at ~3 MB (1 MB × 3 files,
oldest deleted automatically) so the log can never fill the SD card.
"""

import logging
import os
import sys
import threading
from logging.handlers import RotatingFileHandler

_MAX_BYTES = 1_000_000
_BACKUPS   = 2
_FILE_NAME = "dashboard.log"


def _log_uncaught(exc_type, exc, tb):
    logging.getLogger("crash").critical("Uncaught exception — app terminating",
                                        exc_info=(exc_type, exc, tb))
    sys.__excepthook__(exc_type, exc, tb)


def _log_thread_uncaught(args):
    logging.getLogger("crash").critical(
        f"Uncaught exception in thread {args.thread.name if args.thread else '?'}",
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback))


def setup(logs_dir: str, debug: bool = False) -> None:
    """Configure the root logger once. Safe to call again (no-op)."""
    root = logging.getLogger()
    if root.handlers:
        return
    root.setLevel(logging.DEBUG if debug else logging.INFO)

    # Crashes on the Pi were undiagnosable: uncaught tracebacks go to stderr,
    # which startx discards. Route them through logging so they reach the file.
    sys.excepthook = _log_uncaught
    threading.excepthook = _log_thread_uncaught

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname).1s %(name)s: %(message)s", datefmt="%H:%M:%S"))
    root.addHandler(console)

    os.makedirs(logs_dir, exist_ok=True)
    file_h = RotatingFileHandler(os.path.join(logs_dir, _FILE_NAME),
                                 maxBytes=_MAX_BYTES, backupCount=_BACKUPS)
    file_h.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname).1s %(name)s: %(message)s"))
    root.addHandler(file_h)
