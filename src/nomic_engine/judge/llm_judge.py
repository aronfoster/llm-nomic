"""LLM-powered Judge implementation."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

from ..data_models import ChatMessage, ModelDefinition
from ..judge_contracts import (
    JudgeScoreResponse,
    JudgeVetoResponse,
    StateUpdates,
)
from ..llm import ApiClient, PromptBuilder
from ..llm import prompts as llm_prompts
from ..llm.parsers import (
    parse_judge_maintain_state_response,
    parse_judge_score_response,
    parse_judge_veto_response,
)
from .base_judge import BaseJudge

if TYPE_CHECKING:
    from ..core.game_manager import GameManager
    from ..data_models import Discussion, Proposal, Vote
    from ..players.base_player import BasePlayer

logger = logging.getLogger(__name__)


class LLMJudge(BaseJudge):
    """Judge strategy that delegates decisions to an LLM model."""

    # Maximum number of retry attempts when LLM produces invalid JSON
    MAX_VETO_RETRIES = 2
    MAX_SCORE_RETRIES = 2
    MAX_MAINTAIN_STATE_RETRIES = 2

    def __init__(
        self,
        model_config: ModelDefinition,
        prompt_builder: PromptBuilder | None = None,
        api_client: ApiClient | None = None,
    ) -> None:
        """Initialize the LLMJudge.

        Args:
            model_config (ModelDefinition): Configuration for the LLM model
                used for judging.
            prompt_builder (PromptBuilder, optional): Prompt builder instance.
                If None, a new PromptBuilder() is created.
            api_client (ApiClient, optional): API client instance for LLM calls
                If None, a new ApiClient(model_config) is created.
        """
        self.model_config = model_config
        self.prompt_builder = prompt_builder or PromptBuilder()
        self.api_client = api_client or ApiClient(model_config)
        logger.info(
            "Initialized LLMJudge with model %s (provider: %s)",
            model_config.api_model_id,
            model_config.provider,
        )

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

        system_message = ChatMessage(
            role="system", content=llm_prompts.JUDGE_SYSTEM_PROMPT
        )
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
        for attempt in range(self.MAX_VETO_RETRIES):
            # Use base_messages for first attempt, rebuild for retries
            messages = base_messages.copy()

            response_text = self.api_client.get_completion(messages)

            # Handle API errors (None response)
            if response_text is None:
                logger.error(
                    f"LLM Judge: API error on veto attempt {attempt + 1}/"
                    f"{self.MAX_VETO_RETRIES}"
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
                reason = cast(str | None, data.get("reason"))
                private_thoughts = cast(
                    str | None, data.get("private_thoughts")
                )
                return {
                    "veto": bool(data["veto"]),
                    "reason": reason,
                    "private_thoughts": private_thoughts,
                }

            except ValueError as e:
                # Parsing failed - log the error
                logger.warning(
                    f"LLM Judge: Invalid veto response on attempt "
                    f"{attempt + 1}/{self.MAX_VETO_RETRIES}. Error: {e}"
                )

                # If this was the last attempt, break out
                if attempt >= self.MAX_VETO_RETRIES - 1:
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
            f"{self.MAX_VETO_RETRIES} attempts."
        )
        raise RuntimeError(
            f"LLM Judge failed to generate a valid veto decision after "
            f"{self.MAX_VETO_RETRIES} attempts."
        )

    def assess_scores(
        self,
        game_manager: "GameManager",
        players: list["BasePlayer"],
        proposal: "Proposal",
        votes: list["Vote"],
        discussions: list["Discussion"],
    ) -> JudgeScoreResponse:
        assert game_manager.game_state is not None
        _ = players

        base_messages = self._build_messages(
            game_manager, proposal, votes, discussions
        )
        base_messages.append(self.prompt_builder.build_judge_score_prompt())

        logger.debug(
            "Requesting score assessment from model %s",
            self.model_config.api_model_id,
        )

        # Retry loop with maximum attempts
        for attempt in range(self.MAX_SCORE_RETRIES):
            # Use base_messages for first attempt, rebuild for retries
            messages = base_messages.copy()

            response_text = self.api_client.get_completion(messages)

            # Handle API errors (None response)
            if response_text is None:
                logger.error(
                    f"LLM Judge: API error on score assessment attempt "
                    f"{attempt + 1}/{self.MAX_SCORE_RETRIES}"
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
                adjustments = data.get("score_adjustments", [])
                if not adjustments:
                    logger.info(
                        "LLM Judge proposed no score changes this turn."
                    )
                    return {
                        "private_thoughts": data.get("private_thoughts"),
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
                    "private_thoughts": data.get("private_thoughts"),
                    "score_adjustments": adjustments,
                }

            except ValueError as e:
                # Parsing failed - log the error
                logger.warning(
                    f"LLM Judge: Invalid score response on attempt "
                    f"{attempt + 1}/{self.MAX_SCORE_RETRIES}. Error: {e}"
                )

                # If this was the last attempt, break out
                if attempt >= self.MAX_SCORE_RETRIES - 1:
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
            f"{self.MAX_SCORE_RETRIES} attempts."
        )
        raise RuntimeError(
            f"LLM Judge failed to generate a valid score assessment after "
            f"{self.MAX_SCORE_RETRIES} attempts."
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
        for attempt in range(self.MAX_MAINTAIN_STATE_RETRIES):
            # Use base_messages for first attempt, rebuild for retries
            messages = base_messages.copy()

            response_text = self.api_client.get_completion(messages)

            # Handle API errors (None response)
            if response_text is None:
                logger.error(
                    f"LLM Judge: API error on maintain_state attempt "
                    f"{attempt + 1}/{self.MAX_MAINTAIN_STATE_RETRIES}"
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
                if data.get("flags"):
                    state_updates["flags"] = data["flags"]
                if data.get("target_score") is not None:
                    state_updates["target_score"] = data["target_score"]

                if state_updates:
                    logger.info(
                        "LLM Judge recommends state updates: %s", state_updates
                    )
                else:
                    logger.info("LLM Judge recommends no state changes.")

                return state_updates

            except ValueError as e:
                # Parsing failed - log the error
                logger.warning(
                    f"LLM Judge: Invalid maintain_state response on attempt "
                    f"{attempt + 1}/{self.MAX_MAINTAIN_STATE_RETRIES}. "
                    f"Error: {e}"
                )

                # If this was the last attempt, break out
                if attempt >= self.MAX_MAINTAIN_STATE_RETRIES - 1:
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
            f"after {self.MAX_MAINTAIN_STATE_RETRIES} attempts."
        )
        raise RuntimeError(
            f"LLM Judge failed to generate a valid maintain_state decision "
            f"after {self.MAX_MAINTAIN_STATE_RETRIES} attempts."
        )
