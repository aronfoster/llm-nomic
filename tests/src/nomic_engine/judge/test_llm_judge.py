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
    prompt_builder.build_judge_score_context_message.return_value = (
        context_message
    )
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


def test_assess_scores_returns_adjustments_without_mutation(mock_game_manager):
    """Score adjustments returned by the LLM should be side-effect free."""

    prompt_builder = Mock()
    context_message = _dummy_messages()[1]
    prompt_builder.build_judge_score_context_message.return_value = (
        context_message
    )
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

    response = judge.assess_scores(
        mock_game_manager, [], Mock(), [], [], proposal_passed=True
    )

    assert response["score_adjustments"] == [
        {"player": "Alice", "delta": 2, "reason": "bonus"}
    ]
    assert mock_game_manager.game_state.scores["Alice"] == 0
    prompt_builder.build_judge_score_context_message.assert_called_once()
    api_client.get_completion.assert_called_once()


# =====================================================================
# RETRY BEHAVIOR TESTS
# =====================================================================


def test_get_veto_retries_on_malformed_json(mock_game_manager):
    """get_veto should retry when LLM returns malformed JSON."""

    prompt_builder = Mock()
    context_message = _dummy_messages()[1]
    prompt_builder.build_judge_score_context_message.return_value = (
        context_message
    )
    prompt_builder.build_judge_veto_prompt.return_value = ChatMessage(
        role="user", content="veto"
    )

    api_client = Mock()
    # First call: malformed JSON (extra closing brace)
    # Second call: valid JSON
    api_client.get_completion.side_effect = [
        '{"private_thoughts":"x","veto":true,"reason":"conflict"}\n}',
        '{"private_thoughts":"x","veto":true,"reason":"conflict"}',
    ]

    judge = LLMJudge(
        Mock(), prompt_builder=prompt_builder, api_client=api_client
    )

    decision = judge.get_veto(mock_game_manager, Mock(), [], [])

    assert decision["veto"] is True
    assert api_client.get_completion.call_count == 2


def test_get_veto_raises_after_max_retries(mock_game_manager):
    """get_veto should raise RuntimeError after exhausting retries."""

    prompt_builder = Mock()
    context_message = _dummy_messages()[1]
    prompt_builder.build_judge_score_context_message.return_value = (
        context_message
    )
    prompt_builder.build_judge_veto_prompt.return_value = ChatMessage(
        role="user", content="veto"
    )

    api_client = Mock()
    # All attempts return malformed JSON
    api_client.get_completion.return_value = "not valid json"

    judge = LLMJudge(
        Mock(), prompt_builder=prompt_builder, api_client=api_client
    )

    with pytest.raises(
        RuntimeError, match="failed to generate a valid veto decision"
    ):
        judge.get_veto(mock_game_manager, Mock(), [], [])

    # Should retry MAX_VETO_RETRIES times (default is 2)
    assert (
        api_client.get_completion.call_count
        == judge.tuning.max_judge_veto_retries
    )


def test_get_veto_retries_on_api_error(mock_game_manager):
    """get_veto should retry when API client returns None."""

    prompt_builder = Mock()
    context_message = _dummy_messages()[1]
    prompt_builder.build_judge_score_context_message.return_value = (
        context_message
    )
    prompt_builder.build_judge_veto_prompt.return_value = ChatMessage(
        role="user", content="veto"
    )

    api_client = Mock()
    # First call: API error (None)
    # Second call: valid JSON
    api_client.get_completion.side_effect = [
        None,
        '{"private_thoughts":"x","veto":false,"reason":"ok"}',
    ]

    judge = LLMJudge(
        Mock(), prompt_builder=prompt_builder, api_client=api_client
    )

    decision = judge.get_veto(mock_game_manager, Mock(), [], [])

    assert decision["veto"] is False
    assert api_client.get_completion.call_count == 2


def test_get_veto_raises_on_missing_required_key(mock_game_manager):
    """get_veto should raise RuntimeError after retries on missing keys."""

    prompt_builder = Mock()
    context_message = _dummy_messages()[1]
    prompt_builder.build_judge_score_context_message.return_value = (
        context_message
    )
    prompt_builder.build_judge_veto_prompt.return_value = ChatMessage(
        role="user", content="veto"
    )

    api_client = Mock()
    # Missing "reason" key
    api_client.get_completion.return_value = (
        '{"private_thoughts":"x","veto":true}'
    )

    judge = LLMJudge(
        Mock(), prompt_builder=prompt_builder, api_client=api_client
    )

    with pytest.raises(
        RuntimeError, match="failed to generate a valid veto decision"
    ):
        judge.get_veto(mock_game_manager, Mock(), [], [])


def test_assess_scores_retries_on_malformed_json(mock_game_manager):
    """assess_scores should retry when LLM returns malformed JSON."""

    prompt_builder = Mock()
    context_message = _dummy_messages()[1]
    prompt_builder.build_judge_score_context_message.return_value = (
        context_message
    )
    prompt_builder.build_judge_score_prompt.return_value = ChatMessage(
        role="user", content="score"
    )

    api_client = Mock()
    # First call: malformed JSON
    # Second call: valid JSON
    api_client.get_completion.side_effect = [
        "invalid json",
        '{"private_thoughts":"ok","score_adjustments":[]}',
    ]

    judge = LLMJudge(
        Mock(), prompt_builder=prompt_builder, api_client=api_client
    )

    response = judge.assess_scores(
        mock_game_manager, [], Mock(), [], [], proposal_passed=True
    )

    assert response["score_adjustments"] == []
    assert api_client.get_completion.call_count == 2


def test_assess_scores_raises_after_max_retries(mock_game_manager):
    """assess_scores should raise RuntimeError after exhausting retries."""

    prompt_builder = Mock()
    context_message = _dummy_messages()[1]
    prompt_builder.build_judge_score_context_message.return_value = (
        context_message
    )
    prompt_builder.build_judge_score_prompt.return_value = ChatMessage(
        role="user", content="score"
    )

    api_client = Mock()
    # All attempts return malformed JSON
    api_client.get_completion.return_value = "not valid json"

    judge = LLMJudge(
        Mock(), prompt_builder=prompt_builder, api_client=api_client
    )

    with pytest.raises(
        RuntimeError, match="failed to generate a valid score assessment"
    ):
        judge.assess_scores(
            mock_game_manager, [], Mock(), [], [], proposal_passed=True
        )

    # Should retry MAX_SCORE_RETRIES times (default is 2)
    assert (
        api_client.get_completion.call_count
        == judge.tuning.max_judge_score_retries
    )


def test_assess_scores_no_partial_application_on_failure(mock_game_manager):
    """assess_scores should not modify scores on parsing failure."""

    prompt_builder = Mock()
    context_message = _dummy_messages()[1]
    prompt_builder.build_judge_score_context_message.return_value = (
        context_message
    )
    prompt_builder.build_judge_score_prompt.return_value = ChatMessage(
        role="user", content="score"
    )

    api_client = Mock()
    # All attempts return malformed JSON
    api_client.get_completion.return_value = "not valid json"

    judge = LLMJudge(
        Mock(), prompt_builder=prompt_builder, api_client=api_client
    )

    initial_alice_score = mock_game_manager.game_state.scores["Alice"]
    initial_bob_score = mock_game_manager.game_state.scores["Bob"]

    with pytest.raises(RuntimeError):
        judge.assess_scores(
            mock_game_manager, [], Mock(), [], [], proposal_passed=True
        )

    # Scores should remain unchanged
    assert mock_game_manager.game_state.scores["Alice"] == initial_alice_score
    assert mock_game_manager.game_state.scores["Bob"] == initial_bob_score


def test_assess_scores_retries_on_invalid_player_name(mock_game_manager):
    """assess_scores should retry when response references unknown player."""

    prompt_builder = Mock()
    context_message = _dummy_messages()[1]
    prompt_builder.build_judge_score_context_message.return_value = (
        context_message
    )
    prompt_builder.build_judge_score_prompt.return_value = ChatMessage(
        role="user", content="score"
    )

    api_client = Mock()
    # First call: references non-existent player "Charlie"
    # Second call: valid response
    api_client.get_completion.side_effect = [
        '{"private_thoughts":"ok","score_adjustments":[{'
        '"player":"Charlie","delta":5,"reason":"bonus"}]}',
        '{"private_thoughts":"ok","score_adjustments":[{'
        '"player":"Alice","delta":3,"reason":"bonus"}]}',
    ]

    judge = LLMJudge(
        Mock(), prompt_builder=prompt_builder, api_client=api_client
    )

    response = judge.assess_scores(
        mock_game_manager, [], Mock(), [], [], proposal_passed=True
    )

    # Should succeed on second attempt
    assert len(response["score_adjustments"]) == 1
    assert response["score_adjustments"][0]["player"] == "Alice"
    assert response["score_adjustments"] == [
        {"player": "Alice", "delta": 3, "reason": "bonus"}
    ]
    assert mock_game_manager.game_state.scores["Alice"] == 0
    assert api_client.get_completion.call_count == 2
