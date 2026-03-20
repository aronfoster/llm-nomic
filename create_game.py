#!/usr/bin/env python3
"""
Interactive Game Creator Script

This script creates a new Nomic game instance by:
1. Loading the model library and initial ruleset
2. Prompting the user for game name and player configuration
3. Generating all required game files in a new directory under games/

All game-creation logic lives in ``src/nomic_engine/game_creator`` so it
can be imported by other parts of the package.  This script is a thin
wrapper that calls the module's ``run_creation_flow`` helper and then
prints the final success summary.
"""

import logging

from src.nomic_engine.constants import (
    CONFIG_FILE,
    GAME_LOG_FILE,
    GAME_STATE_FILE,
    GAME_TRANSCRIPT_FILE,
    RULES_JSONL_FILE,
    RULES_MD_FILE,
    TOKEN_USAGE_FILE,
)
from src.nomic_engine.game_creator import run_creation_flow

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s",
)


def main() -> None:
    """Main entry point for the game creator script."""
    print("=" * 60)
    print("Nomic Game Creator")
    print("=" * 60)
    print()

    game_dir = run_creation_flow()

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
    print(f"  - {game_dir / TOKEN_USAGE_FILE}")
    print()
    print("To start your game, run:")
    print(f"    python -m src.nomic_engine.main --game_dir {game_dir}")


if __name__ == "__main__":
    main()
