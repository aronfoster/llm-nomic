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
from ..llm import (
    ApiClientProtocol,
    PromptBuilder,
    build_token_usage_record,
    create_api_client,
)
from ..llm import prompts as llm_prompts
from ..llm.api_clients import BudgetedApiClient
from ..llm.parsers import (
    parse_judge_maintain_state_response,
    parse_judge_score_response,
    parse_judge_veto_response,
)
from ..llm.retry_helper import llm_retry_loop
from ..memory.memory_manager import MemoryManager
from ..usage_budget import LlmCallOptions, UsageBudgetGuard
from .base_judge import BaseJudge

if TYPE_CHECKING:
    from ..core.game_manager import GameManager
    from ..data_models import (
        CompletionResult,
        Discussion,
        GameState,
        Proposal,
        Rule,
        Vote,
    )
    from ..players.base_player import BasePlayer
    from ..utils.token_usage_logger import TokenUsageLogger

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
        token_usage_logger: TokenUsageLogger | None = None,
        *,
        call_options: LlmCallOptions | None = None,
        usage_guard: UsageBudgetGuard | None = None,
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
            token_usage_logger: Optional TokenUsageLogger for recording token
                usage after every API call. When None, no usage is recorded.
            call_options: Per-call timeout and output cap used when this
                judge constructs its own client.
            usage_guard: Shared game budget checked before every provider
                call, including a caller-supplied api_client.
        """
        self.model_config = model_config
        self.tuning = tuning or EngineTuningConfig()
        self.prompt_builder = prompt_builder or PromptBuilder()
        if api_client is None:
            self.api_client = create_api_client(
                model_config,
                call_options=call_options,
                usage_guard=usage_guard,
            )
        elif usage_guard is not None and not isinstance(
            api_client, BudgetedApiClient
        ):
            self.api_client = BudgetedApiClient(
                api_client, usage_guard, model_config.provider
            )
        else:
            self.api_client = api_client
        self.memory_manager = memory_manager
        self.token_usage_logger = token_usage_logger
        # Accumulates the judge's assistant-role responses during a turn.
        # Reset each turn by GameLoop._reset_judge_turn_state().
        # Still used by GameLoop._update_all_memories() to pass judge context
        # to LLMPlayer.update_memory() calls.
        self._judge_turn_responses: list[ChatMessage] = []
        # Stateful conversation history shared across all four per-turn calls:
        # get_veto → assess_scores → maintain_state → update_memory.
        # Initialized by get_veto; reset each turn by
        # GameLoop._reset_judge_turn_state(). The stable system message
        # (JUDGE_SYSTEM_PROMPT + memory injection) is always the first element,
        # enabling Anthropic/xAI cache hits from the second call onward.
        self.turn_history: list[ChatMessage] = []
        # Move number updated on each judge action for use in logging
        self._current_move_number: int = 0
        logger.info(
            "Initialized LLMJudge with model %s (provider: %s)",
            model_config.api_model_id,
            model_config.provider,
        )

    @property
    def _judge_label(self) -> str:
        """Return a display label for the judge (used in status messages)."""
        return f"⚖️ Judge [{self.model_config.api_model_id}]"

    def _build_judge_system_message(
        self,
        rules: list["Rule"],
        game_state: "GameState",
        proposal: "Proposal",
        votes: list["Vote"],
        discussions: list["Discussion"],
        memory_content: str = "",
    ) -> ChatMessage:
        """Build the judge system message with embedded turn context.

        Combines JUDGE_SYSTEM_PROMPT, the full turn context (rules,
        proposal, votes, scores, discussions), and an optional memory
        block. The memory block is always last so that it is the closest
        context to the model's next response.

        The returned message is byte-identical on every subsequent call
        within the same turn, enabling Anthropic/xAI cache hits from the
        second call onward.

        Args:
            rules: The current list of rules.
            game_state: The current game state (scores, flags, etc.).
            proposal: The proposal being evaluated this turn.
            votes: The votes cast on the proposal.
            discussions: The discussion contributions for this turn.
            memory_content: Optional memory content to append. Omitted
                when empty or whitespace.

        Returns:
            A ChatMessage with role="system".
        """
        context_block = self.prompt_builder.build_judge_context_block(
            rules=rules,
            game_state=game_state,
            proposal=proposal,
            votes=votes,
            discussions=discussions,
        )
        content = llm_prompts.JUDGE_SYSTEM_PROMPT + "\n\n" + context_block
        if memory_content.strip():
            content = (
                content
                + "\n\n"
                + llm_prompts.MEMORY_INJECTION.format(
                    full_memory_content=memory_content
                )
            )
        return ChatMessage(role="system", content=content)

    def _log_usage(self, result: CompletionResult, call_type: str) -> None:
        """Extract metadata and log token usage. Never raises.

        Args:
            result: The CompletionResult returned by get_completion().
            call_type: One of judge_veto, judge_score, judge_maintain_state,
                memory_update.
        """
        if self.token_usage_logger is None:
            return
        try:
            record = build_token_usage_record(
                result=result,
                model_config=self.model_config,
                call_type=call_type,
                move_number=self._current_move_number,
                player_name="Judge",
            )
            self.token_usage_logger.log(record)
        except Exception as exc:
            logger.warning(
                "Judge: failed to build/log token usage record: %s", exc
            )

    def get_veto(
        self,
        game_manager: "GameManager",
        proposal: "Proposal",
        votes: list["Vote"],
        discussions: list["Discussion"],
    ) -> JudgeVetoResponse:
        assert game_manager.game_state is not None
        assert game_manager.rules_manager is not None
        self._current_move_number = game_manager.game_state.move_number

        # Initialize turn history for this turn.
        # The system message (judge persona + full turn context + optional
        # memory) is byte-identical on every subsequent call within the
        # turn, enabling Anthropic/xAI cache hits from the second call.
        memory_content = (
            self.memory_manager.read("Judge") if self.memory_manager else ""
        )
        logger.debug(
            "Building judge system message for proposal %s with %d votes"
            " and %d discussions",
            proposal.proposal_id,
            len(votes),
            len(discussions),
        )
        system_msg = self._build_judge_system_message(
            rules=game_manager.rules_manager.rules,
            game_state=game_manager.game_state,
            proposal=proposal,
            votes=votes,
            discussions=discussions,
            memory_content=memory_content,
        )
        veto_prompt = self.prompt_builder.build_judge_veto_prompt(
            game_state=game_manager.game_state,
        )
        self.turn_history = [system_msg, veto_prompt]

        logger.debug(
            "Requesting veto decision from model %s",
            self.model_config.api_model_id,
        )

        max_veto_retries = self.tuning.max_judge_veto_retries
        try:
            data = llm_retry_loop(
                history=self.turn_history,
                api_client=self.api_client,
                parse_fn=parse_judge_veto_response,
                max_retries=max_veto_retries,
                retry_template=llm_prompts.JUDGE_VETO_RETRY_TEMPLATE,
                actor_label=self._judge_label,
                action_description="deciding on a veto",
                log_usage=lambda result: self._log_usage(result, "judge_veto"),
                secondary_append=self._judge_turn_responses,
            )
        except RuntimeError:
            logger.error(
                f"LLM Judge: Failed to generate valid veto decision after "
                f"{max_veto_retries} attempts."
            )
            raise RuntimeError(
                f"LLM Judge failed to generate a valid veto decision after "
                f"{max_veto_retries} attempts."
            )

        logger.info(
            "LLM Judge veto decision: %s | Reason: %s",
            "VETO" if data["veto"] else "ALLOW",
            data["reason"],
        )
        return {
            "veto": data["veto"],
            "reason": data["reason"],
            "private_thoughts": data["private_thoughts"],
        }

    def assess_scores(
        self,
        game_manager: "GameManager",
        players: list["BasePlayer"],
        proposal: "Proposal",
        votes: list["Vote"],
        discussions: list["Discussion"],
        proposal_passed: bool,
    ) -> JudgeScoreResponse:
        """Assess score adjustments using the accumulated turn history.

        The full turn context (rules, proposal, votes, discussions) is already
        in turn_history from get_veto, so only the score prompt is appended.
        This avoids re-sending the ruleset and enables cache hits from
        Anthropic/xAI on the system message prefix.
        """
        assert game_manager.game_state is not None
        assert game_manager.rules_manager is not None
        _ = players

        self._current_move_number = game_manager.game_state.move_number

        # Append only the score prompt to the shared turn history.
        # The full context (rules, proposal, votes, etc.) is already present
        # from get_veto's initialization.
        score_prompt = self.prompt_builder.build_judge_score_prompt(
            proposal_passed=proposal_passed
        )
        self.turn_history.append(score_prompt)

        logger.debug(
            "Requesting score assessment from model %s (proposal %s)",
            self.model_config.api_model_id,
            "PASSED" if proposal_passed else "FAILED",
        )

        max_score_retries = self.tuning.max_judge_score_retries
        valid_players = list(game_manager.game_state.scores.keys())
        try:
            data = llm_retry_loop(
                history=self.turn_history,
                api_client=self.api_client,
                parse_fn=lambda text: parse_judge_score_response(
                    text, valid_players=valid_players
                ),
                max_retries=max_score_retries,
                retry_template=llm_prompts.JUDGE_SCORE_RETRY_TEMPLATE,
                actor_label=self._judge_label,
                action_description="assessing scores",
                log_usage=lambda result: self._log_usage(
                    result, "judge_score"
                ),
                secondary_append=self._judge_turn_responses,
            )
        except RuntimeError:
            logger.error(
                f"LLM Judge: Failed to generate valid score assessment after "
                f"{max_score_retries} attempts."
            )
            raise RuntimeError(
                f"LLM Judge failed to generate a valid score assessment after "
                f"{max_score_retries} attempts."
            )

        adjustments = data["score_adjustments"]
        if not adjustments:
            logger.info("LLM Judge proposed no score changes this turn.")
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

    def maintain_state(
        self,
        game_manager: "GameManager",
        proposal: "Proposal",
        original_rule_text: str | None,
        new_rule_text: str | None,
    ) -> StateUpdates:
        """
        LLM-powered state maintenance that updates GameState when rules change.

        Uses the accumulated turn history so the LLM reasons with full context
        of earlier judge decisions (veto, scores). Only the maintain_state
        prompt is appended — the ruleset and proposal context are already in
        turn_history from get_veto. Includes retry logic for invalid
        responses.
        """
        assert game_manager.game_state is not None

        self._current_move_number = game_manager.game_state.move_number

        # Append only the maintain_state prompt to the shared turn history.
        # The full context is already present from get_veto's initialization.
        maintain_state_prompt = (
            self.prompt_builder.build_judge_maintain_state_prompt(
                proposal=proposal,
                original_rule_text=original_rule_text,
                new_rule_text=new_rule_text,
                game_state=game_manager.game_state,
            )
        )
        self.turn_history.append(maintain_state_prompt)

        logger.debug(
            "Requesting state maintenance decision from model %s for "
            "proposal %s",
            self.model_config.api_model_id,
            proposal.proposal_id,
        )

        max_maintain_state_retries = (
            self.tuning.max_judge_maintain_state_retries
        )
        try:
            data = llm_retry_loop(
                history=self.turn_history,
                api_client=self.api_client,
                parse_fn=parse_judge_maintain_state_response,
                max_retries=max_maintain_state_retries,
                retry_template=llm_prompts.JUDGE_MAINTAIN_STATE_RETRY_TEMPLATE,
                actor_label=self._judge_label,
                action_description="maintaining game state",
                log_usage=lambda result: self._log_usage(
                    result, "judge_maintain_state"
                ),
                secondary_append=self._judge_turn_responses,
            )
        except RuntimeError:
            logger.error(
                f"LLM Judge: Failed to generate valid maintain_state decision "
                f"after {max_maintain_state_retries} attempts."
            )
            raise RuntimeError(
                "LLM Judge failed to generate a valid maintain_state "
                f"decision after {max_maintain_state_retries} attempts."
            )

        # Build StateUpdates from parsed data
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

        return state_updates

    def update_memory(self) -> None:
        """Update the judge's persistent memory file after a completed turn.

        Sends turn_history (which already contains the cached system prefix,
        full context, and all judge reasoning) plus the memory update prompt.
        Since the system message in turn_history is byte-identical to the one
        used in get_veto, Anthropic returns a cache hit for the system prefix
        rather than incurring a fresh cache-write charge.

        This method is a no-op when ``memory_manager`` is ``None``.
        """
        if self.memory_manager is None:
            return

        logger.info(
            f"⚖️ Judge ({self.model_config.api_model_id}) is remembering..."
        )

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

        # Use accumulated turn history (system + full context + all judge
        # reasoning) plus the memory update prompt. The system message is
        # already cached from get_veto, so this call gets a cache hit rather
        # than paying to write a new ephemeral cache block.
        messages = self.turn_history + [
            ChatMessage(role="user", content=update_prompt)
        ]

        result = self.api_client.get_completion(
            messages, use_cache_control=False
        )
        self._log_usage(result, "memory_update")
        response = result.text

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
