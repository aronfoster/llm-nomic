"""
Unit tests for the player_label utility module.

Covers:
- assemble_player_label: correct format strings for human and LLM players
- format_player_label: lookup from GameConfig, fallback behaviour
"""

import pytest

from src.nomic_engine.data_models import (
    GameConfig,
    JudgeType,
    PlayerConfig,
    PlayerPersonality,
)
from src.nomic_engine.utils.player_label import (
    assemble_player_label,
    format_player_label,
)

# --- Tests for assemble_player_label ---


def test_assemble_llm_label_capitalises_personality() -> None:
    label = assemble_player_label(
        "Alice",
        is_human=False,
        personality="machiavellian",
        model_id="claude-sonnet-4-5",
    )
    assert label == "Alice (Machiavellian / claude-sonnet-4-5)"


def test_assemble_llm_label_friendly() -> None:
    label = assemble_player_label(
        "Bob",
        is_human=False,
        personality="friendly",
        model_id="gpt-4o",
    )
    assert label == "Bob (Friendly / gpt-4o)"


def test_assemble_human_label() -> None:
    label = assemble_player_label(
        "Carol",
        is_human=True,
        personality="",
        model_id="",
    )
    assert label == "Carol (Human)"


def test_assemble_human_label_ignores_personality_and_model() -> None:
    """Personality and model_id are ignored for human players."""
    label = assemble_player_label(
        "Dave",
        is_human=True,
        personality="machiavellian",
        model_id="some-model",
    )
    assert label == "Dave (Human)"


# --- Helpers ---


@pytest.fixture
def game_config_mixed() -> GameConfig:
    """GameConfig with one LLM and one human player."""
    return GameConfig(
        players=[
            PlayerConfig(
                name="Alice",
                model_id="claude-sonnet-4-5",
                personality=PlayerPersonality.MACHIAVELLIAN,
            ),
            PlayerConfig(
                name="Bob",
                model_id="human",
                personality=PlayerPersonality.FRIENDLY,
            ),
        ],
        judge_type=JudgeType.HUMAN,
    )


# --- Tests for format_player_label ---


def test_format_player_label_llm(game_config_mixed: GameConfig) -> None:
    label = format_player_label("Alice", game_config_mixed)
    assert label == "Alice (Machiavellian / claude-sonnet-4-5)"


def test_format_player_label_human(game_config_mixed: GameConfig) -> None:
    label = format_player_label("Bob", game_config_mixed)
    assert label == "Bob (Human)"


def test_format_player_label_none_config() -> None:
    """When game_config is None, returns bare player name."""
    assert format_player_label("Alice", None) == "Alice"


def test_format_player_label_player_not_in_config(
    game_config_mixed: GameConfig,
) -> None:
    """When player name is not found, returns bare player name."""
    assert format_player_label("Unknown", game_config_mixed) == "Unknown"
