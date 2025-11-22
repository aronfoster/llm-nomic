"""
Main entrypoint for the Nomic game engine.

This module provides the command-line interface to load and run a game,
executing one turn at a time.
"""

import argparse
import logging
import sys
from pathlib import Path

import pydantic
from pythonjsonlogger.json import JsonFormatter

from .constants import GAME_LOG_FILE
from .core.game_loop import GameLoop
from .core.game_manager import GameManager
from .data_models import ModelLibrary
from .players.base_player import BasePlayer
from .players.human_player import HumanPlayer
from .players.llm_player import LLMPlayer
from .utils.loaders import load_model_library


def setup_logging(game_dir: str) -> None:
    """
    Configure logging for the application.

    Sets up:
    - Console handler: INFO level with text formatter
    - File handler: DEBUG level with JSON formatter to game_log.jsonl

    Args:
        game_dir: Path to the game instance directory
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # Console handler - INFO level with text formatter
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
    )
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # File handler - DEBUG level with JSON formatter
    log_file_path = Path(game_dir) / GAME_LOG_FILE
    file_handler = logging.FileHandler(log_file_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    json_formatter = JsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    file_handler.setFormatter(json_formatter)
    root_logger.addHandler(file_handler)


def instantiate_players(
    game_manager: GameManager, model_library: ModelLibrary
) -> list[BasePlayer]:
    """
    Instantiate player objects based on game configuration.

    Args:
        game_manager: The loaded GameManager instance containing game
                      configuration.
        model_library: The ModelLibrary containing available model definitions.

    Returns:
        List of instantiated BasePlayer objects (HumanPlayer or LLMPlayer).

    Raises:
        ValueError: If game_manager.game_config is None or if a model_id
                    is not found in the model library.
    """
    if game_manager.game_config is None:
        raise ValueError("GameManager must have game_config loaded")

    players: list[BasePlayer] = []

    for player_config in game_manager.game_config.players:
        if player_config.model_id == "human":
            players.append(HumanPlayer(player_config.name))
        else:
            # For any other model_id, look up the ModelDefinition
            model_def = None
            for model in model_library.models:
                if model.id == player_config.model_id:
                    model_def = model
                    break

            if model_def is None:
                available = ", ".join(m.id for m in model_library.models)
                raise ValueError(
                    f"Model ID '{player_config.model_id}' not found in "
                    f"model library. Available models: {available}"
                )

            players.append(LLMPlayer(player_config.name, model_def))

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

    # Setup logging (after args so we have game_dir)
    setup_logging(args.game_dir)
    logger = logging.getLogger(__name__)

    # Load model library
    try:
        model_library = load_model_library()
    except SystemExit:
        # load_model_library already logged the error and called sys.exit
        raise

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
        players = instantiate_players(manager, model_library)
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
