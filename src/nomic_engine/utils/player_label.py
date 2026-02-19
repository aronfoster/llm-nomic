"""
Utility for formatting player labels with model and personality information.

Provides a single shared helper so the label format lives in one place
and is never duplicated across console output and transcript logging.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..data_models import GameConfig


def assemble_player_label(
    name: str,
    is_human: bool,
    personality: str,
    model_id: str,
) -> str:
    """
    Build a player label string from explicit components.

    This is the single source of truth for the label format:
    - LLM:   ``Alice (Machiavellian / claude-sonnet-4-5)``
    - Human: ``Alice (Human)``

    Args:
        name: The player's unique name.
        is_human: True when the player is a human (not an LLM).
        personality: The personality value string (ignored when is_human).
        model_id: The model ID string (ignored when is_human).

    Returns:
        Formatted label string.
    """
    if is_human:
        return f"{name} (Human)"
    return f"{name} ({personality.capitalize()} / {model_id})"


def format_player_label(
    player_name: str, game_config: "GameConfig | None"
) -> str:
    """
    Return a formatted player label by looking up the player in game_config.

    Label format:
    - LLM players:   ``Alice (Machiavellian / claude-sonnet-4-5)``
    - Human players: ``Alice (Human)``
    - Fallback (player not in config or config is None): ``Alice``

    Args:
        player_name: The player's unique name.
        game_config: The loaded GameConfig, or None if unavailable.

    Returns:
        Formatted label string.
    """
    if game_config is None:
        return player_name

    try:
        for player_cfg in game_config.players:
            if player_cfg.name == player_name:
                is_human = player_cfg.model_id == "human"
                return assemble_player_label(
                    player_name,
                    is_human,
                    player_cfg.personality if not is_human else "",
                    player_cfg.model_id if not is_human else "",
                )
    except (TypeError, AttributeError):
        # game_config.players is not iterable (e.g. in unit tests that use
        # a Mock instead of a real GameConfig).  Fall through to plain name.
        pass

    # Player not found in config – return name as-is
    return player_name
