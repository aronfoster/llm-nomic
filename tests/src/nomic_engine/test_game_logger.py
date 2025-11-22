"""
Tests for the GameLogger class.

These tests validate logging functionality including:
- Event logging via standard logging module
- Transcript logging to markdown format
"""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

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
    """Test that log_event delegates to the standard logging module."""
    with TemporaryDirectory() as tmpdir:
        game_dir = Path(tmpdir)
        logger = GameLogger(game_dir)

        # Patch the logging module used by game_logger
        with patch("src.nomic_engine.game_logger.logging") as mock_logging:
            # Log an event
            logger.log_event("test_event", {"key": "value"})

            # Verify logging.info was called with correct parameters
            mock_logging.info.assert_called_once_with(
                "EVENT: test_event", extra={"key": "value"}
            )
