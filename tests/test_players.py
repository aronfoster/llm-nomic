"""Smoke test for player abstractions."""

from src.nomic_engine.players.base_player import BasePlayer
from src.nomic_engine.players.human_player import HumanPlayer


def test_player_imports():
    """Test that player classes can be imported."""
    assert BasePlayer is not None
    assert HumanPlayer is not None
