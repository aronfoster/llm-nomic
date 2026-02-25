"""LLM-powered Judge implementation."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..data_models import ChatMessage, EngineTuningConfig, ModelDefinition
from ..judge_contracts import (
    JudgeScoreResponse,
    JudgeVetoResponse,
    StateUpdates,
)
from ..llm import ApiClientProtocol, PromptBuilder, create_api_client
from ..llm import prompts as llm_prompts
from ..llm.parsers import (
    parse_judge_maintain_state_response,
    parse_judge_score_response,
    parse_judge_veto_response,
)
from ..memory.memory_manager import MemoryManager
from ..utils.rule_filters import filter_scoring_rules
from .base_judge import BaseJudge

if TYPE_CHECKING:
    from ..core.game_manager import GameManager
    from ..data_models import Discussion, Proposal, Vote
    from ..players.base_player import BasePlayer

logger = logging.getLogger(__name__)


class LLMJudge(BaseJudge):
    """Judge strategy that delegates decisions to an LLM model."""

    def __init__(
        self,
        model_config: ModelDefinition,
        prompt_builder: PromptBuilder | None = None,
        api_client: ApiClientProtocol | None = None,
        tuning: EngineTuningConfig | None = None,
        memory_manager: MemoryManager | None = None,
    ) -> None:
        """Initialize the LLMJudge.

        Args:
            model_config (ModelDefinition): Configuration for the LLM model
                used for judging.
            prompt_builder (PromptBuilder, optional): Prompt builder instance.
                If None, a new PromptBuilder() is created.
            api_client (ApiClientProtocol, optional): API client for LLM
                calls. If None, create_api_client(model_config) is used.
            tuning: Optional engine tuning configuration.
            memory_manager: Optional MemoryManager for persistent memory
                injection. When None, no memory is injected.
        """
        self.model_config = model_config
        self.tuning = tuning or EngineTuningConfig()
        self.prompt_builder = prompt_builder or PromptBuilder()
        self.api_client = api_client or create_api_client(model_config)
        self.memory_manager = memory_manager
        # Accumulates the judge's assistant-role responses during a turn.
        # Reset each turn by GameLoop._reset_judge_turn_state().
        self._judge_turn_responses: list[ChatMessage] = []
        logger.info(
            "Initialized LLMJudge with model %s (provider: %s)",
            model_config.api_model_id,
            model_config.provider,
        )

    def _build_judge_system_message(
        self, memory_content: str = ""
    ) -> ChatMessage:
        """Build the judge system message, optionally appending memory.

        Args:
            memory_content: Optional memory content to append. Omitted when
                empty or whitespace.

        Returns:
            A ChatMessage with role="system".
        """
        content = llm_prompts.JUDGE_SYSTEM_PROMPT
        if memory_content.strip():
            content = (
                content
                + "\n\n"
                + llm_prompts.MEMORY_INJECTION.format(
                    full_memory_content=memory_content
                )
            )
        return ChatMessage(role="system", content=content)

    def _build_messages(
        self,
        game_manager: "GameManager",
        proposal: "Proposal",
        votes: list["Vote"],
        discussions: list["Discussion"],
    ) -> list[ChatMessage]:
        assert game_manager.rules_manager is not None
        assert game_manager.game_state is not None

        logger.debug(
            "Building judge context for proposal %s with %d votes and %d "
            "discussions",
            proposal.proposal_id,
            len(votes),
            len(discussions),
        )

        memory_content = (
            self.memory_manager.read("Judge") if self.memory_manager else ""
        )
        system_message = self._build_judge_system_message(memory_content)
        context_message = self.prompt_builder.build_judge_context_message(
            rules=game_manager.rules_manager.rules,
            game_state=game_manager.game_state,
            proposal=proposal,
            votes=votes,
            discussions=discussions,
        )
        return [system_message, context_message]

    def get_veto(
        self,
        game_manager: "GameManager",
        proposal: "Proposal",
        votes: list["Vote"],
        discussions: list["Discussion"],
    ) -> JudgeVetoResponse:
        base_messages = self._build_messages(
            game_manager, proposal, votes, discussions
        )
        base_messages.append(
            self.prompt_builder.build_judge_veto_prompt(
                game_state=game_manager.game_state,
            )
        )

        logger.debug(
            "Requesting veto decision from model %s",
            self.model_config.api_model_id,
        )

        # Retry loop with maximum attempts
        max_veto_retries = self.tuning.max_judge_veto_retries
        for attempt in range(max_veto_retries):
            # Use base_messages for first attempt, rebuild for retries
            messages = base_messages.copy()

            response_text = self.api_client.get_completion(messages)

            # Handle API errors (None response)
            if response_text is None:
                logger.error(
                    f"LLM Judge: API error on veto attempt {attempt + 1}/"
                    f"{max_veto_retries}"
                )
                # Continue to retry if attempts remain
                continue

            logger.info("Raw LLM judge veto response:\n%s", response_text)

            # Try to parse the response
            try:
                data = parse_judge_veto_response(response_text)

                # Success!
                logger.info(
                    "LLM Judge veto decision: %s | Reason: %s",
                    "VETO" if data["veto"] else "ALLOW",
                    data["reason"],
                )
                self._judge_turn_responses.append(
                    ChatMessage(role="assistant", content=response_text)
                )
                return {
                    "veto": data["veto"],
                    "reason": data["reason"],
                    "private_thoughts": data["private_thoughts"],
                }

            except ValueError as e:
                # Parsing failed - log the error
                logger.warning(
                    f"LLM Judge: Invalid veto response on attempt "
                    f"{attempt + 1}/{max_veto_retries}. Error: {e}"
                )

                # If this was the last attempt, break out
                if attempt >= max_veto_retries - 1:
                    break

                # Prepare retry by appending bad response and error message
                base_messages.append(
                    ChatMessage(role="assistant", content=response_text)
                )
                retry_message = llm_prompts.JUDGE_VETO_RETRY_TEMPLATE.format(
                    validation_error=str(e)
                )
                base_messages.append(
                    ChatMessage(role="user", content=retry_message)
                )

                # Loop continues to retry with updated messages

        # All retries exhausted - raise RuntimeError
        logger.error(
            f"LLM Judge: Failed to generate valid veto decision after "
            f"{max_veto_retries} attempts."
        )
        raise RuntimeError(
            f"LLM Judge failed to generate a valid veto decision after "
            f"{max_veto_retries} attempts."
        )

    def assess_scores(
        self,
        game_manager: "GameManager",
        players: list["BasePlayer"],
        proposal: "Proposal",
        votes: list["Vote"],
        discussions: list["Discussion"],
        proposal_passed: bool,
    ) -> JudgeScoreResponse:
        assert game_manager.game_state is not None
        assert game_manager.rules_manager is not None
        _ = players

        # Filter rules to only scoring-relevant ones
        scoring_rules = filter_scoring_rules(game_manager.rules_manager.rules)

        # Build scoring-specific context (not using _build_messages)
        system_message = ChatMessage(
            role="system", content=llm_prompts.JUDGE_SYSTEM_PROMPT
        )
        context_message = (
            self.prompt_builder.build_judge_score_context_message(
                rules=scoring_rules,
                game_state=game_manager.game_state,
                proposal=proposal,
                votes=votes,
                discussions=discussions,
                proposal_passed=proposal_passed,
            )
        )
        score_prompt = self.prompt_builder.build_judge_score_prompt(
            proposal_passed=proposal_passed
        )

        base_messages = [system_message, context_message, score_prompt]

        logger.debug(
            "Requesting score assessment from model %s (proposal %s)",
            self.model_config.api_model_id,
            "PASSED" if proposal_passed else "FAILED",
        )

        # Retry loop with maximum attempts
        max_score_retries = self.tuning.max_judge_score_retries
        for attempt in range(max_score_retries):
            # Use base_messages for first attempt, rebuild for retries
            messages = base_messages.copy()

            response_text = self.api_client.get_completion(messages)

            # Handle API errors (None response)
            if response_text is None:
                logger.error(
                    f"LLM Judge: API error on score assessment attempt "
                    f"{attempt + 1}/{max_score_retries}"
                )
                # Continue to retry if attempts remain
                continue

            logger.info("Raw LLM judge score response:\n%s", response_text)

            # Try to parse the response
            try:
                data = parse_judge_score_response(
                    response_text,
                    valid_players=list(game_manager.game_state.scores.keys()),
                )

                # Success! Return intended score adjustments (no mutation)
                adjustments = data["score_adjustments"]
                self._judge_turn_responses.append(
                    ChatMessage(role="assistant", content=response_text)
                )
                if not adjustments:
                    logger.info(
                        "LLM Judge proposed no score changes this turn."
                    )
                    return {
                        "private_thoughts": data["private_thoughts"],
                        "score_adjustments": [],
                    }

                for adj in adjustments:
                    logger.info(
                        "LLM Judge proposed %s %+d points (%s)",
                        adj["player"],
                        adj["delta"],
                        adj["reason"],
                    )
                return {
                    "private_thoughts": data["private_thoughts"],
                    "score_adjustments": adjustments,
                }

            except ValueError as e:
                # Parsing failed - log the error
                logger.warning(
                    f"LLM Judge: Invalid score response on attempt "
                    f"{attempt + 1}/{max_score_retries}. Error: {e}"
                )

                # If this was the last attempt, break out
                if attempt >= max_score_retries - 1:
                    break

                # Prepare retry by appending bad response and error message
                base_messages.append(
                    ChatMessage(role="assistant", content=response_text)
                )
                retry_message = llm_prompts.JUDGE_SCORE_RETRY_TEMPLATE.format(
                    validation_error=str(e)
                )
                base_messages.append(
                    ChatMessage(role="user", content=retry_message)
                )

                # Loop continues to retry with updated messages

        # All retries exhausted - raise RuntimeError
        logger.error(
            f"LLM Judge: Failed to generate valid score assessment after "
            f"{max_score_retries} attempts."
        )
        raise RuntimeError(
            f"LLM Judge failed to generate a valid score assessment after "
            f"{max_score_retries} attempts."
        )

    def maintain_state(
        self,
        game_manager: "GameManager",
        proposal: "Proposal",
        original_rule_text: str | None,
        new_rule_text: str | None,
    ) -> StateUpdates:
        """
        LLM-powered state maintenance that updates GameState when rules change.

        Uses the LLM to determine if the rule change requires updating flags
        or target_score. Includes retry logic for invalid responses.
        """
        assert game_manager.game_state is not None

        # Build minimal context: just system message and maintain_state
        # prompt
        system_message = ChatMessage(
            role="system", content=llm_prompts.JUDGE_SYSTEM_PROMPT
        )
        maintain_state_prompt = (
            self.prompt_builder.build_judge_maintain_state_prompt(
                proposal=proposal,
                original_rule_text=original_rule_text,
                new_rule_text=new_rule_text,
                game_state=game_manager.game_state,
            )
        )
        base_messages = [system_message, maintain_state_prompt]

        logger.debug(
            "Requesting state maintenance decision from model %s for "
            "proposal %s",
            self.model_config.api_model_id,
            proposal.proposal_id,
        )

        # Retry loop with maximum attempts
        max_maintain_state_retries = (
            self.tuning.max_judge_maintain_state_retries
        )
        for attempt in range(max_maintain_state_retries):
            # Use base_messages for first attempt, rebuild for retries
            messages = base_messages.copy()

            response_text = self.api_client.get_completion(messages)

            # Handle API errors (None response)
            if response_text is None:
                logger.error(
                    f"LLM Judge: API error on maintain_state attempt "
                    f"{attempt + 1}/{max_maintain_state_retries}"
                )
                # Continue to retry if attempts remain
                continue

            logger.info(
                "Raw LLM judge maintain_state response:\n%s", response_text
            )

            # Try to parse the response
            try:
                data = parse_judge_maintain_state_response(response_text)

                # Success! Build StateUpdates from parsed data
                state_updates: StateUpdates = {}
                if data["flags"]:
                    state_updates["flags"] = data["flags"]
                target_score_val = data["target_score"]
                if target_score_val is not None:
                    state_updates["target_score"] = target_score_val

                if state_updates:
                    logger.info(
                        "LLM Judge recommends state updates: %s", state_updates
                    )
                else:
                    logger.info("LLM Judge recommends no state changes.")

                self._judge_turn_responses.append(
                    ChatMessage(role="assistant", content=response_text)
                )
                return state_updates

            except ValueError as e:
                # Parsing failed - log the error
                logger.warning(
                    f"LLM Judge: Invalid maintain_state response on attempt "
                    f"{attempt + 1}/{max_maintain_state_retries}. "
                    f"Error: {e}"
                )

                # If this was the last attempt, break out
                if attempt >= max_maintain_state_retries - 1:
                    break

                # Prepare retry by appending bad response and error message
                base_messages.append(
                    ChatMessage(role="assistant", content=response_text)
                )
                retry_message = (
                    llm_prompts.JUDGE_MAINTAIN_STATE_RETRY_TEMPLATE.format(
                        validation_error=str(e)
                    )
                )
                base_messages.append(
                    ChatMessage(role="user", content=retry_message)
                )

                # Loop continues to retry with updated messages

        # All retries exhausted - raise RuntimeError
        logger.error(
            f"LLM Judge: Failed to generate valid maintain_state decision "
            f"after {max_maintain_state_retries} attempts."
        )
        raise RuntimeError(
            f"LLM Judge failed to generate a valid maintain_state decision "
            f"after {max_maintain_state_retries} attempts."
        )

    def update_memory(self) -> None:
        """Update the judge's persistent memory file after a completed turn.

        Builds a minimal message list from the system prompt, the judge's
        own responses cached during the turn, and the memory update prompt.
        Calls the API once (no retry) and conditionally writes the response.

        This method is a no-op when ``memory_manager`` is ``None``.
        """
        if self.memory_manager is None:
            return

        if not self._judge_turn_responses:
            logger.warning(
                "Judge: no turn responses cached, skipping memory update"
            )
            return

        character_limit = self.memory_manager.max_characters or 0
        if character_limit:
            update_prompt = llm_prompts.MEMORY_UPDATE_PROMPT_WITH_LIMIT.format(
                character_limit=character_limit
            )
        else:
            update_prompt = llm_prompts.MEMORY_UPDATE_PROMPT
        system_message = ChatMessage(
            role="system", content=llm_prompts.JUDGE_SYSTEM_PROMPT
        )
        messages = (
            [system_message]
            + self._judge_turn_responses
            + [ChatMessage(role="user", content=update_prompt)]
        )

        response = self.api_client.get_completion(messages)

        if response is None:
            logger.warning(
                "Judge: memory update API call failed, keeping old memory"
            )
            return

        if len(response.strip()) < 50:
            logger.warning(
                f"Judge: memory update response too short "
                f"({len(response.strip())} chars), keeping old memory"
            )
            return

        self.memory_manager.write("Judge", response)
