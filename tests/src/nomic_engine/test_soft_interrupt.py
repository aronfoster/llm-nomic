"""Unit tests for the SoftInterrupt graceful-stop mechanism."""

import sys
import threading
from unittest.mock import MagicMock, patch

from src.nomic_engine.soft_interrupt import (  # noqa: E402 — src path
    SoftInterrupt,
)

# ---------------------------------------------------------------------------
# Basic state tests
# ---------------------------------------------------------------------------


def test_is_requested_false_initially() -> None:
    """is_requested is False before any keypress."""
    si = SoftInterrupt()
    assert si.is_requested is False


def test_is_requested_true_after_event_set() -> None:
    """is_requested is True after the internal event is set directly."""
    si = SoftInterrupt()
    si._stop_requested.set()
    assert si.is_requested is True


# ---------------------------------------------------------------------------
# start() / stop() no-op when stdin is not a tty
# ---------------------------------------------------------------------------


def test_start_noop_when_stdin_not_tty() -> None:
    """start() does not launch a thread when stdin is not a TTY."""
    si = SoftInterrupt()
    with patch.object(sys.stdin, "isatty", return_value=False):
        si.start()
    assert si._thread is None
    assert not si._running.is_set()


def test_stop_clears_running_flag() -> None:
    """stop() clears the _running event."""
    si = SoftInterrupt()
    si._running.set()
    si.stop()
    assert not si._running.is_set()


# ---------------------------------------------------------------------------
# Background thread: _monitor sets stop flag when stdin is readable
# ---------------------------------------------------------------------------


def test_monitor_sets_stop_flag_on_keypress(capsys) -> None:
    """
    _monitor() sets is_requested and prints acknowledgement when data
    arrives on stdin.
    """
    si = SoftInterrupt()
    si._running.set()

    # Simulate stdin returning readable and then having a byte available
    fake_stdin = MagicMock()
    fake_stdin.fileno.return_value = 99

    with (
        patch("src.nomic_engine.soft_interrupt.sys.stdin", fake_stdin),
        patch(
            "src.nomic_engine.soft_interrupt.select.select",
            return_value=([fake_stdin], [], []),
        ),
        patch(
            "src.nomic_engine.soft_interrupt.os.read",
            return_value=b"p\n",
        ),
    ):
        # Run _monitor directly (it loops, so we let it run once then stop)
        def _run_once() -> None:
            si._monitor()

        t = threading.Thread(target=_run_once, daemon=True)
        t.start()
        # Give the thread a moment to process
        t.join(timeout=1.0)

    assert si.is_requested is True
    out = capsys.readouterr().out
    assert "Stopping after this turn" in out


def test_monitor_exits_cleanly_when_running_cleared() -> None:
    """
    _monitor() exits within a short time after _running is cleared (no
    stdin data arrives).
    """
    si = SoftInterrupt()
    si._running.set()

    fake_stdin = MagicMock()
    fake_stdin.fileno.return_value = 99

    # select always returns nothing readable (timeout fires)
    with (
        patch("src.nomic_engine.soft_interrupt.sys.stdin", fake_stdin),
        patch(
            "src.nomic_engine.soft_interrupt.select.select",
            return_value=([], [], []),
        ),
    ):
        t = threading.Thread(target=si._monitor, daemon=True)
        t.start()
        # Clear the running flag — thread should exit on next poll
        si._running.clear()
        t.join(timeout=1.0)

    assert not t.is_alive()
    assert not si.is_requested


def test_monitor_exits_on_select_oserror() -> None:
    """_monitor() exits cleanly if select raises OSError."""
    si = SoftInterrupt()
    si._running.set()

    fake_stdin = MagicMock()
    fake_stdin.fileno.return_value = 99

    with (
        patch("src.nomic_engine.soft_interrupt.sys.stdin", fake_stdin),
        patch(
            "src.nomic_engine.soft_interrupt.select.select",
            side_effect=OSError("fd closed"),
        ),
    ):
        t = threading.Thread(target=si._monitor, daemon=True)
        t.start()
        t.join(timeout=1.0)

    assert not t.is_alive()


# ---------------------------------------------------------------------------
# Integration: turn loop respects is_requested
# ---------------------------------------------------------------------------


def test_turn_loop_stops_after_current_turn_when_requested() -> None:
    """
    The turn loop breaks after the current turn completes once
    is_requested is True, without waiting for game_over.
    """
    si = SoftInterrupt()
    call_count = 0

    def fake_run_turn() -> bool:
        nonlocal call_count
        call_count += 1
        # On the first call, simulate a keypress arriving mid-turn
        if call_count == 1:
            si._stop_requested.set()
        return False  # game not over

    # Simulate the turn loop logic from run_game()
    game_over = False
    max_turns = None
    turns_run = 0

    while True:
        game_over = fake_run_turn()
        turns_run += 1
        if game_over:
            break
        if si.is_requested:
            break
        if max_turns is not None and turns_run >= max_turns:
            break

    assert turns_run == 1
    assert not game_over
    assert si.is_requested


def test_turn_loop_does_not_stop_if_not_requested() -> None:
    """
    The turn loop does NOT stop early when is_requested stays False
    (game ends normally via game_over).
    """
    si = SoftInterrupt()
    results = [False, False, True]
    idx = 0

    def fake_run_turn() -> bool:
        nonlocal idx
        result = results[idx]
        idx += 1
        return result

    game_over = False
    turns_run = 0
    while True:
        game_over = fake_run_turn()
        turns_run += 1
        if game_over:
            break
        if si.is_requested:
            break

    assert turns_run == 3
    assert game_over


# ---------------------------------------------------------------------------
# start() launches a live thread when stdin is a tty
# ---------------------------------------------------------------------------


def test_start_launches_thread_when_stdin_is_tty() -> None:
    """start() launches a daemon thread when stdin is a TTY."""
    si = SoftInterrupt()

    fake_stdin = MagicMock()
    fake_stdin.isatty.return_value = True
    fake_stdin.fileno.return_value = 99

    # select never returns readable so the thread just loops and exits on stop
    with (
        patch("src.nomic_engine.soft_interrupt.sys.stdin", fake_stdin),
        patch(
            "src.nomic_engine.soft_interrupt.select.select",
            return_value=([], [], []),
        ),
    ):
        si.start()
        assert si._thread is not None
        assert si._thread.is_alive()
        si.stop()
        # Thread should exit within the poll timeout
        si._thread.join(timeout=1.0)
        assert not si._thread.is_alive()
