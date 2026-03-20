"""
Game discovery utility.

Scans GAMES_DIR for valid existing game instances and returns structured
metadata suitable for display in the console menu.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from .constants import CONFIG_FILE, GAME_STATE_FILE, GAMES_DIR


@dataclass
class GameInfo:
    """Summary metadata for a single discovered game instance."""

    display_name: str
    path: Path
    turn_number: int
    current_player: str
    is_complete: bool


def discover_games(
    games_dir: Optional[Path] = None,
) -> List[GameInfo]:
    """Scan *games_dir* for valid game instances and return their metadata.

    A directory is considered a valid game instance only when it contains
    both ``config.yml`` and ``game_state.json``.  Any directory that is
    missing either file is silently skipped.

    If *games_dir* is ``None`` the default ``GAMES_DIR`` constant is used.
    If the directory does not exist, an empty list is returned without error.

    Args:
        games_dir: Path to the directory that contains game sub-directories.
                   Defaults to ``Path(GAMES_DIR)``.

    Returns:
        List of :class:`GameInfo` objects sorted by display name, one per
        valid game sub-directory.
    """
    root = Path(games_dir) if games_dir is not None else Path(GAMES_DIR)

    if not root.exists():
        return []

    results: List[GameInfo] = []
    for candidate in sorted(root.iterdir()):
        if not candidate.is_dir():
            continue
        if not (candidate / CONFIG_FILE).exists():
            continue
        state_path = candidate / GAME_STATE_FILE
        if not state_path.exists():
            continue

        try:
            state_data = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        turn_number: int = state_data.get("move_number", 0)
        current_player: str = state_data.get("current_player_name", "")
        target_score: Optional[int] = state_data.get("target_score")
        scores: dict[str, int] = state_data.get("scores", {})

        is_complete = target_score is not None and any(
            s >= target_score for s in scores.values()
        )

        results.append(
            GameInfo(
                display_name=candidate.name,
                path=candidate,
                turn_number=turn_number,
                current_player=current_player,
                is_complete=is_complete,
            )
        )

    return results
