#!/usr/bin/env python3
"""
Interactive Game Creator Script

This script creates a new Nomic game instance by:
1. Loading the model library and initial ruleset
2. Prompting the user for game name and player configuration
3. Generating all required game files in a new directory under games/
"""

import logging
import re
import sys
from pathlib import Path

import yaml

from src.nomic_engine.constants import (
    CONFIG_FILE,
    GAME_LOG_FILE,
    GAME_STATE_FILE,
    GAME_TRANSCRIPT_FILE,
    GAMES_DIR,
    INITIAL_RULES_FILE,
    RULES_JSONL_FILE,
    RULES_MD_FILE,
)
from src.nomic_engine.core.rules_manager import RulesManager
from src.nomic_engine.data_models import (
    GameConfig,
    GameState,
    JudgeType,
    ModelDefinition,
    ModelLibrary,
    PlayerConfig,
    PlayerPersonality,
)
from src.nomic_engine.utils.flag_schema import (
    get_flag_defaults,
    load_flag_schema,
)
from src.nomic_engine.utils.loaders import load_model_library
from src.nomic_engine.utils.parsers import parse_rules_md

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


def load_initial_rules() -> list:
    """
    Load the initial ruleset from Nomic_Initial_Ruleset_v1.md.

    Returns:
        List of Rule objects

    Raises:
        SystemExit: If the file is not found or parsing fails
    """
    initial_rules_file = Path(INITIAL_RULES_FILE)
    try:
        logger.info(f"Loading initial rules from {initial_rules_file}")
        rules = parse_rules_md(initial_rules_file)
        logger.info(f"Successfully loaded {len(rules)} rules")
        return rules
    except FileNotFoundError:
        logger.error(f"Initial rules file not found: {initial_rules_file}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Failed to parse initial rules: {e}")
        sys.exit(1)


def sanitize_game_name(name: str) -> str:
    """
    Sanitize a game name to be a valid directory name.

    Args:
        name: The raw game name from user input

    Returns:
        A sanitized version safe for use as a directory name
    """
    # Replace spaces and special characters with underscores
    sanitized = re.sub(r"[^\w\-]", "_", name)
    # Remove leading/trailing underscores and convert to lowercase
    sanitized = sanitized.strip("_").lower()
    return sanitized


def get_game_name() -> tuple[str, Path]:
    """
    Prompt the user for a game name and validate it.

    Returns:
        Tuple of (original_name, game_directory_path)

    Raises:
        SystemExit: If the game directory already exists
    """
    while True:
        game_name = input("Enter new game name: ").strip()
        if not game_name:
            print("Game name cannot be empty. Please try again.")
            continue

        sanitized_name = sanitize_game_name(game_name)
        if not sanitized_name:
            print("Invalid game name. Please use alphanumeric characters.")
            continue

        game_dir = Path(GAMES_DIR) / sanitized_name

        if game_dir.exists():
            logger.error(f"Game directory already exists: {game_dir}")
            print(f"A game with that name already exists at {game_dir}")
            print("Please choose a different name.")
            continue

        return game_name, game_dir


def get_player_count() -> int:
    """
    Prompt the user for the number of players.

    Returns:
        The number of players (must be > 0)
    """
    while True:
        try:
            count = input("How many players? ").strip()
            count = int(count)
            if count <= 0:
                print("Number of players must be greater than 0.")
                continue
            return count
        except ValueError:
            print("Please enter a valid number.")


def get_target_score(default: int = 100) -> int | None:
    """Prompt the user for a target score or allow skipping."""

    while True:
        raw_value = input(f"Target score? [Default: {default}] ").strip()

        if raw_value == "":
            return default

        if raw_value.lower() in {"none", "no", "skip"}:
            return None

        try:
            value = int(raw_value)
            if value <= 0:
                print("Target score must be greater than 0 or 'none' to disable.")
                continue
            return value
        except ValueError:
            print("Please enter a whole number, or 'none' to disable.")


def choose_llm_model(model_library: ModelLibrary) -> str:
    """
    Display available LLM models and let the user choose one.

    Args:
        model_library: The ModelLibrary containing available models

    Returns:
        The chosen model's ID
    """
    print("\nAvailable LLM models:")
    for idx, model in enumerate(model_library.models, start=1):
        print(f"  {idx}. {model.id} ({model.provider})")

    while True:
        try:
            choice = input("Choose a model by number: ").strip()
            choice_idx = int(choice) - 1
            if 0 <= choice_idx < len(model_library.models):
                return model_library.models[choice_idx].id
            else:
                print(
                    "Please enter a number between 1 and "
                    f"{len(model_library.models)}"
                )
        except ValueError:
            print("Please enter a valid number.")


def choose_personality() -> PlayerPersonality:
    """
    Display available personalities and let the user choose one.

    Returns:
        The chosen PlayerPersonality enum value.
    """
    personalities = list(PlayerPersonality)
    print("\nAvailable personalities:")
    for idx, personality in enumerate(personalities, start=1):
        print(f"  {idx}. {personality.value}")

    while True:
        try:
            choice = input("Choose a personality by number: ").strip()
            choice_idx = int(choice) - 1
            if 0 <= choice_idx < len(personalities):
                return personalities[choice_idx]
            else:
                print(
                    "Please enter a number between 1 and "
                    f"{len(personalities)}"
                )
        except ValueError:
            print("Please enter a valid number.")


def configure_players(model_library: ModelLibrary) -> list[PlayerConfig]:
    """
    Interactively configure all players for the game.

    Args:
        model_library: The ModelLibrary for LLM model selection

    Returns:
        List of PlayerConfig objects
    """
    player_count = get_player_count()
    players = []

    for i in range(player_count):
        print(f"\n--- Configuring Player {i + 1} ---")

        # Get player name
        while True:
            name = input("Player name: ").strip()
            if not name:
                print("Player name cannot be empty.")
                continue
            # Check for duplicate names
            if any(p.name == name for p in players):
                print(
                    "A player named '"
                    f"{name}"
                    "' already exists. Please choose a different name."
                )
                continue
            break

        # Get player type
        while True:
            player_type = input("Player type (human/llm): ").strip().lower()
            if player_type in ["human", "llm"]:
                break
            print("Please enter either 'human' or 'llm'.")

        # Get model ID and personality
        if player_type == "llm":
            model_id = choose_llm_model(model_library)
            personality = choose_personality()
        else:
            model_id = "human"
            personality = PlayerPersonality.FRIENDLY  # Default for human

        players.append(
            PlayerConfig(
                name=name,
                model_id=model_id,
                personality=personality,
            )
        )
        if player_type == "llm":
            print(
                f"Added {name} as {player_type} player using "
                f"{model_id} with {personality.value} personality"
            )
        else:
            print(f"Added {name} as {player_type} player")

    return players


def choose_judge_type() -> JudgeType:
    """Prompt the user to choose between a human or LLM judge."""

    judge_types = list(JudgeType)
    print("\nSelect judge type:")
    for idx, judge_type in enumerate(judge_types, start=1):
        print(f"  {idx}. {judge_type.value}")

    while True:
        try:
            choice = input("Choose judge type by number: ").strip()
            choice_idx = int(choice) - 1
            if 0 <= choice_idx < len(judge_types):
                return judge_types[choice_idx]
            print(f"Please enter a number between 1 and {len(judge_types)}")
        except ValueError:
            print("Please enter a valid number.")


def get_model_definition(
    model_library: ModelLibrary, model_id: str
) -> ModelDefinition:
    """Return the model definition matching the provided model id."""

    for model in model_library.models:
        if model.id == model_id:
            return model

    available = ", ".join(model.id for model in model_library.models)
    raise ValueError(
        f"Model ID '{model_id}' not found in model library. "
        f"Available models: {available}"
    )


def configure_judge(
    model_library: ModelLibrary,
) -> tuple[JudgeType, ModelDefinition | None]:
    """Prompt the user to configure the judge for the game."""

    judge_type = choose_judge_type()

    if judge_type == JudgeType.LLM:
        model_id = choose_llm_model(model_library)
        judge_model = get_model_definition(model_library, model_id)
        print(f"Selected LLM judge using model: {model_id}")
        return judge_type, judge_model

    print("Selected human judge")
    return judge_type, None


def create_game_files(
    game_dir: Path,
    players: list[PlayerConfig],
    initial_rules: list,
    judge_type: JudgeType,
    judge_model: ModelDefinition | None,
    target_score: int | None,
) -> None:
    """
    Generate all required game files in the game directory.

    Args:
        game_dir: Path to the game directory
        players: List of PlayerConfig objects
        initial_rules: List of Rule objects
        judge_type: Whether the judge is human or LLM
        judge_model: Model definition for the judge (if LLM)
    """
    # Create the game directory
    logger.info(f"Creating game directory: {game_dir}")
    game_dir.mkdir(parents=True, exist_ok=True)

    # 1. Create config.yml
    config_path = game_dir / CONFIG_FILE
    logger.info(f"Creating {config_path}")
    game_config = GameConfig(
        players=players,
        judge_type=judge_type,
        judge_model=judge_model,
        target_score=target_score,
    )
    with config_path.open("w", encoding="utf-8") as f:
        # Convert to dict and then to YAML (mode='json' serializes enums)
        config_dict = game_config.model_dump(mode="json")
        yaml.safe_dump(
            config_dict,
            f,
            default_flow_style=False,
            sort_keys=False,
        )

    # 2. Create game_state.json
    state_path = game_dir / GAME_STATE_FILE
    logger.info(f"Creating {state_path}")
    # Load flag schema and populate defaults
    load_flag_schema()
    flag_defaults = get_flag_defaults()
    logger.info(f"Loaded flag defaults from schema: {flag_defaults}")
    game_state = GameState(
        scores={player.name: 0 for player in players},
        target_score=game_config.target_score,
        turn_order=[player.name for player in players],
        current_player_name=players[0].name,
        move_number=1,
        next_proposal_id=301,
        flags=flag_defaults,
    )
    with state_path.open("w", encoding="utf-8") as f:
        f.write(game_state.model_dump_json(indent=2))

    # 3. Create rules.jsonl and rules.md
    rules_manager = RulesManager(rules=initial_rules)

    rules_jsonl_path = game_dir / RULES_JSONL_FILE
    logger.info(f"Creating {rules_jsonl_path}")
    rules_manager.save_to_jsonl(rules_jsonl_path)

    rules_md_path = game_dir / RULES_MD_FILE
    logger.info(f"Creating {rules_md_path}")
    rules_manager.render_to_markdown(rules_md_path)

    # 4. Create empty log files
    game_log_path = game_dir / GAME_LOG_FILE
    logger.info(f"Creating {game_log_path}")
    game_log_path.touch()

    game_transcript_path = game_dir / GAME_TRANSCRIPT_FILE
    logger.info(f"Creating {game_transcript_path}")
    game_transcript_path.touch()


def main() -> None:
    """Main entry point for the game creator script."""
    print("=" * 60)
    print("Nomic Game Creator")
    print("=" * 60)
    print()

    # Load dependencies
    model_library = load_model_library()
    initial_rules = load_initial_rules()

    # Get game configuration from user
    game_name, game_dir = get_game_name()
    judge_type, judge_model = configure_judge(model_library)
    players = configure_players(model_library)
    target_score = get_target_score()

    # Create all game files
    print("\nCreating game files...")
    create_game_files(
        game_dir,
        players,
        initial_rules,
        judge_type,
        judge_model,
        target_score,
    )

    # Success message
    print()
    print("=" * 60)
    print(f"Successfully created new game at: {game_dir}")
    print("=" * 60)
    print()
    print("Game files created:")
    print(f"  - {game_dir / CONFIG_FILE}")
    print(f"  - {game_dir / GAME_STATE_FILE}")
    print(f"  - {game_dir / RULES_JSONL_FILE}")
    print(f"  - {game_dir / RULES_MD_FILE}")
    print(f"  - {game_dir / GAME_LOG_FILE}")
    print(f"  - {game_dir / GAME_TRANSCRIPT_FILE}")
    print()
    print("To start your game, run:")
    print(f"    python -m src.nomic_engine.main --game_dir {game_dir}")


if __name__ == "__main__":
    main()
