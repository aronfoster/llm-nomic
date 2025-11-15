"""
Main entrypoint for the Nomic game engine.

This module provides the command-line interface to load and run a game,
executing one turn at a time.
"""

import argparse
import logging
import sys

import pydantic

from .game_loop import GameLoop
from .game_manager import GameManager
from .players.base_player import BasePlayer
from .players.human_player import HumanPlayer
from .players.llm_player import LLMPlayer


def setup_logging() -> None:
    """
    Configure basic logging for the application.

    Sets up logging to display INFO level messages with a simple format.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


def instantiate_players(game_manager: GameManager) -> list[BasePlayer]:
    """
    Instantiate player objects based on game configuration.

    Args:
        game_manager: The loaded GameManager instance containing game
                      configuration.

    Returns:
        List of instantiated BasePlayer objects (HumanPlayer or LLMPlayer).

    Raises:
        ValueError: If game_manager.game_config is None.
    """
    if game_manager.game_config is None:
        raise ValueError("GameManager must have game_config loaded")

    players: list[BasePlayer] = []

    for player_config in game_manager.game_config.players:
        if player_config.model_id == "human":
            players.append(HumanPlayer(player_config.name))
        elif player_config.model_id == "llm":
            players.append(LLMPlayer(player_config.name))
        else:
            # For any other model_id, treat as LLM player
            players.append(LLMPlayer(player_config.name))

    return players


def main() -> None:
    """
    Main entrypoint for the Nomic game engine.

    Parses command-line arguments, loads the game, instantiates players,
    and runs a single turn before exiting.

    Exit codes:
        0: Success or user interrupt
        1: Error occurred (file not found, validation error, game error)
    """
    # Setup logging
    setup_logging()
    logger = logging.getLogger(__name__)

    # Parse command-line arguments
    parser = argparse.ArgumentParser(
        description="Run one turn of a Nomic game."
    )
    parser.add_argument(
        "--game_dir",
        type=str,
        required=True,
        help="Path to the game instance directory",
    )
    args = parser.parse_args()

    # Load game
    try:
        logger.info(f"Loading game from {args.game_dir}")
        manager = GameManager(args.game_dir)
        manager.load_game()
        logger.info("Game loaded successfully")
    except FileNotFoundError as e:
        logger.error(f"Game file not found: {e.filename}")
        sys.exit(1)
    except pydantic.ValidationError as e:
        logger.error(f"Validation error while loading game: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error while loading game: {e}")
        sys.exit(1)

    # Instantiate players
    try:
        players = instantiate_players(manager)
    except ValueError as e:
        logger.error(f"Error instantiating players: {e}")
        sys.exit(1)

    # Validate that we have at least one player
    if len(players) < 1:
        logger.error("No players configured.")
        sys.exit(1)

    logger.info(f"Instantiated {len(players)} player(s)")

    # Initialize game loop
    try:
        game_loop = GameLoop(manager, players)
    except ValueError as e:
        logger.error(f"Error initializing game loop: {e}")
        sys.exit(1)

    # Run single turn
    try:
        logger.info("Starting turn execution")
        game_loop.run_turn()
        print("\n Turn complete. State saved.")
        logger.info("Turn completed successfully")
    except KeyboardInterrupt:
        print("\n\nGame interrupted.")
        logger.info("Game interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Error during game execution: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
