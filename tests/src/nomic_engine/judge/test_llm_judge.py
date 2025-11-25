"""Unit tests for the LLMJudge strategy."""

from unittest.mock import Mock

import pytest

from src.nomic_engine.data_models import (
    ChatMessage,
    GameState,
    Rule,
    RuleStatus,
)
from src.nomic_engine.judge.llm_judge import LLMJudge


@pytest.fixture
def mock_game_manager():
    game_state = GameState(
        scores={"Alice": 0, "Bob": 0},
        current_player_name="Alice",
        move_number=1,
        turn_order=["Alice", "Bob"],
        next_proposal_id=1,
    )

    rules_manager = Mock()
    rules_manager.rules = [
        Rule(
            rule_id="1", text="Follow the rules.", status=RuleStatus.IMMUTABLE
        ),
    ]

    manager = Mock()
    manager.game_state = game_state
    manager.rules_manager = rules_manager
    return manager


def _dummy_messages() -> list[ChatMessage]:
    return [
        ChatMessage(role="system", content="sys"),
        ChatMessage(role="user", content="ctx"),
    ]


def test_get_veto_returns_bool(mock_game_manager):
    """LLMJudge should parse veto output and return the boolean decision."""

    prompt_builder = Mock()
    context_message = _dummy_messages()[1]
    prompt_builder.build_judge_context_message.return_value = context_message
    prompt_builder.build_judge_veto_prompt.return_value = ChatMessage(
        role="user", content="veto"
    )

    api_client = Mock()
    api_client.get_completion.return_value = (
        '{"private_thoughts":"x","veto":true,"reason":"conflict"}'
    )

    judge = LLMJudge(
        Mock(), prompt_builder=prompt_builder, api_client=api_client
    )

    decision = judge.get_veto(mock_game_manager, Mock(), [], [])

    assert decision["veto"] is True
    prompt_builder.build_judge_context_message.assert_called_once()
    api_client.get_completion.assert_called_once()


def test_assess_scores_applies_adjustments(mock_game_manager):
    """Score adjustments returned by the LLM should modify game state."""

    prompt_builder = Mock()
    context_message = _dummy_messages()[1]
    prompt_builder.build_judge_context_message.return_value = context_message
    prompt_builder.build_judge_score_prompt.return_value = ChatMessage(
        role="user", content="score"
    )

    api_client = Mock()
    api_client.get_completion.return_value = (
        '{"private_thoughts":"ok","score_adjustments":[{'
        '"player":"Alice","delta":2,"reason":"bonus"}]}'
    )

    judge = LLMJudge(
        Mock(), prompt_builder=prompt_builder, api_client=api_client
    )

    judge.assess_scores(mock_game_manager, [], Mock(), [], [])

    assert mock_game_manager.game_state.scores["Alice"] == 2
    prompt_builder.build_judge_context_message.assert_called_once()
    api_client.get_completion.assert_called_once()
