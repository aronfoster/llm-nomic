"""
GameLogger: Responsible for logging game events and maintaining
a game transcript.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .constants import GAME_LOG_FILE, GAME_TRANSCRIPT_FILE


class GameLogger:
    """Manages logging game events and maintaining a game transcript."""

    def __init__(self, game_dir: Path) -> None:
        """
        Initialize the GameLogger with paths to log files.

        Args:
            game_dir: Path to the game instance directory
        """
        self.log_path = game_dir / GAME_LOG_FILE
        self.transcript_path = game_dir / GAME_TRANSCRIPT_FILE

    def log_event(self, event_type: str, data: dict[str, Any]) -> None:
        """
        Log an event as a JSON line in the game log file.

        Args:
            event_type: The type of event (e.g., "move_start", "proposal_made")
            data: Additional data about the event

        Raises:
            IOError: If the log file cannot be written
        """
        timestamp = datetime.now().isoformat()
        payload = {
            "timestamp": timestamp,
            "event_type": event_type,
            "data": data,
        }

        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")

    def log_transcript(self, text: str) -> None:
        """
        Append formatted markdown text to the game transcript.

        Args:
            text: The text to append to the transcript

        Raises:
            IOError: If the transcript file cannot be written
        """
        timestamp = datetime.now().isoformat()
        formatted_text = f"#### {timestamp}\n\n{text}\n\n"

        with self.transcript_path.open("a", encoding="utf-8") as f:
            f.write(formatted_text)
