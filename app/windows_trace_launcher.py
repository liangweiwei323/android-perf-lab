"""Run record_android_trace with graceful CTRL_BREAK handling on Windows."""

from __future__ import annotations

import runpy
import signal
import sys


def _handle_break(_signum, _frame):
    # record_android_trace already catches KeyboardInterrupt around its device
    # wait loop and then stops/pulls the trace. It only registers SIGINT/SIGTERM,
    # while a Windows process group is safely targetable with CTRL_BREAK/SIGBREAK.
    raise KeyboardInterrupt


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: windows_trace_launcher.py <record_android_trace> [args...]")
    helper = sys.argv[1]
    sys.argv = [helper, *sys.argv[2:]]
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, _handle_break)
    runpy.run_path(helper, run_name="__main__")


if __name__ == "__main__":
    main()

