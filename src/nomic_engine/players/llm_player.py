"""
LLM player implementation for the Nomic game.

This module provides a stub for an LLM-powered player that will
eventually use language models to participate in the game.
"""

from ..data_models import GameState, Proposal, Rule, Vote
from .base_player import BasePlayer


class LLMPlayer(BasePlayer):
    """
    A player implementation using a Large Language Model.

    This is a stub implementation - all methods raise NotImplementedError
    until the LLM integration is completed.
    """

    def propose(self, game_state: GameState, rules: list[Rule]) -> Proposal:
        """
        Generate a proposal using an LLM.

        Args:
            game_state: The current state of the game.
            rules: The current list of all rules.

        Returns:
            A complete Proposal object representing the player's
            proposed change.

        Raises:
            NotImplementedError: LLM integration not yet implemented.
        """
        raise NotImplementedError("LLMPlayer is not yet implemented.")

    def discuss(
        self, proposal: Proposal, game_state: GameState, rules: list[Rule]
    ) -> str | None:
        """
        Provide discussion/commentary on a proposal using an LLM.

        Args:
            proposal: The proposal being discussed.
            game_state: The current state of the game.
            rules: The current list of all rules.

        Returns:
            A string containing the player's discussion, or None to abstain
            from discussion.

        Raises:
            NotImplementedError: LLM integration not yet implemented.
        """
        raise NotImplementedError("LLMPlayer is not yet implemented.")

    def vote(
        self, proposal: Proposal, game_state: GameState, rules: list[Rule]
    ) -> Vote:
        """
        Cast a vote on a proposal using an LLM.

        Args:
            proposal: The proposal being voted on.
            game_state: The current state of the game.
            rules: The current list of all rules.

        Returns:
            A complete Vote object representing the player's vote.

        Raises:
            NotImplementedError: LLM integration not yet implemented.
        """
        raise NotImplementedError("LLMPlayer is not yet implemented.")
