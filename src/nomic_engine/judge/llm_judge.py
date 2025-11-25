"""LLM-powered Judge implementation."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..data_models import ChatMessage, ModelDefinition
from ..llm import ApiClient, PromptBuilder
from ..llm import prompts as llm_prompts
from ..llm.parsers import (
    parse_judge_score_response,
    parse_judge_veto_response,
)
from .base_judge import BaseJudge, JudgeScoreResponse, JudgeVetoResponse

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
        api_client: ApiClient | None = None,
    ) -> None:
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
        messages = self._build_messages(
            game_manager, proposal, votes, discussions
        )
        messages.append(self.prompt_builder.build_judge_veto_prompt())

        logger.debug(
            "Requesting veto decision from model %s",
            self.model_config.api_model_id,
        )

        response_text = self.api_client.get_completion(messages)
        if response_text is None:
            raise RuntimeError("LLM judge failed to return a veto decision.")

        logger.info("Raw LLM judge veto response:\n%s", response_text)

        try:
            data = parse_judge_veto_response(response_text)
        except ValueError as e:
            logger.error(f"Invalid judge veto response: {e}")
            raise

        logger.info(
            "LLM Judge veto decision: %s | Reason: %s",
            "VETO" if data["veto"] else "ALLOW",
            data["reason"],
        )
        return {
            "veto": bool(data["veto"]),
            "reason": data.get("reason"),
            "private_thoughts": data.get("private_thoughts"),
        }

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

        messages = self._build_messages(
            game_manager, proposal, votes, discussions
        )
        messages.append(self.prompt_builder.build_judge_score_prompt())

        logger.debug(
            "Requesting score assessment from model %s",
            self.model_config.api_model_id,
        )

        response_text = self.api_client.get_completion(messages)
        if response_text is None:
            raise RuntimeError("LLM judge failed to return score changes.")

        logger.info("Raw LLM judge score response:\n%s", response_text)

        try:
            data = parse_judge_score_response(
                response_text,
                valid_players=list(game_manager.game_state.scores.keys()),
            )
        except ValueError as e:
            logger.error(f"Invalid judge score response: {e}")
            raise

        adjustments = data.get("score_adjustments", [])
        if not adjustments:
            logger.info("LLM Judge applied no score changes this turn.")
            return {
                "private_thoughts": data.get("private_thoughts"),
                "score_adjustments": [],
            }

        for adj in adjustments:
            player_name = adj["player"]
            delta = adj["delta"]
            reason = adj["reason"]
            game_manager.game_state.scores[player_name] += delta
            logger.info(
                "LLM Judge adjusted %s by %+d points (%s)",
                player_name,
                delta,
                reason,
            )
        return {
            "private_thoughts": data.get("private_thoughts"),
            "score_adjustments": adjustments,
        }
