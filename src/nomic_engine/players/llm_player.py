"""
LLM player implementation for the Nomic game.

This module provides a stub for an LLM-powered player that will
eventually use language models to participate in the game.
"""

import logging
from typing import Literal

from ..data_models import (
    ChatMessage,
    Discussion,
    EngineTuningConfig,
    GameState,
    ModelDefinition,
    PlayerPersonality,
    Proposal,
    ProposalType,
    Rule,
    Vote,
)
from ..llm import (
    ApiClient,
    PromptBuilder,
    parse_discussion_response,
    parse_proposal_response,
    parse_revision_response,
    parse_vote_response,
    prompts,
)
from .base_player import BasePlayer

logger = logging.getLogger(__name__)


class LLMPlayer(BasePlayer):
    """
    A player implementation using a Large Language Model.

    This is a stub implementation - all methods raise NotImplementedError
    until the LLM integration is completed.
    """

    def __init__(
        self,
        player_name: str,
        model_config: ModelDefinition,
        personality: PlayerPersonality = PlayerPersonality.FRIENDLY,
        tuning: EngineTuningConfig | None = None,
    ) -> None:
        """
        Initialize an LLM player with a specific model configuration.

        Args:
            player_name: The unique name for this player.
            model_config: The ModelDefinition containing API configuration
                          for this player's LLM.
            personality: The PlayerPersonality enum value dictating which
                         system prompt persona to use.
        """
        super().__init__(player_name)
        self.model_config = model_config
        self.personality = personality
        self.tuning = tuning or EngineTuningConfig()
        self.api_client = ApiClient(self.model_config)
        self.prompt_builder = PromptBuilder()
        # Stateful conversation history for the current turn
        self.turn_history: list[ChatMessage] = []

    def _reset_history(self, system_message: ChatMessage) -> None:
        """
        Reset the conversation history for a new turn/action.

        Clears the turn_history and starts fresh with the given system message.

        Args:
            system_message: The system message to start the new context.
        """
        self.turn_history = [system_message]

    def propose(self, game_state: GameState, rules: list[Rule]) -> Proposal:
        """
        Generate a proposal using an LLM.

        This method starts a new turn for the Proposer by resetting the
        conversation history. It implements a retry loop to handle the
        non-deterministic nature of LLMs.

        Args:
            game_state: The current state of the game.
            rules: The current list of all rules.

        Returns:
            A complete Proposal object representing the player's
            proposed change.

        Raises:
            RuntimeError: If the LLM fails to generate a valid proposal
                         after all retry attempts are exhausted.
        """
        # Build system message for proposer (starts new turn)
        system_message = self.prompt_builder.build_proposer_system_message(
            rules=rules,
            game_state=game_state,
            player_name=self.player_name,
            personality=self.personality.value,
        )

        # Reset history for new turn
        self._reset_history(system_message)

        # Retry loop with maximum attempts
        max_proposal_retries = self.tuning.max_propose_retries
        for attempt in range(max_proposal_retries):
            # Status indicator for UX
            print(f"\n🤖 {self.player_name} is thinking about a proposal...")

            # Get completion from the LLM using turn history
            response_text = self.api_client.get_completion(self.turn_history)

            # Log raw response for debugging
            logger.info(
                f"Raw LLM Response from {self.player_name}:\n{response_text}"
            )

            # Handle API errors (None response)
            if response_text is None:
                logger.error(
                    f"{self.player_name}: API error on attempt {attempt + 1}/"
                    f"{max_proposal_retries}"
                )
                # Continue to retry if attempts remain
                continue

            # Try to parse the response
            try:
                data = parse_proposal_response(response_text)

                # Success! Append valid response to history
                self.turn_history.append(
                    ChatMessage(role="assistant", content=response_text)
                )

                # Construct and return the Proposal object
                # Note: proposal_id is left as None; GameLoop assigns it
                return Proposal(
                    proposer_name=self.player_name,
                    move_number=game_state.move_number,
                    type=ProposalType(data["type"]),  # Convert str to enum
                    proposal_id=None,
                    target_rule_id=data.get("target_rule_id"),
                    new_text=data.get("new_text"),
                    rationale=data.get("rationale"),
                    private_thoughts=data.get("private_thoughts"),
                )

            except ValueError as e:
                # Parsing failed - log the error
                logger.warning(
                    f"{self.player_name}: Invalid response on attempt "
                    f"{attempt + 1}/{max_proposal_retries}. Error: {e}"
                )

                # If this was the last attempt, break out
                if attempt >= max_proposal_retries - 1:
                    break

                # Construct retry by appending bad response and error message
                # Append the LLM's bad response as an assistant message
                self.turn_history.append(
                    ChatMessage(role="assistant", content=response_text)
                )

                # Append the retry prompt with the specific error as a user msg
                retry_message = prompts.PROPOSE_RETRY_TEMPLATE.format(
                    validation_error=str(e)
                )
                self.turn_history.append(
                    ChatMessage(role="user", content=retry_message)
                )

                # Loop continues to retry with updated conversation history

        # All retries exhausted - raise RuntimeError (better to crash than
        # to generate a "pass" turn for a proposal phase)
        logger.error(
            f"{self.player_name}: Failed to generate valid proposal after "
            f"{max_proposal_retries} attempts."
        )
        raise RuntimeError(
            f"LLM failed to generate a valid proposal after "
            f"{max_proposal_retries} attempts."
        )

    def discuss(
        self, proposal: Proposal, game_state: GameState, rules: list[Rule]
    ) -> Discussion:
        """
        Provide discussion/commentary on a proposal using an LLM.

        This method starts a new turn for discussers by resetting the
        conversation history. It implements a retry loop to handle the
        non-deterministic nature of LLMs.

        Args:
            proposal: The proposal being discussed.
            game_state: The current state of the game.
            rules: The current list of all rules.

        Returns:
            A Discussion object containing the player's discussion.
            If the player abstains, Discussion.text will be empty.
        """
        # Build system message for discusser (starts new turn for this player)
        system_message = self.prompt_builder.build_discusser_system_message(
            proposal=proposal,
            rules=rules,
            game_state=game_state,
            player_name=self.player_name,
            personality=self.personality.value,
        )

        # Reset history for new turn
        self._reset_history(system_message)

        # Retry loop with maximum attempts
        max_discussion_retries = self.tuning.max_discuss_retries
        for attempt in range(max_discussion_retries):
            # Status indicator for UX
            print(f"\n🤖 {self.player_name} is thinking...")

            # Get completion from the LLM using turn history
            response_text = self.api_client.get_completion(self.turn_history)

            # Log raw response for debugging
            logger.info(
                f"Raw LLM Response from {self.player_name}:\n{response_text}"
            )

            # Handle API errors (None response)
            if response_text is None:
                logger.error(
                    f"{self.player_name}: API error on attempt {attempt + 1}/"
                    f"{max_discussion_retries}"
                )
                # Continue to retry if attempts remain
                continue

            # Try to parse the response
            try:
                data = parse_discussion_response(response_text)

                # Success! Append valid response to history
                self.turn_history.append(
                    ChatMessage(role="assistant", content=response_text)
                )

                # Log private thoughts
                logger.debug(
                    f"{self.player_name} private thoughts: "
                    f"{data['private_thoughts']}"
                )

                # Return Discussion object (empty text means abstention)
                return Discussion(
                    player_name=self.player_name,
                    text=data["discussion_text"],
                    private_thoughts=data.get("private_thoughts"),
                )

            except ValueError as e:
                # Parsing failed - log the error
                logger.warning(
                    f"{self.player_name}: Invalid response on attempt "
                    f"{attempt + 1}/{max_discussion_retries}. Error: {e}"
                )

                # If this was the last attempt, break out
                if attempt >= max_discussion_retries - 1:
                    break

                # Construct retry by appending bad response and error message
                # Append the LLM's bad response as an assistant message
                self.turn_history.append(
                    ChatMessage(role="assistant", content=response_text)
                )

                # Append the retry prompt as a user message
                self.turn_history.append(
                    ChatMessage(
                        role="user", content=prompts.DISCUSS_RETRY_TEMPLATE
                    )
                )

                # Loop continues to retry with updated conversation history

        # All retries exhausted - return empty Discussion (abstain)
        logger.error(
            f"{self.player_name}: Failed to generate valid discussion after "
            f"{max_discussion_retries} attempts. Defaulting to abstain."
        )
        return Discussion(
            player_name=self.player_name,
            text="",
            private_thoughts=None,
        )

    def vote(
        self,
        proposal: Proposal,
        game_state: GameState,
        rules: list[Rule],
        discussions: list[Discussion] | None = None,
    ) -> Vote:
        """
        Cast a vote on a proposal using an LLM.

        This method continues the player's turn (does NOT reset history).
        It appends the vote instruction to the existing conversation history.

        Args:
            proposal: The proposal being voted on.
            game_state: The current state of the game.
            rules: The current list of all rules.
            discussions: Optional list of Discussion objects from all players.
                        Used to provide context for the vote decision.

        Returns:
            A complete Vote object representing the player's vote.
            If all retry attempts fail, returns an ABSTAIN vote.
        """
        # Use empty list if discussions not provided
        if discussions is None:
            discussions = []

        # Build vote instruction and append to history (continues turn)
        vote_instruction = self.prompt_builder.build_vote_instruction(
            proposal=proposal,
            discussions=discussions,
            rules=rules,
            player_name=self.player_name,
        )
        self.turn_history.append(vote_instruction)

        # Retry loop with maximum attempts
        max_vote_retries = self.tuning.max_vote_retries
        for attempt in range(max_vote_retries):
            # Status indicator for UX
            print(f"\n🤖 {self.player_name} is thinking...")

            # Get completion from the LLM using turn history
            response_text = self.api_client.get_completion(self.turn_history)

            # Log raw response for debugging
            logger.info(
                f"Raw LLM Response from {self.player_name}:\n{response_text}"
            )

            # Handle API errors (None response)
            if response_text is None:
                logger.error(
                    f"{self.player_name}: API error on attempt {attempt + 1}/"
                    f"{max_vote_retries}"
                )
                # Continue to retry if attempts remain
                continue

            # Try to parse the response
            try:
                data = parse_vote_response(response_text)

                # Success! Append valid response to history
                self.turn_history.append(
                    ChatMessage(role="assistant", content=response_text)
                )

                # Log private thoughts
                logger.debug(
                    f"{self.player_name} private thoughts: "
                    f"{data['private_thoughts']}"
                )

                # Cast vote to Literal type (parser guarantees it's valid)
                vote_value: Literal["YES", "NO", "ABSTAIN"] = data["vote"]  # type: ignore[assignment]
                return Vote(
                    player_name=self.player_name,
                    vote=vote_value,
                    reason=data["public_reason"],
                    private_thoughts=data["private_thoughts"],
                )

            except ValueError as e:
                # Parsing failed - log the error
                logger.warning(
                    f"{self.player_name}: Invalid response on attempt "
                    f"{attempt + 1}/{max_vote_retries}. Error: {e}"
                )

                # If this was the last attempt, break out
                if attempt >= max_vote_retries - 1:
                    break

                # Construct retry by appending bad response and error message
                # Append the LLM's bad response as an assistant message
                self.turn_history.append(
                    ChatMessage(role="assistant", content=response_text)
                )

                # Append the retry prompt as a user message
                self.turn_history.append(
                    ChatMessage(
                        role="user", content=prompts.VOTE_RETRY_TEMPLATE
                    )
                )

                # Loop continues to retry with updated conversation history

        # All retries exhausted - return ABSTAIN as fallback
        logger.error(
            f"{self.player_name}: Failed to generate valid vote after "
            f"{max_vote_retries} attempts. Defaulting to ABSTAIN."
        )
        return Vote(
            player_name=self.player_name,
            vote="ABSTAIN",
            reason="LLM Error: Failed to generate valid vote.",
        )

    def revise(
        self,
        proposal: Proposal,
        discussions: list[Discussion],
        game_state: GameState,
        rules: list[Rule],
    ) -> Proposal | None:
        """
        Revise a proposal based on discussion using an LLM.

        This method continues the proposer's turn (does NOT reset history).
        It appends the revision instruction with peer feedback to the existing
        conversation history.

        Args:
            proposal: The original proposal made by this player.
            discussions: A list of Discussion objects from all players.
            game_state: The current state of the game.
            rules: The current list of all rules.

        Returns:
            The (potentially) revised Proposal object,
            or None if the player chooses to withdraw the proposal.
        """
        # Build revision instruction and append to history (continues turn)
        revision_instruction = self.prompt_builder.build_revision_instruction(
            discussions=discussions
        )
        self.turn_history.append(revision_instruction)

        # Retry loop with maximum attempts
        max_revision_retries = self.tuning.max_revise_retries
        for attempt in range(max_revision_retries):
            # Status indicator for UX
            print(f"\n🤖 {self.player_name} is reviewing feedback...")

            # Get completion from the LLM using turn history
            response_text = self.api_client.get_completion(self.turn_history)

            # Log raw response for debugging
            logger.info(
                f"Raw LLM Response from {self.player_name}:\n{response_text}"
            )

            # Handle API errors (None response)
            if response_text is None:
                logger.error(
                    f"{self.player_name}: API error on attempt {attempt + 1}/"
                    f"{max_revision_retries}"
                )
                # Continue to retry if attempts remain
                continue

            # Try to parse the response
            try:
                data = parse_revision_response(response_text)

                # Success! Append valid response to history
                self.turn_history.append(
                    ChatMessage(role="assistant", content=response_text)
                )

                # Log private thoughts
                logger.debug(
                    f"{self.player_name} private thoughts: "
                    f"{data['private_thoughts']}"
                )

                # Handle based on action
                action = data["action"]

                if action == "WITHDRAW":
                    return None

                if action == "KEEP":
                    # Create a copy to update private_thoughts
                    kept_proposal = proposal.model_copy()
                    thoughts = data.get("private_thoughts")
                    kept_proposal.private_thoughts = thoughts
                    return kept_proposal

                # action == "MODIFY"
                # Create a copy and update with new values if provided
                new_proposal = proposal.model_copy()
                if data.get("new_text"):
                    new_proposal.new_text = data["new_text"]
                if data.get("rationale"):
                    new_proposal.rationale = data["rationale"]
                new_proposal.private_thoughts = data.get("private_thoughts")
                return new_proposal

            except ValueError as e:
                # Parsing failed - log the error
                logger.warning(
                    f"{self.player_name}: Invalid response on attempt "
                    f"{attempt + 1}/{max_revision_retries}. Error: {e}"
                )

                # If this was the last attempt, break out
                if attempt >= max_revision_retries - 1:
                    break

                # Construct retry by appending bad response and error message
                # Append the LLM's bad response as an assistant message
                self.turn_history.append(
                    ChatMessage(role="assistant", content=response_text)
                )

                # Append the retry prompt with the specific error as a user msg
                retry_message = prompts.REVISE_RETRY_TEMPLATE.format(
                    validation_error=str(e)
                )
                self.turn_history.append(
                    ChatMessage(role="user", content=retry_message)
                )

                # Loop continues to retry with updated conversation history

        # All retries exhausted - return original proposal (KEEP) as fallback
        # to avoid stalling the game
        logger.error(
            f"{self.player_name}: Failed to generate valid revision after "
            f"{max_revision_retries} attempts. Defaulting to KEEP."
        )
        return proposal
