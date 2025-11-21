"""
LLM player implementation for the Nomic game.

This module provides a stub for an LLM-powered player that will
eventually use language models to participate in the game.
"""

import logging
from typing import Literal

from ..data_models import (
    ChatMessage,
    GameState,
    ModelDefinition,
    Proposal,
    Rule,
    Vote,
)
from ..llm import ApiClient, PromptBuilder, parse_vote_response, prompts
from .base_player import BasePlayer

logger = logging.getLogger(__name__)


class LLMPlayer(BasePlayer):
    """
    A player implementation using a Large Language Model.

    This is a stub implementation - all methods raise NotImplementedError
    until the LLM integration is completed.
    """

    # Maximum number of retry attempts when LLM produces invalid JSON
    MAX_VOTE_RETRIES = 2

    def __init__(
        self, player_name: str, model_config: ModelDefinition
    ) -> None:
        """
        Initialize an LLM player with a specific model configuration.

        Args:
            player_name: The unique name for this player.
            model_config: The ModelDefinition containing API configuration
                          for this player's LLM.
        """
        super().__init__(player_name)
        self.model_config = model_config
        self.api_client = ApiClient(self.model_config)
        self.prompt_builder = PromptBuilder()

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
        # TODO: MVP Stub; Always abstain from discussion to allow testing of voting
        return None

    def vote(
        self, proposal: Proposal, game_state: GameState, rules: list[Rule]
    ) -> Vote:
        """
        Cast a vote on a proposal using an LLM.

        This method implements a retry loop to handle the non-deterministic
        nature of LLMs. If the LLM produces invalid JSON, the error message
        is fed back to the model for a retry attempt.

        Args:
            proposal: The proposal being voted on.
            game_state: The current state of the game.
            rules: The current list of all rules.

        Returns:
            A complete Vote object representing the player's vote.
            If all retry attempts fail, returns an ABSTAIN vote.
        """
        # Build initial messages for the vote prompt
        messages = self.prompt_builder.build_vote_messages(
            proposal=proposal,
            rules=rules,
            game_state=game_state,
            discussions=[],  # Empty for now
            player_name=self.player_name,
        )

        # Retry loop with maximum attempts
        for attempt in range(self.MAX_VOTE_RETRIES):
            # Get completion from the LLM
            response_text = self.api_client.get_completion(messages)

            # Handle API errors (None response)
            if response_text is None:
                logger.error(
                    f"{self.player_name}: API error on attempt {attempt + 1}/"
                    f"{self.MAX_VOTE_RETRIES}"
                )
                # Continue to retry if attempts remain
                continue

            # Try to parse the response
            try:
                data = parse_vote_response(response_text)

                # Success! Log private thoughts and return vote
                logger.debug(
                    f"{self.player_name} private thoughts: "
                    f"{data['private_thoughts']}"
                )

                # Cast vote to Literal type (parser guarantees it's valid)
                vote_value: Literal["YES", "NO", "ABSTAIN"] = data[
                    "vote"
                ]  # type: ignore[assignment]
                return Vote(
                    player_name=self.player_name,
                    vote=vote_value,
                    reason=data["public_reason"],
                )

            except ValueError as e:
                # Parsing failed - log the error
                logger.warning(
                    f"{self.player_name}: Invalid response on attempt "
                    f"{attempt + 1}/{self.MAX_VOTE_RETRIES}. Error: {e}"
                )

                # If this was the last attempt, break out
                if attempt >= self.MAX_VOTE_RETRIES - 1:
                    break

                # Construct retry by appending bad response and error message
                # Append the LLM's bad response as an assistant message
                messages.append(
                    ChatMessage(role="assistant", content=response_text)
                )

                # Append the retry prompt as a user message
                messages.append(
                    ChatMessage(
                        role="user", content=prompts.VOTE_RETRY_TEMPLATE
                    )
                )

                # Loop continues to retry with updated conversation history

        # All retries exhausted - return ABSTAIN as fallback
        logger.error(
            f"{self.player_name}: Failed to generate valid vote after "
            f"{self.MAX_VOTE_RETRIES} attempts. Defaulting to ABSTAIN."
        )
        return Vote(
            player_name=self.player_name,
            vote="ABSTAIN",
            reason="LLM Error: Failed to generate valid vote.",
        )

    def revise(
        self,
        proposal: Proposal,
        discussions: list[tuple[str, str]],
        game_state: GameState,
        rules: list[Rule],
    ) -> Proposal | None:
        """
        Revise a proposal based on discussion using an LLM.

        Args:
            proposal: The original proposal made by this player.
            discussions: A list of tuples (player_name, discussion_text).
            game_state: The current state of the game.
            rules: The current list of all rules.

        Returns:
            The (potentially) revised Proposal object,
            or None if the player chooses to withdraw the proposal.

        Raises:
            NotImplementedError: LLM integration not yet implemented.
        """
        # TODO: MVP Stub; Never revise
        return proposal
