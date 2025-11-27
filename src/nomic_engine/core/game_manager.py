"""
GameManager: The central manager for loading, saving, and managing
game instances.
"""

import json
import logging
from pathlib import Path

import pydantic
import yaml

from ..constants import (
    CONFIG_FILE,
    GAME_STATE_FILE,
    RULES_JSONL_FILE,
    RULES_MD_FILE,
)
from ..data_models import GameConfig, GameState
from ..game_logger import GameLogger
from .rules_manager import RulesManager

logger = logging.getLogger(__name__)


class GameManager:
    """
    Manages a single game instance - loading, saving, and
    coordinating components.
    """

    def __init__(self, game_dir_path: str | Path) -> None:
        """
        Initialize the GameManager for a specific game instance.

        Args:
            game_dir_path: Path to the game instance directory
        """
        self.game_dir = Path(game_dir_path)

        # Define all file paths
        self.config_path = self.game_dir / CONFIG_FILE
        self.game_state_path = self.game_dir / GAME_STATE_FILE
        self.rules_jsonl_path = self.game_dir / RULES_JSONL_FILE
        self.rules_md_path = self.game_dir / RULES_MD_FILE

        # Initialize logger
        self.logger = GameLogger(self.game_dir)

        # Initialize component attributes
        self.game_config: GameConfig | None = None
        self.game_state: GameState | None = None
        self.rules_manager: RulesManager | None = None

    def load_game(self) -> None:
        """
        Load all game data from files into memory.

        Loads:
        - Game configuration from config.yml
        - Game state from game_state.json
        - Rules from rules.jsonl

        Raises:
            FileNotFoundError: If any required file is not found
            pydantic.ValidationError: If any file has invalid data
            json.JSONDecodeError: If JSON files are malformed
            yaml.YAMLError: If YAML files are malformed
        """
        try:
            # Load config.yml
            logger.debug(f"Loading game config from {self.config_path}")
            with self.config_path.open("r", encoding="utf-8") as f:
                config_data = yaml.safe_load(f)
            self.game_config = GameConfig(**config_data)
            logger.info(
                f"Loaded game config with "
                f"{len(self.game_config.players)} players"
            )

            # Load game_state.json
            logger.debug(f"Loading game state from {self.game_state_path}")
            with self.game_state_path.open("r", encoding="utf-8") as f:
                state_data = json.load(f)
            self.game_state = GameState(**state_data)
            logger.info(
                f"Loaded game state at move #{self.game_state.move_number}"
            )

            # Load rules.jsonl
            logger.debug(f"Loading rules from {self.rules_jsonl_path}")
            self.rules_manager = RulesManager.load_from_jsonl(
                self.rules_jsonl_path
            )
            logger.info(f"Loaded {len(self.rules_manager.rules)} rules")

        except FileNotFoundError as e:
            logger.error(f"Game file not found: {e.filename}")
            raise
        except pydantic.ValidationError as e:
            logger.error(f"Validation error while loading game data: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error while loading game: {e}")
            raise

    def save_game_state(self) -> None:
        """
        Save the current game state to game_state.json.

        Raises:
            ValueError: If game_state is None
            IOError: If the file cannot be written
        """
        if self.game_state is None:
            raise ValueError("Cannot save game state: game_state is None")

        logger.debug(f"Saving game state to {self.game_state_path}")
        with self.game_state_path.open("w", encoding="utf-8") as f:
            f.write(self.game_state.model_dump_json(indent=2))
        logger.info(f"Saved game state at move #{self.game_state.move_number}")

    def save_rules(self) -> None:
        """
        Save the current rules to both rules.jsonl and rules.md.

        Raises:
            ValueError: If rules_manager is None
            IOError: If the files cannot be written
        """
        if self.rules_manager is None:
            raise ValueError("Cannot save rules: rules_manager is None")

        logger.debug(
            f"Saving {len(self.rules_manager.rules)} rules to "
            f"{self.rules_jsonl_path}"
        )
        self.rules_manager.save_to_jsonl(self.rules_jsonl_path)

        logger.debug(f"Rendering rules to markdown at {self.rules_md_path}")
        self.rules_manager.render_to_markdown(self.rules_md_path)

        logger.info(f"Saved {len(self.rules_manager.rules)} rules")
