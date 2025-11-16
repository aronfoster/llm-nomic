"""
Tests for the GameLogger class.

These tests validate logging functionality including:
- Event logging to JSON format
- Transcript logging to markdown format
"""

from pathlib import Path
from tempfile import TemporaryDirectory

from src.nomic_engine.game_logger import GameLogger


def test_game_logger_log_transcript() -> None:
    """Test that log_transcript appends raw text without timestamp."""
    with TemporaryDirectory() as tmpdir:
        game_dir = Path(tmpdir)
        logger = GameLogger(game_dir)

        # Ensure the transcript file doesn't exist yet
        assert not logger.transcript_path.exists()

        # Log some text
        test_text = "## MOVE #1\n**Proposer:** Alice\n**Type:** Add"
        logger.log_transcript(test_text)

        # Verify the file was created
        assert logger.transcript_path.exists()

        # Read the file contents
        content = logger.transcript_path.read_text(encoding="utf-8")

        # Verify that ONLY the raw text (and newlines) was written
        # There should be no timestamp headers (#### {timestamp})
        assert content == test_text + "\n\n"
        assert "####" not in content
        assert "MOVE #1" in content
        assert "Alice" in content


def test_game_logger_log_transcript_multiple_entries() -> None:
    """Test that multiple transcript entries are appended correctly."""
    with TemporaryDirectory() as tmpdir:
        game_dir = Path(tmpdir)
        logger = GameLogger(game_dir)

        # Log multiple entries
        entry1 = "## MOVE #1\n**Proposer:** Alice"
        entry2 = "## MOVE #2\n**Proposer:** Bob"

        logger.log_transcript(entry1)
        logger.log_transcript(entry2)

        # Read the file contents
        content = logger.transcript_path.read_text(encoding="utf-8")

        # Verify both entries are present
        assert entry1 in content
        assert entry2 in content

        # Verify no timestamp headers
        assert "####" not in content


def test_game_logger_log_event() -> None:
    """Test that log_event writes JSON-formatted events."""
    with TemporaryDirectory() as tmpdir:
        game_dir = Path(tmpdir)
        logger = GameLogger(game_dir)

        # Ensure the log file doesn't exist yet
        assert not logger.log_path.exists()

        # Log an event
        logger.log_event("test_event", {"key": "value"})

        # Verify the file was created
        assert logger.log_path.exists()

        # Read and verify the content
        content = logger.log_path.read_text(encoding="utf-8")

        # Should be a JSON line with timestamp, event_type, and data
        assert "test_event" in content
        assert '"key": "value"' in content
        assert "timestamp" in content
