"""
GameLogger: Responsible for logging game events and maintaining
a game transcript.
"""

import logging
from pathlib import Path
from typing import Any

from .constants import GAME_TRANSCRIPT_FILE


class GameLogger:
    """Manages logging game events and maintaining a game transcript."""

    def __init__(self, game_dir: Path) -> None:
        """
        Initialize the GameLogger with paths to log files.

        Args:
            game_dir: Path to the game instance directory
        """
        self.transcript_path = game_dir / GAME_TRANSCRIPT_FILE

    def log_event(self, event_type: str, data: dict[str, Any]) -> None:
        """
        Log an event via the standard logging module.

        The event will be written to the JSON log file by the configured
        file handler.

        Args:
            event_type: The type of event (e.g., "move_start", "proposal_made")
            data: Additional data about the event
        """
        # Log as INFO so it appears in console AND file
        # Pass data as 'extra' so it merges into the JSON log entry
        logging.info(f"EVENT: {event_type}", extra=data)

    def log_transcript(self, text: str) -> None:
        """
        Append raw markdown text to the game transcript.

        Args:
            text: The text to append to the transcript

        Raises:
            IOError: If the transcript file cannot be written
        """
        with self.transcript_path.open("a", encoding="utf-8") as f:
            f.write(text + "\n\n")
