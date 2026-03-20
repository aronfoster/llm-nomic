"""Graceful soft-interrupt listener for the Nomic turn loop.

Monitors stdin for a designated keypress while turns are executing.
When the key is pressed the ``stop_requested`` flag is set and an
acknowledgement is printed, so the turn loop can exit cleanly after
the current turn finishes.

The listener is only active during the turn loop (started immediately
before the loop and stopped afterwards), so keypresses outside of turn
execution have no visible effect on the turn loop.
"""

import select
import sys
import termios
import threading
import tty
from typing import Any

_STOP_KEY = "p"


class SoftInterruptListener:
    """Background keyboard listener for the turn-loop soft interrupt.

    A daemon thread polls stdin for the designated stop key (``p``).
    When the key is pressed while a turn is running, ``stop_requested``
    is set to ``True`` and a one-line acknowledgement is printed.  The
    current turn continues to completion; the turn loop then checks the
    flag and exits cleanly.

    The listener is inactive outside of the turn loop (it is not
    started until ``start()`` is called and is stopped by ``stop()``),
    so keypresses at the interactive menu have no effect on the game.

    Example usage::

        listener = SoftInterruptListener()
        listener.start()
        try:
            while True:
                game_over = game_loop.run_turn()
                if game_over or listener.stop_requested:
                    break
        finally:
            listener.stop()

    Ctrl+C is NOT handled here; it propagates as ``KeyboardInterrupt``
    to the main thread and terminates the process immediately.
    """

    def __init__(self) -> None:
        self._stop_event: threading.Event = threading.Event()
        self._active: threading.Event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def stop_requested(self) -> bool:
        """``True`` once the stop key has been pressed."""
        return self._stop_event.is_set()

    def start(self) -> None:
        """Start the background keypress listener.

        Resets any previously-set stop flag so the listener is fresh
        for a new game session.
        """
        self._stop_event.clear()
        self._active.set()
        self._thread = threading.Thread(
            target=self._listen,
            daemon=True,
            name="soft-interrupt-listener",
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the background keypress listener.

        Signals the background thread to exit and waits briefly for it
        to finish (which also allows it to restore terminal settings).
        """
        self._active.clear()
        if self._thread is not None:
            self._thread.join(timeout=0.5)

    def _listen(self) -> None:
        """Background thread: poll stdin for the stop keypress.

        When stdin is connected to a real terminal the terminal is
        switched to ``cbreak`` mode so characters arrive immediately
        (no line-buffering).  ``cbreak`` preserves ``Ctrl+C`` (SIGINT).
        The original terminal settings are always restored on exit.

        When stdin is not a tty (e.g. piped input in tests) raw-mode
        changes are skipped; characters still arrive via ``select``,
        but require a newline in that scenario.
        """
        old_settings: list[Any] | None = None
        fd: int | None = None

        if sys.stdin.isatty():
            try:
                fd = sys.stdin.fileno()
                old_settings = termios.tcgetattr(fd)
                tty.setcbreak(fd)
            except Exception:
                fd = None
                old_settings = None

        try:
            while self._active.is_set():
                try:
                    readable, _, _ = select.select([sys.stdin], [], [], 0.1)
                    if readable:
                        ch = sys.stdin.read(1)
                        if not ch:
                            break  # EOF
                        if ch == _STOP_KEY and not self._stop_event.is_set():
                            self._stop_event.set()
                            print(
                                "\nStopping after this turn\u2026",
                                flush=True,
                            )
                except (EOFError, OSError):
                    break
        finally:
            if old_settings is not None and fd is not None:
                try:
                    termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
                except Exception:
                    pass
