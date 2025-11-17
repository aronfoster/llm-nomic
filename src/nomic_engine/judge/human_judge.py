"""
Human judge interaction logic.

This module contains functions for interacting with the human judge,
including veto decisions and score assignment.
"""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..core.game_manager import GameManager
    from ..players.base_player import BasePlayer

logger = logging.getLogger(__name__)


def get_veto() -> bool:
    """
    Prompt the human judge (Arbiter) for a veto decision.

    Returns:
        True if the judge vetoes, False otherwise
    """
    judge_response = (
        input("\nJudge (Arbiter), do you VETO this outcome? (y/n): ")
        .strip()
        .lower()
    )
    judge_vetoed = judge_response == "y"
    return judge_vetoed


def get_scores_from_judge(
    game_manager: "GameManager", players: list["BasePlayer"]
) -> None:
    """
    Prompt the Judge to manually assign point changes for each player.

    This function displays all point-related rules and prompts the Judge
    to enter score changes for each player based on the current turn.
    Input is validated to ensure it's an integer.

    Args:
        game_manager: The GameManager instance for accessing game state
            and rules
        players: List of all player objects

    Raises:
        AssertionError: If game_state or rules_manager is None
    """
    assert game_manager.game_state is not None
    assert game_manager.rules_manager is not None

    # Find all point-related rules
    point_rules = [
        r
        for r in game_manager.rules_manager.rules
        if "point" in r.text.lower()
    ]

    # Print header
    print(
        f"\n--- Judge (Scorer), please assess points for Move "
        f"#{game_manager.game_state.move_number} ---"
    )

    # Print point-scoring rules
    print("\nRelevant Point-Scoring Rules:")
    for rule in point_rules:
        status_char = rule.status.value[0].upper()
        print(f"Rule {rule.rule_id} ({status_char}): {rule.text}")

    print()  # Blank line for readability

    # Loop through each player and get score changes
    for player in players:
        while True:
            try:
                points_input = input(
                    f"Enter point change for {player.player_name}: "
                )
                points_change = int(points_input)
                break  # Valid integer received
            except ValueError:
                print("Invalid input. Please enter an integer.")
                continue

        # Apply the score change
        game_manager.game_state.scores[player.player_name] += points_change
        logger.debug(f"Applied {points_change} points to {player.player_name}")
