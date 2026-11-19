"""
Main entrypoint for the Nomic game engine.

This module provides the command-line interface to load and run a game,
executing one or more turns at a time, as well as an interactive console
menu for managing multiple games within a single process.
"""

import argparse
import logging
import sys
from pathlib import Path

import pydantic
from pythonjsonlogger.json import JsonFormatter

from .config import load_env_vars
from .constants import GAME_LOG_FILE
from .core.game_loop import GameLoop
from .core.game_manager import GameManager
from .data_models import JudgeType, ModelLibrary
from .game_creator import run_creation_flow
from .game_discovery import GameInfo, discover_games
from .judge import BaseJudge
from .judge.human_judge import HumanJudge
from .judge.llm_judge import LLMJudge
from .players.base_player import BasePlayer
from .players.human_player import HumanPlayer
from .players.llm_player import LLMPlayer
from .soft_interrupt import SoftInterrupt
from .startup_validation import validate_startup
from .utils.loaders import load_model_library


def setup_logging(game_dir: str) -> None:
    """
    Configure logging for the application.

    Sets up:
    - Console handler: WARNING level with text formatter
    - File handler: DEBUG level with JSON formatter to game_log.jsonl

    Args:
        game_dir: Path to the game instance directory
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # Console handler - WARNING level so only warnings/errors appear on console
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING)
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

            players.append(
                LLMPlayer(
                    player_config.name,
                    model_def,
                    player_config.personality,
                    game_manager.game_config.tuning,
                    memory_manager=game_manager.memory_manager,
                    token_usage_logger=game_manager.token_usage_logger,
                )
            )

    return players


def instantiate_judge(game_manager: GameManager) -> BaseJudge:
    """Instantiate a Judge based on the game configuration."""

    if game_manager.game_config is None:
        raise ValueError("GameManager must have game_config loaded")

    judge_type = game_manager.game_config.judge_type
    judge_model = game_manager.game_config.judge_model

    if judge_type == JudgeType.LLM:
        if judge_model is None:
            raise ValueError(
                "Game config is missing judge_model for LLM judge type"
            )
        return LLMJudge(
            judge_model,
            tuning=game_manager.game_config.tuning,
            memory_manager=game_manager.memory_manager,
            token_usage_logger=game_manager.token_usage_logger,
        )

    return HumanJudge()


def run_game(
    game_dir: str,
    max_turns: int | None,
) -> None:
    """
    Load and run a game from *game_dir*.

    Args:
        game_dir: Path to the game instance directory.
        max_turns: Maximum number of turns to run, or None for unlimited.

    Side-effects:
        Prints output to stdout. Calls sys.exit(1) on unrecoverable errors.
    """
    logger = logging.getLogger(__name__)

    # Load model library
    try:
        model_library = load_model_library()
    except SystemExit:
        raise

    # Load game
    try:
        logger.info(f"Loading game from {game_dir}")
        manager = GameManager(game_dir)
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

    # Instantiate judge
    try:
        judge = instantiate_judge(manager)
    except ValueError as e:
        logger.error(f"Error instantiating judge: {e}")
        sys.exit(1)

    # Validate that we have at least one player
    if len(players) < 1:
        logger.error("No players configured.")
        sys.exit(1)

    logger.info(f"Instantiated {len(players)} player(s)")

    # Initialize game loop
    try:
        game_loop = GameLoop(manager, players, judge)
    except ValueError as e:
        logger.error(f"Error initializing game loop: {e}")
        sys.exit(1)

    # Check if game has already been completed
    try:
        victory_exists, winners, winning_score = (
            game_loop.check_existing_victory()
        )

        if victory_exists:
            logger.info("Game already completed, displaying victory summary")
            assert manager.game_state is not None
            victory_summary = game_loop._format_victory_summary(
                winners=winners,
                winning_score=winning_score,
                scores=manager.game_state.scores,
                target_score=manager.game_state.target_score or 0,
                total_turns=manager.game_state.move_number,
            )
            print(victory_summary)
            logger.info("Exiting: game already completed")
            return
    except Exception as e:
        logger.error(f"Error checking victory status: {e}", exc_info=True)
        sys.exit(1)

    # Validate startup configuration (API keys + personality files)
    validate_startup(players, judge, manager)

    # Run turns
    turns_run = 0
    game_over = False
    soft_interrupt = SoftInterrupt()
    soft_interrupt.start()
    try:
        logger.info("Starting turn execution")
        while True:
            game_over = game_loop.run_turn()
            turns_run += 1
            if game_over:
                logger.info("Game ended due to target score.")
                break
            if soft_interrupt.is_requested:
                logger.info("Game paused by soft interrupt.")
                break
            if max_turns is not None and turns_run >= max_turns:
                break
    except KeyboardInterrupt:
        print("\n\nGame interrupted.")
        logger.info("Game interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Error during game execution: {e}", exc_info=True)
        sys.exit(1)
    finally:
        soft_interrupt.stop()

    if not game_over:
        if turns_run == 1:
            print("\n Turn complete. State saved.")
        else:
            print(f"\n {turns_run} turns complete. State saved.")
        logger.info("Turn(s) completed successfully")


def _print_game_list(games: list[GameInfo]) -> None:
    """Print a numbered list of discovered games to stdout."""
    for idx, game in enumerate(games, start=1):
        status = "Complete" if game.is_complete else "In progress"
        print(
            f"  {idx}. {game.display_name}"
            f"  [Turn {game.turn_number}"
            f" | {game.current_player}"
            f" | {status}]"
        )


def _menu_continue_game() -> str | None:
    """
    Handle the 'Continue a game' menu option.

    Returns:
        The selected game's directory path as a string, or None if the
        operator declined to select a game (e.g. no games available).
    """
    games = discover_games()
    if not games:
        print("\nNo existing games found.")
        return None

    print("\nAvailable games:")
    _print_game_list(games)

    while True:
        raw = input("\nSelect a game by number (or 0 to go back): ").strip()
        try:
            choice = int(raw)
        except ValueError:
            print("Please enter a number.")
            continue
        if choice == 0:
            return None
        if 1 <= choice <= len(games):
            return str(games[choice - 1].path)
        print(f"Please enter a number between 1 and {len(games)}, or 0.")


def _menu_new_game() -> str | None:
    """
    Handle the 'New game' menu option.

    Runs the interactive game-creation flow and returns the new game's
    directory path. Returns None if creation fails unexpectedly.
    """
    try:
        game_dir = run_creation_flow()
        print(f"\nGame created at: {game_dir}")
        return str(game_dir)
    except KeyboardInterrupt:
        print("\nGame creation cancelled.")
        return None


def run_interactive_menu(max_turns: int | None) -> None:
    """
    Display the top-level interactive console menu in a loop.

    The operator is shown three options:
    1. Continue a game
    2. New game
    3. Quit

    After a game session ends (victory or operator stops), the menu is
    shown again. The process does not exit between games.

    Args:
        max_turns: Forwarded to run_game(); None means unlimited turns.
    """
    while True:
        print("\n" + "=" * 40)
        print("  NOMIC — Main Menu")
        print("=" * 40)
        print("  1. Continue a game")
        print("  2. New game")
        print("  3. Quit")
        print("=" * 40)

        raw = input("Select an option: ").strip()

        if raw == "1":
            selected_dir = _menu_continue_game()
            if selected_dir is None:
                continue
            setup_logging(selected_dir)
            run_game(selected_dir, max_turns)

        elif raw == "2":
            new_dir = _menu_new_game()
            if new_dir is None:
                continue
            play_now = input("\nStart playing now? [y/N]: ").strip().lower()
            if play_now in ("y", "yes"):
                setup_logging(new_dir)
                run_game(new_dir, max_turns)

        elif raw == "3":
            print("Goodbye!")
            sys.exit(0)

        else:
            print("Invalid option. Please enter 1, 2, or 3.")


def main() -> None:
    """
    Main entrypoint for the Nomic game engine.

    When invoked without --game_dir, displays an interactive console menu.
    When invoked with --game_dir, loads and runs the specified game directly
    (bypassing the menu).

    Exit codes:
        0: Success or user interrupt
        1: Error occurred (file not found, validation error, game error)
    """
    # Credentials are read when a game starts, not when this module
    # is imported.
    load_env_vars()

    # Parse command-line arguments
    parser = argparse.ArgumentParser(
        description="Run one or more turns of a Nomic game."
    )
    parser.add_argument(
        "--game_dir",
        type=str,
        default=None,
        help="Path to the game instance directory",
    )
    turn_mode = parser.add_mutually_exclusive_group()
    turn_mode.add_argument(
        "--turns",
        type=int,
        metavar="N",
        help=(
            "Run up to N turns in a single invocation "
            "(must be a positive integer)"
        ),
    )
    turn_mode.add_argument(
        "--until-victory",
        action="store_true",
        default=False,
        help="Run turns continuously until the victory condition is reached",
    )
    args = parser.parse_args()

    if args.turns is not None and args.turns < 1:
        parser.error("--turns must be a positive integer")

    # Determine max_turns for the turn loop
    if args.until_victory:
        max_turns: int | None = None  # unlimited
    elif args.turns is not None:
        max_turns = args.turns
    else:
        max_turns = None  # default: continuous loop until victory

    if args.game_dir is not None:
        # --game_dir provided: bypass menu, run directly
        setup_logging(args.game_dir)
        run_game(args.game_dir, max_turns)
    else:
        # No --game_dir: show interactive menu
        run_interactive_menu(max_turns)


if __name__ == "__main__":
    main()
