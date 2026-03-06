"""
LLM player implementation for the Nomic game.

This module provides a stub for an LLM-powered player that will
eventually use language models to participate in the game.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

from ..data_models import (
    ChatMessage,
    Discussion,
    EngineTuningConfig,
    GameState,
    ModelDefinition,
    Proposal,
    ProposalType,
    Rule,
    Vote,
)
from ..llm import (
    PromptBuilder,
    build_token_usage_record,
    create_api_client,
    parse_discussion_response,
    parse_proposal_response,
    parse_revision_response,
    parse_vote_response,
    prompts,
)
from ..llm.parsers import ProposalResponse, RevisionResponse, VoteResponse
from ..llm.retry_helper import llm_retry_loop
from ..memory.memory_manager import MemoryManager
from ..utils.player_label import assemble_player_label
from .base_player import BasePlayer

if TYPE_CHECKING:
    from ..utils.token_usage_logger import TokenUsageLogger

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
        personality: str = "friendly",
        tuning: EngineTuningConfig | None = None,
        memory_manager: MemoryManager | None = None,
        token_usage_logger: TokenUsageLogger | None = None,
    ) -> None:
        """
        Initialize an LLM player with a specific model configuration.

        Args:
            player_name: The unique name for this player.
            model_config: The ModelDefinition containing API configuration
                          for this player's LLM.
            personality: Lowercase personality name (e.g. "machiavellian").
                         Must match a file in the ``personalities/`` directory.
            tuning: Optional engine tuning configuration.
            memory_manager: Optional MemoryManager for persistent memory
                injection. When None, no memory is injected.
            token_usage_logger: Optional TokenUsageLogger for recording token
                usage after every API call. When None, no usage is recorded.
        """
        super().__init__(player_name)
        self.model_config = model_config
        self.personality = personality
        self.tuning = tuning or EngineTuningConfig()
        self.memory_manager = memory_manager
        self.token_usage_logger = token_usage_logger
        self.api_client = create_api_client(self.model_config)
        self.prompt_builder = PromptBuilder()
        # Stateful conversation history for the current turn
        self.turn_history: list[ChatMessage] = []
        # Move number updated on each player action for use in logging
        self._current_move_number: int = 0

    @property
    def player_label(self) -> str:
        """Return a label with personality and model id for display."""
        return assemble_player_label(
            self.player_name,
            is_human=False,
            personality=self.personality,
            model_id=self.model_config.id,
        )

    def _read_own_memory(self) -> str:
        """Return this player's memory content, or '' if unavailable."""
        if self.memory_manager is None:
            return ""
        return self.memory_manager.read(self.player_name)

    def _reset_history(
        self, system_message: ChatMessage, user_message: ChatMessage
    ) -> None:
        """
        Reset the conversation history for a new turn/action.

        Clears turn_history and initialises it with [system, user] so that
        every API call — including the very first — has at least one user
        message. This ensures cache prefix matching works from call 1.

        Args:
            system_message: The stable system message (cacheable prefix).
            user_message: The phase-specific user message.
        """
        self.turn_history = [system_message, user_message]

    def _log_usage(self, result: object, call_type: str) -> None:
        """Extract metadata and log token usage. Never raises.

        Args:
            result: The CompletionResult returned by get_completion().
            call_type: One of propose, discuss, revise, vote, memory_update.
        """
        if self.token_usage_logger is None:
            return
        from ..data_models import CompletionResult

        if not isinstance(result, CompletionResult):
            return
        try:
            record = build_token_usage_record(
                result=result,
                model_config=self.model_config,
                call_type=call_type,
                move_number=self._current_move_number,
                player_name=self.player_name,
            )
            self.token_usage_logger.log(record)
        except Exception as exc:
            logger.warning(
                "%s: failed to build/log token usage record: %s",
                self.player_name,
                exc,
            )

    def propose(
        self,
        game_state: GameState,
        rules: list[Rule],
        continue_turn: bool = False,
        withdrawal_attempt: int = 0,
        max_withdrawal_retries: int = 0,
        post_parse_validator: Callable[[ProposalResponse], None] | None = None,
    ) -> Proposal:
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
        self._current_move_number = game_state.move_number

        # Build system + user messages for proposer (starts new turn)
        system_msg, user_msg = (
            self.prompt_builder.build_proposer_system_message(
                rules=rules,
                game_state=game_state,
                player_name=self.player_name,
                personality=self.personality,
                memory_content=self._read_own_memory(),
            )
        )

        # Reset history for a fresh turn, unless this is a pivot retry.
        if not continue_turn:
            self._reset_history(system_msg, user_msg)
        elif not self.turn_history:
            # Defensive fallback: initialize context if history is unexpectedly
            # empty even though caller requested a cumulative retry.
            self._reset_history(system_msg, user_msg)

        # Retry loop with maximum attempts
        max_proposal_retries = self.tuning.max_propose_retries
        try:
            data = llm_retry_loop(
                history=self.turn_history,
                api_client=self.api_client,
                parse_fn=parse_proposal_response,
                max_retries=max_proposal_retries,
                retry_template=prompts.PROPOSE_RETRY_TEMPLATE,
                actor_label=self.player_label,
                action_description="thinking about a proposal",
                log_usage=lambda result: self._log_usage(result, "propose"),
                post_parse_validator=post_parse_validator,
                legality_retry_template=prompts.PROPOSE_LEGALITY_RETRY_TEMPLATE,
            )
        except RuntimeError:
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

        # Construct and return the Proposal object
        # Note: proposal_id is left as None; GameLoop assigns it
        return Proposal(
            proposer_name=self.player_name,
            move_number=game_state.move_number,
            type=ProposalType(data["type"]),  # Convert str to enum
            proposal_id=None,
            target_rule_id=data["target_rule_id"],
            new_text=data["new_text"],
            rationale=data["rationale"],
            private_thoughts=data["private_thoughts"],
        )

    def begin_discussion_turn(
        self,
        proposal: Proposal,
        game_state: GameState,
        rules: list[Rule],
    ) -> None:
        """
        Initialise the discusser's conversation history for a new round.

        Builds the system message that establishes the player's context
        (rules, game state, proposal) and resets conversation history.
        Called by ``GameLoop._collect_discussions()`` before ``discuss()``
        on each fresh discussion round; skipped on retry rounds when the
        ``retain_discusser_history_on_retry`` flag is True.

        Args:
            proposal: The proposal being discussed.
            game_state: The current state of the game.
            rules: The current list of all rules.
        """
        self._current_move_number = game_state.move_number
        system_msg, user_msg = (
            self.prompt_builder.build_discusser_system_message(
                proposal=proposal,
                rules=rules,
                game_state=game_state,
                player_name=self.player_name,
                personality=self.personality,
                memory_content=self._read_own_memory(),
            )
        )
        self._reset_history(system_msg, user_msg)

    def discuss(
        self,
        proposal: Proposal,
        game_state: GameState,
        rules: list[Rule],
    ) -> Discussion:
        """
        Provide discussion/commentary on a proposal using an LLM.

        ``begin_discussion_turn()`` must be called before this method on the
        first discussion call of each round to initialise conversation history.
        This method does not perform any history initialisation itself.

        Args:
            proposal: The proposal being discussed.
            game_state: The current state of the game.
            rules: The current list of all rules.

        Returns:
            A Discussion object containing the player's discussion.
            If the player abstains, Discussion.text will be empty.
        """
        self._current_move_number = game_state.move_number

        # Retry loop with maximum attempts
        max_discussion_retries = self.tuning.max_discuss_retries
        try:
            data = llm_retry_loop(
                history=self.turn_history,
                api_client=self.api_client,
                parse_fn=parse_discussion_response,
                max_retries=max_discussion_retries,
                retry_template=prompts.DISCUSS_RETRY_TEMPLATE,
                actor_label=self.player_label,
                action_description="thinking...",
                log_usage=lambda result: self._log_usage(result, "discuss"),
            )
        except RuntimeError:
            # All retries exhausted - return empty Discussion (abstain)
            logger.error(
                f"{self.player_name}: Failed to generate valid discussion "
                f"after {max_discussion_retries} attempts. "
                "Defaulting to abstain."
            )
            return Discussion(
                player_name=self.player_name,
                text="",
                private_thoughts=None,
            )

        # Return Discussion object (empty text means abstention)
        return Discussion(
            player_name=self.player_name,
            text=data["discussion_text"],
            private_thoughts=data["private_thoughts"],
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
        self._current_move_number = game_state.move_number

        # Use empty list if discussions not provided
        if discussions is None:
            discussions = []

        allow_abstention = game_state.flags.get("allow_abstention", False)

        # Build vote instruction and append to history (continues turn)
        vote_instruction = self.prompt_builder.build_vote_instruction(
            proposal=proposal,
            discussions=discussions,
            rules=rules,
            player_name=self.player_name,
            personality=self.personality,
            game_state=game_state,
        )
        self.turn_history.append(vote_instruction)

        # When ABSTAIN is forbidden, validate parsed votes against it
        abstain_validator: Callable[[VoteResponse], None] | None = None
        if not allow_abstention:

            def abstain_validator(parsed: VoteResponse) -> None:
                if parsed.get("vote") == "ABSTAIN":
                    raise ValueError(
                        "ABSTAIN is not permitted; you must vote YES or NO."
                    )

        # Retry loop with maximum attempts
        max_vote_retries = self.tuning.max_vote_retries
        try:
            data = llm_retry_loop(
                history=self.turn_history,
                api_client=self.api_client,
                parse_fn=parse_vote_response,
                max_retries=max_vote_retries,
                retry_template=prompts.VOTE_RETRY_TEMPLATE,
                actor_label=self.player_label,
                action_description="thinking...",
                log_usage=lambda result: self._log_usage(result, "vote"),
                post_parse_validator=abstain_validator,
                legality_retry_template=prompts.VOTE_ABSTAIN_FORBIDDEN_RETRY_TEMPLATE,
            )
        except RuntimeError:
            # All retries exhausted
            if not allow_abstention:
                # ABSTAIN is forbidden — fall back to NO to avoid crashing
                logger.error(
                    f"{self.player_name}: Failed to generate valid vote after "
                    f"{max_vote_retries} attempts. Defaulting to NO "
                    "(ABSTAIN is forbidden)."
                )
                return Vote(
                    player_name=self.player_name,
                    vote="NO",
                    reason="LLM Error: Failed to generate valid vote.",
                )
            logger.error(
                f"{self.player_name}: Failed to generate valid vote after "
                f"{max_vote_retries} attempts. Defaulting to ABSTAIN."
            )
            return Vote(
                player_name=self.player_name,
                vote="ABSTAIN",
                reason="LLM Error: Failed to generate valid vote.",
            )

        return Vote(
            player_name=self.player_name,
            vote=data["vote"],
            reason=data["public_reason"],
            private_thoughts=data["private_thoughts"],
        )

    def note_withdrawal_for_retry(
        self,
        discussions: list[Discussion],
        withdrawal_attempt: int,
        max_withdrawal_retries: int,
    ) -> None:
        """Append a pivot prompt while preserving full turn context."""
        del discussions

        pivot_message = prompts.WITHDRAWAL_RETRY_TEMPLATE.format(
            withdrawal_attempt=withdrawal_attempt,
            max_withdrawal_retries=max_withdrawal_retries,
        )
        self.turn_history.append(
            ChatMessage(role="user", content=pivot_message)
        )

    def on_proposal_updated(
        self,
        proposal: Proposal,
        game_state: GameState,
        rules: list[Rule],
        withdrawal_attempt: int,
        max_withdrawal_retries: int,
    ) -> None:
        """Append a user message with the new proposal context.

        Injects the replacement proposal into the existing discussion history
        without resetting it, so accumulated reasoning is preserved.

        Args:
            proposal: The new (replacement) proposal.
            game_state: Current game state.
            rules: Current rules.
            withdrawal_attempt: The current retry attempt number (1-based).
            max_withdrawal_retries: Max retries configured for this game.
        """
        proposal_block = self.prompt_builder._format_proposal(
            proposal, rules, self.player_name
        )
        message = prompts.DISCUSS_PROPOSAL_UPDATED_TEMPLATE.format(
            withdrawal_attempt=withdrawal_attempt,
            max_withdrawal_retries=max_withdrawal_retries,
            proposal_block=proposal_block,
            json_format_enforcement=prompts.JSON_FORMAT_ENFORCEMENT,
        )
        self.turn_history.append(ChatMessage(role="user", content=message))

    def revise(
        self,
        proposal: Proposal,
        discussions: list[Discussion],
        game_state: GameState,
        rules: list[Rule],
        post_parse_validator: Callable[[RevisionResponse], None] | None = None,
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
        self._current_move_number = game_state.move_number

        # Build revision instruction and append to history (continues turn)
        revision_instruction = self.prompt_builder.build_revision_instruction(
            discussions=discussions,
            personality=self.personality,
        )
        self.turn_history.append(revision_instruction)

        # Retry loop with maximum attempts
        max_revision_retries = self.tuning.max_revise_retries
        try:
            data = llm_retry_loop(
                history=self.turn_history,
                api_client=self.api_client,
                parse_fn=parse_revision_response,
                max_retries=max_revision_retries,
                retry_template=prompts.REVISE_RETRY_TEMPLATE,
                actor_label=self.player_label,
                action_description="reviewing feedback...",
                log_usage=lambda result: self._log_usage(result, "revise"),
                post_parse_validator=post_parse_validator,
                legality_retry_template=prompts.REVISE_LEGALITY_RETRY_TEMPLATE,
            )
        except RuntimeError:
            # All retries exhausted - return original proposal (KEEP) as
            # fallback to avoid stalling the game
            logger.error(
                f"{self.player_name}: Failed to generate valid revision after "
                f"{max_revision_retries} attempts. Defaulting to KEEP."
            )
            return proposal

        # Handle based on action
        action = data["action"]

        if action == "WITHDRAW":
            return None

        if action == "KEEP":
            # Create a copy to update private_thoughts
            kept_proposal = proposal.model_copy()
            kept_proposal.private_thoughts = data["private_thoughts"]
            return kept_proposal

        # action == "MODIFY"
        # Create a copy and update with new values if provided
        new_proposal = proposal.model_copy()
        new_text = data["new_text"]
        if new_text:
            new_proposal.new_text = new_text
        rationale = data["rationale"]
        if rationale:
            new_proposal.rationale = rationale
        new_proposal.private_thoughts = data["private_thoughts"]
        return new_proposal

    def update_memory(
        self,
        judge_turn_outputs: list[ChatMessage] | None = None,
    ) -> None:
        """Update this player's persistent memory file after a completed turn.

        Appends the memory update prompt to the existing turn history, calls
        the API once (no retry), and conditionally writes the response.

        Args:
            judge_turn_outputs: Optional list of judge ChatMessages from the
                current turn. When provided and non-empty, they are injected
                between turn_history and MEMORY_UPDATE_PROMPT so the player
                has full context of judge actions when consolidating memory.

        This method is a no-op when ``memory_manager`` is ``None``.
        """
        if self.memory_manager is None:
            return

        logger.info(
            f"🤖 {self.player_name} ({self.personality} / "
            f"{self.model_config.api_model_id}) is remembering..."
        )

        if judge_turn_outputs:
            judge_block = "\n\n".join(
                msg.content for msg in judge_turn_outputs
            )
            self.turn_history.append(
                ChatMessage(
                    role="user",
                    content=(
                        "=== JUDGE ACTIONS THIS TURN ===\n"
                        + judge_block
                        + "\n=== END JUDGE ACTIONS ==="
                    ),
                )
            )

        character_limit = self.memory_manager.max_characters or 0
        if character_limit:
            update_prompt = prompts.MEMORY_UPDATE_PROMPT_WITH_LIMIT.format(
                character_limit=character_limit
            )
        else:
            update_prompt = prompts.MEMORY_UPDATE_PROMPT
        self.turn_history.append(
            ChatMessage(role="user", content=update_prompt)
        )

        result = self.api_client.get_completion(self.turn_history)
        self._log_usage(result, "memory_update")
        response = result.text

        if response is None:
            logger.warning(
                f"{self.player_name}: memory update API call failed, "
                "keeping old memory"
            )
            return

        if len(response.strip()) < 50:
            logger.warning(
                f"{self.player_name}: memory update response too short "
                f"({len(response.strip())} chars), keeping old memory"
            )
            return

        self.memory_manager.write(self.player_name, response)
