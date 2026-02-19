"""Smoke test for player abstractions."""

from src.nomic_engine.data_models import ModelDefinition
from src.nomic_engine.players.base_player import BasePlayer
from src.nomic_engine.players.human_player import HumanPlayer
from src.nomic_engine.players.llm_player import LLMPlayer


def test_player_imports():
    """Test that player classes can be imported."""
    assert BasePlayer is not None
    assert HumanPlayer is not None


def test_human_player_label():
    """HumanPlayer.player_label should include the (Human) suffix."""
    player = HumanPlayer("Alice")
    assert player.player_label == "Alice (Human)"


def test_llm_player_label():
    """LLMPlayer.player_label should include personality and model id."""
    # Use the "local" provider so no API key env var is required.
    model_def = ModelDefinition(
        id="claude-sonnet-4-5",
        provider="local",
        api_model_id="http://localhost:11434",
        env_key_name=None,
    )
    player = LLMPlayer(
        "Bob",
        model_def,
        personality="machiavellian",
    )
    assert player.player_label == "Bob (Machiavellian / claude-sonnet-4-5)"


def test_llm_player_label_friendly():
    """LLMPlayer.player_label capitalises the personality value."""
    # Use the "local" provider so no API key env var is required.
    model_def = ModelDefinition(
        id="gpt-4o",
        provider="local",
        api_model_id="http://localhost:11434",
        env_key_name=None,
    )
    player = LLMPlayer(
        "Carol",
        model_def,
        personality="friendly",
    )
    assert player.player_label == "Carol (Friendly / gpt-4o)"
