"""
Graceful soft-interrupt mechanism for the interactive turn loop.

While a turn is running the operator can press any key (followed by Enter
in the default cooked-mode terminal) to signal "finish this turn, then
stop".  The current turn — including all in-flight LLM API calls — runs to
full completion before the loop exits.

Ctrl+C continues to hard-terminate immediately, as before.
"""

import os
import select
import sys
import threading


class SoftInterrupt:
    """
    Background mechanism that monitors stdin for a graceful stop keypress.

    Usage::

        interrupt = SoftInterrupt()
        interrupt.start()          # begin monitoring
        try:
            while not interrupt.is_requested:
                run_turn()
        finally:
            interrupt.stop()       # stop monitoring before next stdin use

    The monitor is a daemon thread so it never prevents process exit.
    If stdin is not a TTY (e.g. redirected in CI), ``start()`` is a no-op.
    """

    def __init__(self) -> None:
        self._stop_requested: threading.Event = threading.Event()
        self._running: threading.Event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def is_requested(self) -> bool:
        """True if the operator has pressed the stop key."""
        return self._stop_requested.is_set()

    def start(self) -> None:
        """
        Start monitoring stdin for the stop keypress.

        No-op when stdin is not a TTY (e.g. pipes, CI environments).
        """
        if not sys.stdin.isatty():
            return
        self._running.set()
        self._thread = threading.Thread(
            target=self._monitor,
            daemon=True,
            name="soft-interrupt-monitor",
        )
        self._thread.start()

    def stop(self) -> None:
        """
        Stop monitoring.

        Returns promptly; the background thread exits within the next
        ``select`` poll cycle (≤ 0.2 s).
        """
        self._running.clear()

    def _monitor(self) -> None:
        """Background thread: poll stdin and set the stop flag on keypress."""
        fd = sys.stdin.fileno()
        while self._running.is_set() and not self._stop_requested.is_set():
            try:
                readable, _, _ = select.select([sys.stdin], [], [], 0.2)
            except (ValueError, OSError):
                break
            if not readable or not self._running.is_set():
                continue
            try:
                data = os.read(fd, 256)
            except OSError:
                break
            if data and not self._stop_requested.is_set():
                self._stop_requested.set()
                print("\nStopping after this turn…", flush=True)
