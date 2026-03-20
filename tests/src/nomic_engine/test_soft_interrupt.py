"""Unit tests for SoftInterruptListener."""

import threading
from unittest.mock import MagicMock, patch

from src.nomic_engine.soft_interrupt import (
    _STOP_KEY,
    SoftInterruptListener,
)


def test_stop_requested_initially_false() -> None:
    """stop_requested is False before any key is pressed."""
    listener = SoftInterruptListener()
    assert listener.stop_requested is False


def test_stop_before_start_does_not_raise() -> None:
    """Calling stop() before start() must not raise."""
    listener = SoftInterruptListener()
    listener.stop()  # should be a no-op


def test_start_and_stop_lifecycle() -> None:
    """start() spawns the daemon thread; stop() joins it cleanly."""

    def noop_select(
        rlist: list[object],
        wlist: list[object],
        xlist: list[object],
        timeout: float,
    ) -> tuple[list[object], list[object], list[object]]:
        return ([], [], [])  # never readable → thread spins on _active

    mock_stdin = MagicMock()
    mock_stdin.isatty.return_value = False

    listener = SoftInterruptListener()
    with (
        patch("src.nomic_engine.soft_interrupt.sys.stdin", mock_stdin),
        patch("src.nomic_engine.soft_interrupt.select.select", noop_select),
    ):
        listener.start()
        assert listener._thread is not None
        assert listener._thread.is_alive()
        listener.stop()
    # After stop() the thread should no longer be alive (joined with
    # up to 0.5 s timeout, which is far more than the 0.1 s poll).
    assert not listener._thread.is_alive()


def test_stop_requested_reflects_internal_event() -> None:
    """stop_requested delegates directly to the internal Event."""
    listener = SoftInterruptListener()
    assert listener.stop_requested is False
    listener._stop_event.set()
    assert listener.stop_requested is True


def test_start_resets_stop_event() -> None:
    """start() clears a stop flag left over from a previous session."""
    listener = SoftInterruptListener()
    listener._stop_event.set()
    assert listener.stop_requested is True
    listener.start()
    assert listener.stop_requested is False
    listener.stop()


def test_multiple_start_stop_cycles() -> None:
    """The listener can be started and stopped more than once."""
    listener = SoftInterruptListener()
    for _ in range(3):
        listener.start()
        assert listener.stop_requested is False
        listener.stop()


def test_listen_sets_flag_on_stop_key(capsys: object) -> None:
    """Background thread sets stop_requested when the stop key arrives."""
    barrier = threading.Event()

    # Simulate select() returning readable once, then never again so
    # the thread spins down gracefully after stop().
    call_count = [0]

    def fake_select(
        rlist: list[object],
        wlist: list[object],
        xlist: list[object],
        timeout: float,
    ) -> tuple[list[object], list[object], list[object]]:
        call_count[0] += 1
        if call_count[0] == 1:
            barrier.set()  # signal that we are about to return data
            return (rlist, [], [])
        return ([], [], [])

    mock_stdin = MagicMock()
    mock_stdin.isatty.return_value = False
    mock_stdin.read.side_effect = [_STOP_KEY, ""]

    listener = SoftInterruptListener()

    with (
        patch("src.nomic_engine.soft_interrupt.sys.stdin", mock_stdin),
        patch("src.nomic_engine.soft_interrupt.select.select", fake_select),
    ):
        listener.start()
        barrier.wait(timeout=1.0)
        listener.stop()

    assert listener.stop_requested is True


def test_listen_ignores_non_stop_key() -> None:
    """Characters other than the stop key do not set the flag."""
    call_count = [0]

    def fake_select(
        rlist: list[object],
        wlist: list[object],
        xlist: list[object],
        timeout: float,
    ) -> tuple[list[object], list[object], list[object]]:
        call_count[0] += 1
        if call_count[0] == 1:
            return (rlist, [], [])
        return ([], [], [])

    mock_stdin = MagicMock()
    mock_stdin.isatty.return_value = False
    mock_stdin.read.side_effect = ["x", ""]

    listener = SoftInterruptListener()

    with (
        patch("src.nomic_engine.soft_interrupt.sys.stdin", mock_stdin),
        patch("src.nomic_engine.soft_interrupt.select.select", fake_select),
    ):
        listener.start()
        listener.stop()

    assert listener.stop_requested is False


def test_listen_handles_eof_gracefully() -> None:
    """An EOF on stdin (empty read) causes the thread to exit cleanly."""

    def fake_select(
        rlist: list[object],
        wlist: list[object],
        xlist: list[object],
        timeout: float,
    ) -> tuple[list[object], list[object], list[object]]:
        return (rlist, [], [])

    mock_stdin = MagicMock()
    mock_stdin.isatty.return_value = False
    mock_stdin.read.return_value = ""  # EOF

    listener = SoftInterruptListener()

    with (
        patch("src.nomic_engine.soft_interrupt.sys.stdin", mock_stdin),
        patch("src.nomic_engine.soft_interrupt.select.select", fake_select),
    ):
        listener.start()
        listener.stop()

    assert listener.stop_requested is False
