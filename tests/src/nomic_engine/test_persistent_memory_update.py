"""
Tests for Sprint 34 Task 3: Persistent Memory — Update Step.

Covers:
- LLMPlayer.update_memory()
- LLMJudge.update_memory()
- LLMJudge._judge_turn_responses accumulation (get_veto, assess_scores,
  maintain_state)
- GameLoop._reset_judge_turn_state()
- GameLoop._update_all_memories()
- GameLoop.run_turn() integration with memory update calls
"""

from __future__ import annotations

import logging
from unittest.mock import Mock, patch

import pytest

from src.nomic_engine.core.game_loop import GameLoop
from src.nomic_engine.core.game_manager import GameManager
from src.nomic_engine.data_models import (
    ChatMessage,
    CompletionResult,
    Discussion,
    GameState,
    ModelDefinition,
    Proposal,
    ProposalType,
    Rule,
    RuleStatus,
    Vote,
    WithdrawalPolicy,
)
from src.nomic_engine.judge.human_judge import HumanJudge
from src.nomic_engine.judge.llm_judge import LLMJudge
from src.nomic_engine.llm import prompts
from src.nomic_engine.players.base_player import BasePlayer
from src.nomic_engine.players.llm_player import LLMPlayer

# =====================================================================
# Shared Fixtures
# =====================================================================


@pytest.fixture
def model_config() -> ModelDefinition:
    return ModelDefinition(
        id="test-model",
        provider="local",
        api_model_id="http://localhost:11434",
        env_key_name=None,
    )


@pytest.fixture
def mock_memory_manager() -> Mock:
    mm = Mock()
    mm.max_characters = 5000
    return mm


@pytest.fixture
def mock_game_state() -> GameState:
    return GameState(
        scores={"Alice": 0, "Bob": 0},
        current_player_name="Alice",
        move_number=1,
        turn_order=["Alice", "Bob"],
        next_proposal_id=301,
    )


@pytest.fixture
def mock_rules() -> list[Rule]:
    return [
        Rule(
            rule_id="101",
            text="Immutable rule.",
            status=RuleStatus.IMMUTABLE,
        ),
        Rule(
            rule_id="201",
            text="Mutable rule.",
            status=RuleStatus.MUTABLE,
        ),
    ]


@pytest.fixture
def mock_game_manager(
    mock_game_state: GameState, mock_rules: list[Rule]
) -> Mock:
    manager = Mock(spec=GameManager)
    manager.game_state = mock_game_state

    rules_manager = Mock()
    rules_manager.rules = mock_rules
    rules_manager.apply_proposal = Mock()
    manager.rules_manager = rules_manager

    game_logger = Mock()
    game_logger.log_transcript = Mock()
    game_logger.log_event = Mock()
    manager.logger = game_logger

    manager.save_game_state = Mock()
    manager.save_rules = Mock()

    manager.game_config = Mock()
    manager.game_config.withdrawal_policy = WithdrawalPolicy.FORFEIT
    manager.game_config.max_withdrawal_retries = 2
    manager.game_config.retain_discusser_history_on_retry = False

    return manager


# =====================================================================
# Helpers
# =====================================================================


def _make_llm_player(
    model_config: ModelDefinition,
    player_name: str = "Alice",
    memory_manager: Mock | None = None,
) -> LLMPlayer:
    """Create an LLMPlayer with mocked internals for testing update_memory."""
    with (
        patch("src.nomic_engine.players.llm_player.create_api_client"),
        patch("src.nomic_engine.players.llm_player.PromptBuilder"),
    ):
        player = LLMPlayer(
            player_name, model_config, memory_manager=memory_manager
        )
        player.api_client = Mock()
        player.turn_history = [ChatMessage(role="system", content="context")]
        return player


def _make_llm_judge(memory_manager: Mock | None = None) -> LLMJudge:
    """Create an LLMJudge with mocked API client and prompt builder."""
    prompt_builder = Mock()
    prompt_builder.build_judge_context_block.return_value = "ctx"
    prompt_builder.build_judge_veto_prompt.return_value = ChatMessage(
        role="user", content="veto"
    )
    prompt_builder.build_judge_score_prompt.return_value = ChatMessage(
        role="user", content="score"
    )
    prompt_builder.build_judge_maintain_state_prompt.return_value = (
        ChatMessage(role="user", content="maintain")
    )
    api_client = Mock()
    return LLMJudge(
        Mock(),
        prompt_builder=prompt_builder,
        api_client=api_client,
        memory_manager=memory_manager,
    )


def _make_judge_game_manager() -> Mock:
    game_state = GameState(
        scores={"Alice": 0, "Bob": 0},
        current_player_name="Alice",
        move_number=1,
        turn_order=["Alice", "Bob"],
        next_proposal_id=1,
    )
    rules_manager = Mock()
    rules_manager.rules = [
        Rule(rule_id="1", text="Follow.", status=RuleStatus.IMMUTABLE)
    ]
    manager = Mock()
    manager.game_state = game_state
    manager.rules_manager = rules_manager
    return manager


def _simple_players(names: list[str]) -> list[Mock]:
    """Build plain Mock players that succeed through a full turn."""
    players = []
    for name in names:
        p = Mock()
        p.player_name = name
        p.propose = Mock(
            return_value=Proposal(
                proposer_name=name,
                move_number=1,
                type=ProposalType.ADD,
                new_text="New rule text.",
                rationale="A compelling reason.",
            )
        )
        p.begin_discussion_turn = Mock()
        p.discuss = Mock(
            return_value=Discussion(
                player_name=name,
                text=f"{name} discussion",
                private_thoughts=None,
            )
        )
        p.vote = Mock(
            return_value=Vote(player_name=name, vote="YES", reason="Agreed")
        )
        # revise: return the proposal unchanged (same object reference)
        p.revise = Mock(side_effect=lambda proposal, **kw: proposal)
        p.note_withdrawal_for_retry = Mock()
        p.on_proposal_updated = Mock()
        players.append(p)
    return players


# =====================================================================
# LLMPlayer.update_memory() Tests
# =====================================================================


class TestLLMPlayerUpdateMemory:
    """Tests for LLMPlayer.update_memory()."""

    def test_no_op_when_memory_manager_is_none(
        self, model_config: ModelDefinition
    ):
        """update_memory() is a no-op when memory_manager is None."""
        player = _make_llm_player(model_config, memory_manager=None)

        player.update_memory()

        player.api_client.get_completion.assert_not_called()

    def test_writes_response_when_long_enough(
        self,
        model_config: ModelDefinition,
        mock_memory_manager: Mock,
    ):
        """update_memory() writes to memory when response is ≥ 50 chars."""
        player = _make_llm_player(
            model_config, memory_manager=mock_memory_manager
        )
        long_response = "A" * 100
        player.api_client.get_completion.return_value = CompletionResult(
            text=long_response, raw_response=None, client_latency_ms=0
        )

        player.update_memory()

        mock_memory_manager.write.assert_called_once_with(
            "Alice", long_response
        )

    def test_does_not_write_when_response_too_short(
        self,
        model_config: ModelDefinition,
        mock_memory_manager: Mock,
    ):
        """update_memory() does not write when response < 50 chars."""
        player = _make_llm_player(
            model_config, memory_manager=mock_memory_manager
        )
        player.api_client.get_completion.return_value = CompletionResult(
            text="Short", raw_response=None, client_latency_ms=0
        )

        player.update_memory()

        mock_memory_manager.write.assert_not_called()

    def test_logs_warning_when_response_too_short(
        self,
        model_config: ModelDefinition,
        mock_memory_manager: Mock,
        caplog: pytest.LogCaptureFixture,
    ):
        """update_memory() logs a WARNING when response < 50 chars."""
        player = _make_llm_player(
            model_config, memory_manager=mock_memory_manager
        )
        player.api_client.get_completion.return_value = CompletionResult(
            text="Hi", raw_response=None, client_latency_ms=0
        )

        with caplog.at_level(logging.WARNING):
            player.update_memory()

        assert "too short" in caplog.text.lower()

    def test_does_not_write_when_api_returns_none(
        self,
        model_config: ModelDefinition,
        mock_memory_manager: Mock,
    ):
        """update_memory() does not write when the API returns None."""
        player = _make_llm_player(
            model_config, memory_manager=mock_memory_manager
        )
        player.api_client.get_completion.return_value = CompletionResult(
            text=None, raw_response=None, client_latency_ms=0
        )

        player.update_memory()

        mock_memory_manager.write.assert_not_called()

    def test_logs_warning_when_api_returns_none(
        self,
        model_config: ModelDefinition,
        mock_memory_manager: Mock,
        caplog: pytest.LogCaptureFixture,
    ):
        """update_memory() logs a WARNING when the API returns None."""
        player = _make_llm_player(
            model_config, memory_manager=mock_memory_manager
        )
        player.api_client.get_completion.return_value = CompletionResult(
            text=None, raw_response=None, client_latency_ms=0
        )

        with caplog.at_level(logging.WARNING):
            player.update_memory()

        assert "api call failed" in caplog.text.lower()

    def test_appends_update_prompt_to_turn_history_before_api_call(
        self,
        model_config: ModelDefinition,
        mock_memory_manager: Mock,
    ):
        """With a character limit, prompt includes the limit number."""
        player = _make_llm_player(
            model_config, memory_manager=mock_memory_manager
        )
        initial_len = len(player.turn_history)

        captured: list[list[ChatMessage]] = []

        def capture_and_return(
            messages: list[ChatMessage],
        ) -> CompletionResult:
            captured.append(list(messages))
            return CompletionResult(
                text="A" * 100, raw_response=None, client_latency_ms=0
            )

        player.api_client.get_completion.side_effect = capture_and_return

        player.update_memory()

        assert len(captured) == 1
        sent = captured[0]
        # The prompt was the last message sent to the API
        assert len(sent) == initial_len + 1
        last_sent = sent[-1]
        assert last_sent.role == "user"
        assert str(mock_memory_manager.max_characters) in last_sent.content

        # turn_history was mutated in place
        assert len(player.turn_history) == initial_len + 1
        appended = player.turn_history[-1]
        assert appended.role == "user"
        assert str(mock_memory_manager.max_characters) in appended.content

    def test_update_prompt_omits_limit_when_no_max_characters(
        self,
        model_config: ModelDefinition,
    ):
        """Without a character limit, prompt has no truncation clause."""
        mm = Mock()
        mm.max_characters = 0
        player = _make_llm_player(model_config, memory_manager=mm)
        player.api_client.get_completion.return_value = CompletionResult(
            text="A" * 100, raw_response=None, client_latency_ms=0
        )

        player.update_memory()

        last_msg = player.turn_history[-1]
        assert "character limit" not in last_msg.content.lower()
        assert "truncated" not in last_msg.content.lower()

    def test_appended_message_contains_memory_update_prompt_text(
        self,
        model_config: ModelDefinition,
        mock_memory_manager: Mock,
    ):
        """The appended message contains the MEMORY_UPDATE_PROMPT lead-in."""
        player = _make_llm_player(
            model_config, memory_manager=mock_memory_manager
        )
        player.api_client.get_completion.return_value = CompletionResult(
            text="A" * 100, raw_response=None, client_latency_ms=0
        )

        player.update_memory()

        last_msg = player.turn_history[-1]
        assert "update your private memory" in last_msg.content.lower()

    def test_short_check_uses_stripped_length(
        self,
        model_config: ModelDefinition,
        mock_memory_manager: Mock,
    ):
        """The ≥ 50 threshold is applied after stripping whitespace."""
        player = _make_llm_player(
            model_config, memory_manager=mock_memory_manager
        )
        # 49 real chars padded with spaces → stripped length 49 < 50
        player.api_client.get_completion.return_value = CompletionResult(
            text="  " + "X" * 49 + "  ",
            raw_response=None,
            client_latency_ms=0,
        )

        player.update_memory()

        mock_memory_manager.write.assert_not_called()

    def test_exactly_50_chars_stripped_is_accepted(
        self,
        model_config: ModelDefinition,
        mock_memory_manager: Mock,
    ):
        """update_memory() writes when the stripped response is exactly 50."""
        player = _make_llm_player(
            model_config, memory_manager=mock_memory_manager
        )
        response = "B" * 50
        player.api_client.get_completion.return_value = CompletionResult(
            text=response, raw_response=None, client_latency_ms=0
        )

        player.update_memory()

        mock_memory_manager.write.assert_called_once_with("Alice", response)


# =====================================================================
# LLMJudge._judge_turn_responses accumulation Tests
# =====================================================================


class TestLLMJudgeTurnResponses:
    """Tests that _judge_turn_responses is accumulated correctly."""

    def test_appends_after_successful_get_veto(self):
        """Appends to _judge_turn_responses after successful get_veto."""
        veto_text = '{"private_thoughts":"x","veto":false,"reason":"ok"}'
        judge = _make_llm_judge()
        judge.api_client.get_completion.return_value = CompletionResult(
            text=veto_text, raw_response=None, client_latency_ms=0
        )
        gm = _make_judge_game_manager()

        assert len(judge._judge_turn_responses) == 0

        judge.get_veto(gm, Mock(), [], [])

        assert len(judge._judge_turn_responses) == 1
        assert judge._judge_turn_responses[0].role == "assistant"
        assert judge._judge_turn_responses[0].content == veto_text

    def test_does_not_append_on_failed_get_veto(self):
        """Does not append to _judge_turn_responses when get_veto fails."""
        judge = _make_llm_judge()
        judge.api_client.get_completion.return_value = CompletionResult(
            text="not json", raw_response=None, client_latency_ms=0
        )
        judge.tuning.max_judge_veto_retries = 1
        gm = _make_judge_game_manager()

        with pytest.raises(RuntimeError):
            judge.get_veto(gm, Mock(), [], [])

        assert len(judge._judge_turn_responses) == 0

    def test_appends_after_successful_assess_scores(self):
        """Appends to _judge_turn_responses after successful assess_scores."""
        score_text = '{"private_thoughts":"ok","score_adjustments":[]}'
        judge = _make_llm_judge()
        # Simulate state after get_veto ran by initializing _turn_history
        judge._turn_history = [
            ChatMessage(role="system", content="sys"),
            ChatMessage(role="user", content="ctx"),
        ]
        judge.api_client.get_completion.return_value = CompletionResult(
            text=score_text, raw_response=None, client_latency_ms=0
        )
        gm = _make_judge_game_manager()

        judge.assess_scores(gm, [], Mock(), [], [], proposal_passed=True)

        assert len(judge._judge_turn_responses) == 1
        assert judge._judge_turn_responses[0].content == score_text

    def test_appends_after_successful_maintain_state(self):
        """Appends to _judge_turn_responses after successful maintain_state."""
        state_text = (
            '{"private_thoughts":"none","flags":{},"target_score":null}'
        )
        judge = _make_llm_judge()
        # Simulate state after get_veto ran by initializing _turn_history
        judge._turn_history = [
            ChatMessage(role="system", content="sys"),
            ChatMessage(role="user", content="ctx"),
        ]
        judge.api_client.get_completion.return_value = CompletionResult(
            text=state_text, raw_response=None, client_latency_ms=0
        )
        gm = _make_judge_game_manager()

        judge.maintain_state(gm, Mock(), None, None)

        assert len(judge._judge_turn_responses) == 1
        assert judge._judge_turn_responses[0].content == state_text

    def test_accumulates_across_all_three_judge_methods(self):
        """_judge_turn_responses accumulates across all three judge methods."""
        veto_text = '{"private_thoughts":"v","veto":false,"reason":"ok"}'
        score_text = '{"private_thoughts":"s","score_adjustments":[]}'
        state_text = '{"private_thoughts":"n","flags":{},"target_score":null}'

        judge = _make_llm_judge()
        judge.api_client.get_completion.side_effect = [
            CompletionResult(
                text=veto_text, raw_response=None, client_latency_ms=0
            ),
            CompletionResult(
                text=score_text, raw_response=None, client_latency_ms=0
            ),
            CompletionResult(
                text=state_text, raw_response=None, client_latency_ms=0
            ),
        ]
        gm = _make_judge_game_manager()

        judge.get_veto(gm, Mock(), [], [])
        judge.assess_scores(gm, [], Mock(), [], [], proposal_passed=True)
        judge.maintain_state(gm, Mock(), None, None)

        assert len(judge._judge_turn_responses) == 3
        assert judge._judge_turn_responses[0].content == veto_text
        assert judge._judge_turn_responses[1].content == score_text
        assert judge._judge_turn_responses[2].content == state_text

    def test_turn_history_grows_across_all_three_judge_methods(self):
        """_turn_history accumulates across get_veto, assess_scores, and
        maintain_state — each appending its prompt and response.

        After the amendment the system message embeds the full turn
        context, so get_veto produces [system_with_ctx, veto_prompt,
        veto_response] = 3 items instead of 4.
        """
        veto_text = '{"private_thoughts":"v","veto":false,"reason":"ok"}'
        score_text = '{"private_thoughts":"s","score_adjustments":[]}'
        state_text = '{"private_thoughts":"n","flags":{},"target_score":null}'

        judge = _make_llm_judge()
        judge.api_client.get_completion.side_effect = [
            CompletionResult(
                text=veto_text, raw_response=None, client_latency_ms=0
            ),
            CompletionResult(
                text=score_text, raw_response=None, client_latency_ms=0
            ),
            CompletionResult(
                text=state_text, raw_response=None, client_latency_ms=0
            ),
        ]
        gm = _make_judge_game_manager()

        judge.get_veto(gm, Mock(), [], [])
        # After get_veto: [system_with_ctx, veto_prompt, veto_response]
        assert len(judge._turn_history) == 3

        judge.assess_scores(gm, [], Mock(), [], [], proposal_passed=True)
        # After assess_scores: [..., score_prompt, score_response]
        assert len(judge._turn_history) == 5

        judge.maintain_state(gm, Mock(), None, None)
        # After maintain_state: [..., maintain_prompt, maintain_response]
        assert len(judge._turn_history) == 7

        # Verify roles at known positions
        assert judge._turn_history[0].role == "system"  # system+context
        assert judge._turn_history[1].role == "user"  # veto prompt
        assert judge._turn_history[2].role == "assistant"  # veto response
        assert judge._turn_history[3].role == "user"  # score prompt
        assert judge._turn_history[4].role == "assistant"  # score response
        assert judge._turn_history[5].role == "user"  # maintain prompt
        assert judge._turn_history[6].role == "assistant"  # maintain response

        # Content is correct
        assert judge._turn_history[2].content == veto_text
        assert judge._turn_history[4].content == score_text
        assert judge._turn_history[6].content == state_text


# =====================================================================
# LLMJudge.update_memory() Tests
# =====================================================================


class TestLLMJudgeUpdateMemory:
    """Tests for LLMJudge.update_memory()."""

    def _make_judge_with_turn_history(
        self,
        memory_manager: Mock | None = None,
    ) -> tuple["LLMJudge", list[ChatMessage]]:
        """Create an LLMJudge whose _turn_history simulates a completed
        get_veto sequence.

        After the amendment the system message embeds the full turn
        context, so history is [system_with_ctx, veto_prompt, veto_resp]
        — 3 items instead of 4.

        Returns the judge and the list of history messages so tests can
        assert on their positions in the sent message list.
        """
        judge = _make_llm_judge(memory_manager=memory_manager)
        sys_msg = ChatMessage(
            role="system",
            content=prompts.JUDGE_SYSTEM_PROMPT + "\n\nturn context",
        )
        veto_prompt = ChatMessage(role="user", content="veto prompt")
        veto_resp = ChatMessage(role="assistant", content="veto response")
        history = [sys_msg, veto_prompt, veto_resp]
        judge._turn_history = history
        judge._judge_turn_responses = [veto_resp]
        return judge, history

    def test_no_op_when_memory_manager_is_none(self):
        """update_memory() is a no-op when memory_manager is None."""
        judge, _ = self._make_judge_with_turn_history(memory_manager=None)

        judge.update_memory()

        judge.api_client.get_completion.assert_not_called()

    def test_skips_when_judge_turn_responses_empty(
        self, caplog: pytest.LogCaptureFixture
    ):
        """Skips and logs a WARNING when _judge_turn_responses is empty."""
        mm = Mock()
        mm.max_characters = 5000
        judge = _make_llm_judge(memory_manager=mm)
        judge._judge_turn_responses = []
        judge._turn_history = [
            ChatMessage(role="system", content="sys"),
        ]

        with caplog.at_level(logging.WARNING):
            judge.update_memory()

        mm.write.assert_not_called()
        judge.api_client.get_completion.assert_not_called()
        assert "no turn responses cached" in caplog.text.lower()

    def test_writes_with_judge_key(self):
        """update_memory() persists memory using the key 'Judge'."""
        mm = Mock()
        mm.max_characters = 5000
        judge, _ = self._make_judge_with_turn_history(memory_manager=mm)
        long_response = "G" * 100
        judge.api_client.get_completion.return_value = CompletionResult(
            text=long_response, raw_response=None, client_latency_ms=0
        )

        judge.update_memory()

        mm.write.assert_called_once_with("Judge", long_response)

    def test_does_not_write_when_api_returns_none(self):
        """update_memory() does not write when the API returns None."""
        mm = Mock()
        mm.max_characters = 5000
        judge, _ = self._make_judge_with_turn_history(memory_manager=mm)
        judge.api_client.get_completion.return_value = CompletionResult(
            text=None, raw_response=None, client_latency_ms=0
        )

        judge.update_memory()

        mm.write.assert_not_called()

    def test_logs_warning_when_api_returns_none(
        self, caplog: pytest.LogCaptureFixture
    ):
        """update_memory() logs a WARNING when the API returns None."""
        mm = Mock()
        mm.max_characters = 5000
        judge, _ = self._make_judge_with_turn_history(memory_manager=mm)
        judge.api_client.get_completion.return_value = CompletionResult(
            text=None, raw_response=None, client_latency_ms=0
        )

        with caplog.at_level(logging.WARNING):
            judge.update_memory()

        assert "api call failed" in caplog.text.lower()

    def test_does_not_write_when_response_too_short(self):
        """update_memory() does not write when response < 50 chars."""
        mm = Mock()
        mm.max_characters = 5000
        judge, _ = self._make_judge_with_turn_history(memory_manager=mm)
        judge.api_client.get_completion.return_value = CompletionResult(
            text="Too short", raw_response=None, client_latency_ms=0
        )

        judge.update_memory()

        mm.write.assert_not_called()

    def test_logs_warning_when_response_too_short(
        self, caplog: pytest.LogCaptureFixture
    ):
        """update_memory() logs a WARNING when response < 50 chars."""
        mm = Mock()
        mm.max_characters = 5000
        judge, _ = self._make_judge_with_turn_history(memory_manager=mm)
        judge.api_client.get_completion.return_value = CompletionResult(
            text="Hi", raw_response=None, client_latency_ms=0
        )

        with caplog.at_level(logging.WARNING):
            judge.update_memory()

        assert "too short" in caplog.text.lower()

    def test_builds_messages_from_turn_history_and_prompt(self):
        """Sends _turn_history + [update_prompt] to the API.

        The new architecture reuses _turn_history (which already has the
        stable system prefix and all accumulated judge reasoning) plus the
        memory update prompt, rather than building a fresh [system, responses,
        prompt] list. This ensures the Anthropic system-message cache is a hit
        rather than incurring a fresh cache-write charge.
        """
        mm = Mock()
        mm.max_characters = 5000
        judge, history = self._make_judge_with_turn_history(memory_manager=mm)
        judge.api_client.get_completion.return_value = CompletionResult(
            text="H" * 100, raw_response=None, client_latency_ms=0
        )

        judge.update_memory()

        judge.api_client.get_completion.assert_called_once()
        messages: list[ChatMessage] = (
            judge.api_client.get_completion.call_args[0][0]
        )

        # _turn_history (3 msgs) + update_prompt = 4 messages
        assert len(messages) == len(history) + 1
        for i, hist_msg in enumerate(history):
            assert messages[i] is hist_msg
        assert messages[-1].role == "user"
        assert "update your private memory" in messages[-1].content.lower()

    def test_builds_messages_with_full_judge_reasoning(self):
        """update_memory includes all accumulated judge reasoning.

        After the amendment the turn context is embedded in the system
        message, so there is no separate context user message. History
        has 7 items (was 8) and the total sent is 8 (was 9).
        """
        mm = Mock()
        mm.max_characters = 5000
        judge = _make_llm_judge(memory_manager=mm)

        # Set up turn history that includes all three judge interactions.
        # System message now embeds the full turn context.
        sys_msg = ChatMessage(
            role="system",
            content=prompts.JUDGE_SYSTEM_PROMPT + "\n\ncontext",
        )
        veto_p = ChatMessage(role="user", content="veto prompt")
        veto_r = ChatMessage(role="assistant", content="Veto reasoning")
        score_p = ChatMessage(role="user", content="score prompt")
        score_r = ChatMessage(role="assistant", content="Score reasoning")
        state_p = ChatMessage(role="user", content="maintain prompt")
        state_r = ChatMessage(role="assistant", content="State reasoning")
        history = [
            sys_msg,
            veto_p,
            veto_r,
            score_p,
            score_r,
            state_p,
            state_r,
        ]
        judge._turn_history = history
        judge._judge_turn_responses = [veto_r, score_r, state_r]
        judge.api_client.get_completion.return_value = CompletionResult(
            text="I" * 100, raw_response=None, client_latency_ms=0
        )

        judge.update_memory()

        messages: list[ChatMessage] = (
            judge.api_client.get_completion.call_args[0][0]
        )
        # 7 history messages + update_prompt = 8
        assert len(messages) == 8
        assert messages[0] is sys_msg
        assert messages[0].role == "system"
        assert messages[2] is veto_r
        assert messages[4] is score_r
        assert messages[6] is state_r
        assert messages[7].role == "user"

    def test_update_prompt_omits_limit_when_no_max_characters(self):
        """Without a character limit, prompt has no truncation clause."""
        mm = Mock()
        mm.max_characters = 0
        judge, _ = self._make_judge_with_turn_history(memory_manager=mm)
        judge.api_client.get_completion.return_value = CompletionResult(
            text="J" * 100, raw_response=None, client_latency_ms=0
        )

        judge.update_memory()

        messages: list[ChatMessage] = (
            judge.api_client.get_completion.call_args[0][0]
        )
        update_msg = messages[-1]
        assert "character limit" not in update_msg.content.lower()
        assert "truncated" not in update_msg.content.lower()


# =====================================================================
# GameLoop._reset_judge_turn_state() Tests
# =====================================================================


class TestGameLoopResetJudgeTurnState:
    """Tests for GameLoop._reset_judge_turn_state()."""

    def test_clears_judge_turn_responses_on_llm_judge(
        self, mock_game_manager: Mock
    ):
        """Empties _judge_turn_responses on an LLMJudge."""
        judge = LLMJudge(Mock(), api_client=Mock())
        judge._judge_turn_responses = [
            ChatMessage(role="assistant", content="Old response")
        ]

        game_loop = GameLoop(
            game_manager=mock_game_manager, players=[], judge=judge
        )
        game_loop._reset_judge_turn_state()

        assert judge._judge_turn_responses == []

    def test_clears_turn_history_on_llm_judge(self, mock_game_manager: Mock):
        """Empties _turn_history on an LLMJudge at turn reset."""
        judge = LLMJudge(Mock(), api_client=Mock())
        judge._turn_history = [
            ChatMessage(role="system", content="Old system"),
            ChatMessage(role="user", content="Old context"),
            ChatMessage(role="assistant", content="Old veto response"),
        ]

        game_loop = GameLoop(
            game_manager=mock_game_manager, players=[], judge=judge
        )
        game_loop._reset_judge_turn_state()

        assert judge._turn_history == []

    def test_clears_both_accumulators_together(self, mock_game_manager: Mock):
        """_reset_judge_turn_state clears both _judge_turn_responses and
        _turn_history in a single call."""
        judge = LLMJudge(Mock(), api_client=Mock())
        judge._judge_turn_responses = [
            ChatMessage(role="assistant", content="Response")
        ]
        judge._turn_history = [
            ChatMessage(role="system", content="System"),
            ChatMessage(role="user", content="Context"),
        ]

        game_loop = GameLoop(
            game_manager=mock_game_manager, players=[], judge=judge
        )
        game_loop._reset_judge_turn_state()

        assert judge._judge_turn_responses == []
        assert judge._turn_history == []

    def test_no_op_on_human_judge(self, mock_game_manager: Mock):
        """Does not raise and is a no-op for a HumanJudge."""
        judge = HumanJudge()
        game_loop = GameLoop(
            game_manager=mock_game_manager, players=[], judge=judge
        )

        game_loop._reset_judge_turn_state()  # should not raise


# =====================================================================
# GameLoop._update_all_memories() Tests
# =====================================================================


class TestGameLoopUpdateAllMemories:
    """Tests for GameLoop._update_all_memories()."""

    def test_calls_update_memory_on_llm_players(self, mock_game_manager: Mock):
        """Calls update_memory() on every LLM player."""
        llm_a = Mock(spec=LLMPlayer)
        llm_a.player_name = "Alice"
        llm_b = Mock(spec=LLMPlayer)
        llm_b.player_name = "Bob"

        game_loop = GameLoop(
            game_manager=mock_game_manager, players=[llm_a, llm_b]
        )
        game_loop._update_all_memories()

        llm_a.update_memory.assert_called_once()
        llm_b.update_memory.assert_called_once()

    def test_skips_human_players(self, mock_game_manager: Mock):
        """Does not call update_memory() on non-LLM players."""
        human = Mock(spec=BasePlayer)
        human.player_name = "Charlie"
        llm = Mock(spec=LLMPlayer)
        llm.player_name = "Alice"

        game_loop = GameLoop(
            game_manager=mock_game_manager, players=[human, llm]
        )
        game_loop._update_all_memories()

        llm.update_memory.assert_called_once()
        # BasePlayer has no update_memory; the method is never reached.
        # Verify that only the LLM player was called (call_count == 1 above).
        assert llm.update_memory.call_count == 1

    def test_calls_update_memory_on_llm_judge(self, mock_game_manager: Mock):
        """Calls update_memory() on an LLMJudge."""
        llm_judge = Mock(spec=LLMJudge)
        llm_judge._judge_turn_responses = []

        game_loop = GameLoop(
            game_manager=mock_game_manager, players=[], judge=llm_judge
        )
        game_loop._update_all_memories()

        llm_judge.update_memory.assert_called_once()

    def test_skips_human_judge(self, mock_game_manager: Mock):
        """Does not raise and is a no-op for a HumanJudge."""
        judge = HumanJudge()
        game_loop = GameLoop(
            game_manager=mock_game_manager, players=[], judge=judge
        )

        game_loop._update_all_memories()  # should not raise


# =====================================================================
# GameLoop.run_turn() Memory Integration Tests
# =====================================================================


class TestGameLoopRunTurnMemoryIntegration:
    """run_turn() calls memory helpers at the correct exit points."""

    def test_calls_reset_judge_turn_state_at_start(
        self, mock_game_manager: Mock
    ):
        """run_turn() calls _reset_judge_turn_state() before any turn logic."""
        players = _simple_players(["Alice", "Bob"])
        game_loop = GameLoop(game_manager=mock_game_manager, players=players)
        game_loop._reset_judge_turn_state = Mock()
        game_loop._update_all_memories = Mock()

        with patch.object(game_loop, "_resolve_turn", return_value=False):
            game_loop.run_turn()

        game_loop._reset_judge_turn_state.assert_called_once()

    def test_calls_update_all_memories_after_resolve_turn(
        self, mock_game_manager: Mock
    ):
        """run_turn() calls _update_all_memories() after _resolve_turn."""
        players = _simple_players(["Alice", "Bob"])
        game_loop = GameLoop(game_manager=mock_game_manager, players=players)
        game_loop._reset_judge_turn_state = Mock()
        game_loop._update_all_memories = Mock()

        with patch.object(game_loop, "_resolve_turn", return_value=False):
            game_loop.run_turn()

        game_loop._update_all_memories.assert_called_once()

    def test_calls_update_all_memories_on_game_over_turn(
        self, mock_game_manager: Mock
    ):
        """run_turn() calls _update_all_memories() even on game-over turns."""
        players = _simple_players(["Alice", "Bob"])
        game_loop = GameLoop(game_manager=mock_game_manager, players=players)
        game_loop._reset_judge_turn_state = Mock()
        game_loop._update_all_memories = Mock()

        with patch.object(game_loop, "_resolve_turn", return_value=True):
            result = game_loop.run_turn()

        assert result is True
        game_loop._update_all_memories.assert_called_once()

    def test_calls_update_all_memories_on_forfeit(
        self,
        mock_game_manager: Mock,
        mock_game_state: GameState,
    ):
        """Calls _update_all_memories() on withdrawal under FORFEIT."""
        players = _simple_players(["Alice", "Bob"])
        players[0].revise = Mock(return_value=None)  # Alice withdraws

        game_loop = GameLoop(game_manager=mock_game_manager, players=players)
        game_loop._reset_judge_turn_state = Mock()
        game_loop._update_all_memories = Mock()

        game_loop.run_turn()

        game_loop._update_all_memories.assert_called_once()

    def test_calls_update_all_memories_on_retry_policy_exhausted(
        self,
        mock_game_manager: Mock,
        mock_game_state: GameState,
    ):
        """Calls _update_all_memories() when RETRY retries are exhausted."""
        mock_game_manager.game_config.withdrawal_policy = (
            WithdrawalPolicy.RETRY
        )
        mock_game_manager.game_config.max_withdrawal_retries = 1

        players = _simple_players(["Alice", "Bob"])
        players[0].revise = Mock(return_value=None)  # always withdraws
        players[0].propose.side_effect = [
            Proposal(
                proposer_name="Alice",
                move_number=1,
                type=ProposalType.ADD,
                new_text="Attempt one.",
                rationale="First try.",
            ),
            Proposal(
                proposer_name="Alice",
                move_number=1,
                type=ProposalType.ADD,
                new_text="Attempt two.",
                rationale="Second try.",
            ),
        ]

        game_loop = GameLoop(game_manager=mock_game_manager, players=players)
        game_loop._reset_judge_turn_state = Mock()
        game_loop._update_all_memories = Mock()

        game_loop.run_turn()

        game_loop._update_all_memories.assert_called_once()

    def test_does_not_call_update_all_memories_on_illegal_proposal(
        self, mock_game_manager: Mock
    ):
        """Does NOT call _update_all_memories() on illegal-proposal exit."""
        players = _simple_players(["Alice", "Bob"])
        # AMEND immutable rule 101 — illegal per mock_rules fixture
        players[0].propose = Mock(
            return_value=Proposal(
                proposer_name="Alice",
                move_number=1,
                type=ProposalType.AMEND,
                target_rule_id="101",
                new_text="Attempting to amend an immutable rule.",
            )
        )

        game_loop = GameLoop(game_manager=mock_game_manager, players=players)
        game_loop._reset_judge_turn_state = Mock()
        game_loop._update_all_memories = Mock()

        game_loop.run_turn()

        game_loop._update_all_memories.assert_not_called()


# =====================================================================
# LLMPlayer.update_memory() — judge_turn_outputs & INFO log Tests
# =====================================================================


class TestLLMPlayerUpdateMemoryJudgeOutputs:
    """Tests for Bug 1 & Bug 2 fixes in LLMPlayer.update_memory()."""

    def test_includes_judge_outputs_in_messages_when_provided(
        self,
        model_config: ModelDefinition,
        mock_memory_manager: Mock,
    ):
        """Messages sent to the API include judge block when provided."""
        player = _make_llm_player(
            model_config, memory_manager=mock_memory_manager
        )
        initial_len = len(player.turn_history)

        judge_responses = [
            ChatMessage(role="assistant", content="Veto: allowed."),
            ChatMessage(role="assistant", content="Score: +1 Alice."),
        ]

        captured: list[list[ChatMessage]] = []

        def capture_and_return(
            messages: list[ChatMessage],
        ) -> CompletionResult:
            captured.append(list(messages))
            return CompletionResult(
                text="A" * 100, raw_response=None, client_latency_ms=0
            )

        player.api_client.get_completion.side_effect = capture_and_return

        player.update_memory(judge_turn_outputs=judge_responses)

        assert len(captured) == 1
        sent = captured[0]
        # turn_history + judge block + memory update prompt
        assert len(sent) == initial_len + 2

        judge_msg = sent[initial_len]
        assert judge_msg.role == "user"
        assert "=== JUDGE ACTIONS THIS TURN ===" in judge_msg.content
        assert "Veto: allowed." in judge_msg.content
        assert "Score: +1 Alice." in judge_msg.content
        assert "=== END JUDGE ACTIONS ===" in judge_msg.content

    def test_omits_judge_block_when_judge_turn_outputs_is_none(
        self,
        model_config: ModelDefinition,
        mock_memory_manager: Mock,
    ):
        """Judge block is absent when judge_turn_outputs is None."""
        player = _make_llm_player(
            model_config, memory_manager=mock_memory_manager
        )
        initial_len = len(player.turn_history)

        captured: list[list[ChatMessage]] = []

        def capture_and_return(
            messages: list[ChatMessage],
        ) -> CompletionResult:
            captured.append(list(messages))
            return CompletionResult(
                text="A" * 100, raw_response=None, client_latency_ms=0
            )

        player.api_client.get_completion.side_effect = capture_and_return

        player.update_memory(judge_turn_outputs=None)

        assert len(captured) == 1
        sent = captured[0]
        assert len(sent) == initial_len + 1
        assert "JUDGE ACTIONS" not in sent[-1].content

    def test_omits_judge_block_when_judge_turn_outputs_is_empty(
        self,
        model_config: ModelDefinition,
        mock_memory_manager: Mock,
    ):
        """Judge block is absent when judge_turn_outputs is an empty list."""
        player = _make_llm_player(
            model_config, memory_manager=mock_memory_manager
        )
        initial_len = len(player.turn_history)

        captured: list[list[ChatMessage]] = []

        def capture_and_return(
            messages: list[ChatMessage],
        ) -> CompletionResult:
            captured.append(list(messages))
            return CompletionResult(
                text="A" * 100, raw_response=None, client_latency_ms=0
            )

        player.api_client.get_completion.side_effect = capture_and_return

        player.update_memory(judge_turn_outputs=[])

        assert len(captured) == 1
        sent = captured[0]
        assert len(sent) == initial_len + 1
        assert "JUDGE ACTIONS" not in sent[-1].content

    def test_logs_info_with_player_name_personality_and_model_id(
        self,
        model_config: ModelDefinition,
        mock_memory_manager: Mock,
        caplog: pytest.LogCaptureFixture,
    ):
        """update_memory() logs INFO with name, personality, model ID."""
        player = _make_llm_player(
            model_config,
            player_name="Max",
            memory_manager=mock_memory_manager,
        )
        player.personality = "machiavellian"
        player.model_config = ModelDefinition(
            id="test-model",
            provider="local",
            api_model_id="grok-4-1-fast",
            env_key_name=None,
        )
        player.api_client.get_completion.return_value = CompletionResult(
            text="A" * 100, raw_response=None, client_latency_ms=0
        )

        with caplog.at_level(logging.INFO):
            player.update_memory()

        assert "Max" in caplog.text
        assert "machiavellian" in caplog.text.lower()
        assert "grok-4-1-fast" in caplog.text
        assert "remembering" in caplog.text.lower()

    def test_judge_responses_separated_by_blank_line(
        self,
        model_config: ModelDefinition,
        mock_memory_manager: Mock,
    ):
        """Multiple judge responses are separated by a blank line."""
        player = _make_llm_player(
            model_config, memory_manager=mock_memory_manager
        )
        judge_responses = [
            ChatMessage(role="assistant", content="Response A"),
            ChatMessage(role="assistant", content="Response B"),
        ]

        captured: list[list[ChatMessage]] = []

        def capture_and_return(
            messages: list[ChatMessage],
        ) -> CompletionResult:
            captured.append(list(messages))
            return CompletionResult(
                text="A" * 100, raw_response=None, client_latency_ms=0
            )

        player.api_client.get_completion.side_effect = capture_and_return

        player.update_memory(judge_turn_outputs=judge_responses)

        judge_msg = captured[0][len(player.turn_history) - 2]
        assert "Response A\n\nResponse B" in judge_msg.content


# =====================================================================
# LLMJudge.update_memory() — INFO log Tests
# =====================================================================


class TestLLMJudgeUpdateMemoryInfoLog:
    """Tests for Bug 2 fix in LLMJudge.update_memory()."""

    def test_logs_info_with_model_id(self, caplog: pytest.LogCaptureFixture):
        """update_memory() logs INFO with model ID before API call."""
        mm = Mock()
        mm.max_characters = 5000
        judge = _make_llm_judge(memory_manager=mm)
        judge.model_config = ModelDefinition(
            id="test-judge",
            provider="anthropic",
            api_model_id="claude-sonnet-4-5",
            env_key_name=None,
        )
        judge._judge_turn_responses = [
            ChatMessage(role="assistant", content="Some reasoning.")
        ]
        judge.api_client.get_completion.return_value = CompletionResult(
            text="G" * 100, raw_response=None, client_latency_ms=0
        )

        with caplog.at_level(logging.INFO):
            judge.update_memory()

        assert "claude-sonnet-4-5" in caplog.text
        assert "remembering" in caplog.text.lower()


# =====================================================================
# GameLoop._update_all_memories() — judge_turn_outputs passing Tests
# =====================================================================


class TestGameLoopUpdateAllMemoriesJudgeOutputs:
    """Tests for judge output passing in GameLoop._update_all_memories()."""

    def test_passes_judge_turn_responses_when_llm_judge(
        self, mock_game_manager: Mock
    ):
        """Passes _judge_turn_responses to players when judge is LLMJudge."""
        llm_a = Mock(spec=LLMPlayer)
        llm_a.player_name = "Alice"
        llm_b = Mock(spec=LLMPlayer)
        llm_b.player_name = "Bob"

        judge_responses = [
            ChatMessage(role="assistant", content="Judge output.")
        ]
        judge = Mock(spec=LLMJudge)
        judge._judge_turn_responses = judge_responses

        game_loop = GameLoop(
            game_manager=mock_game_manager,
            players=[llm_a, llm_b],
            judge=judge,
        )
        game_loop._update_all_memories()

        llm_a.update_memory.assert_called_once_with(
            judge_turn_outputs=judge_responses
        )
        llm_b.update_memory.assert_called_once_with(
            judge_turn_outputs=judge_responses
        )

    def test_passes_none_when_judge_is_not_llm_judge(
        self, mock_game_manager: Mock
    ):
        """Passes None to each player's update_memory for HumanJudge."""
        llm_a = Mock(spec=LLMPlayer)
        llm_a.player_name = "Alice"

        judge = HumanJudge()

        game_loop = GameLoop(
            game_manager=mock_game_manager,
            players=[llm_a],
            judge=judge,
        )
        game_loop._update_all_memories()

        llm_a.update_memory.assert_called_once_with(judge_turn_outputs=None)

    def test_passes_none_when_no_judge(self, mock_game_manager: Mock):
        """Passes None to each player's update_memory with no judge."""
        llm_a = Mock(spec=LLMPlayer)
        llm_a.player_name = "Alice"

        game_loop = GameLoop(
            game_manager=mock_game_manager,
            players=[llm_a],
        )
        game_loop._update_all_memories()

        llm_a.update_memory.assert_called_once_with(judge_turn_outputs=None)
