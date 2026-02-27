"""Unit tests for the LLMJudge strategy."""

from unittest.mock import Mock

import pytest

from src.nomic_engine.data_models import (
    ChatMessage,
    CompletionResult,
    GameState,
    Rule,
    RuleStatus,
)
from src.nomic_engine.judge.llm_judge import LLMJudge
from src.nomic_engine.llm import prompts as llm_prompts


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
            rule_id="1",
            text="Follow the rules.",
            status=RuleStatus.IMMUTABLE,
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


def _make_judge_with_history(prompt_builder=None, api_client=None):
    """Create an LLMJudge with a pre-populated _turn_history.

    Simulates the state after get_veto has successfully run, so that
    assess_scores and maintain_state tests can be called in isolation.
    """
    if prompt_builder is None:
        prompt_builder = Mock()
        prompt_builder.build_judge_score_prompt.return_value = ChatMessage(
            role="user", content="score"
        )
        prompt_builder.build_judge_maintain_state_prompt.return_value = (
            ChatMessage(role="user", content="maintain")
        )
    if api_client is None:
        api_client = Mock()

    judge = LLMJudge(
        Mock(), prompt_builder=prompt_builder, api_client=api_client
    )
    # Simulate turn_history as initialized by a successful get_veto
    judge._turn_history = [
        ChatMessage(role="system", content=llm_prompts.JUDGE_SYSTEM_PROMPT),
        ChatMessage(role="user", content="turn context"),
        ChatMessage(role="user", content="veto prompt"),
        ChatMessage(
            role="assistant",
            content=('{"private_thoughts":"v","veto":false,"reason":"ok"}'),
        ),
    ]
    return judge


def test_get_veto_returns_bool(mock_game_manager):
    """LLMJudge should parse veto output and return the boolean decision."""

    prompt_builder = Mock()
    context_message = _dummy_messages()[1]
    prompt_builder.build_judge_context_message.return_value = context_message
    prompt_builder.build_judge_veto_prompt.return_value = ChatMessage(
        role="user", content="veto"
    )

    api_client = Mock()
    api_client.get_completion.return_value = CompletionResult(
        text='{"private_thoughts":"x","veto":true,"reason":"conflict"}',
        raw_response=None,
        client_latency_ms=0,
    )

    judge = LLMJudge(
        Mock(), prompt_builder=prompt_builder, api_client=api_client
    )

    decision = judge.get_veto(mock_game_manager, Mock(), [], [])

    assert decision["veto"] is True
    prompt_builder.build_judge_context_message.assert_called_once()
    api_client.get_completion.assert_called_once()


def test_get_veto_initializes_turn_history(mock_game_manager):
    """get_veto should initialize _turn_history with system, context, veto
    prompt, and on success append the assistant response."""

    prompt_builder = Mock()
    context_msg = ChatMessage(role="user", content="turn context")
    veto_prompt_msg = ChatMessage(role="user", content="veto prompt")
    prompt_builder.build_judge_context_message.return_value = context_msg
    prompt_builder.build_judge_veto_prompt.return_value = veto_prompt_msg

    api_client = Mock()
    veto_text = '{"private_thoughts":"x","veto":false,"reason":"ok"}'
    api_client.get_completion.return_value = CompletionResult(
        text=veto_text, raw_response=None, client_latency_ms=0
    )

    judge = LLMJudge(
        Mock(), prompt_builder=prompt_builder, api_client=api_client
    )
    judge.get_veto(mock_game_manager, Mock(), [], [])

    # [system, context, veto_prompt, veto_response]
    assert len(judge._turn_history) == 4
    assert judge._turn_history[0].role == "system"
    assert llm_prompts.JUDGE_SYSTEM_PROMPT in judge._turn_history[0].content
    assert judge._turn_history[1] is context_msg
    assert judge._turn_history[2] is veto_prompt_msg
    assert judge._turn_history[3].role == "assistant"
    assert judge._turn_history[3].content == veto_text


def test_assess_scores_returns_adjustments_without_mutation(
    mock_game_manager,
):
    """Score adjustments returned by the LLM should be side-effect free."""

    prompt_builder = Mock()
    prompt_builder.build_judge_score_prompt.return_value = ChatMessage(
        role="user", content="score"
    )

    api_client = Mock()
    api_client.get_completion.return_value = CompletionResult(
        text=(
            '{"private_thoughts":"ok","score_adjustments":[{'
            '"player":"Alice","delta":2,"reason":"bonus"}]}'
        ),
        raw_response=None,
        client_latency_ms=0,
    )

    judge = _make_judge_with_history(
        prompt_builder=prompt_builder, api_client=api_client
    )

    response = judge.assess_scores(
        mock_game_manager, [], Mock(), [], [], proposal_passed=True
    )

    assert response["score_adjustments"] == [
        {"player": "Alice", "delta": 2, "reason": "bonus"}
    ]
    assert mock_game_manager.game_state.scores["Alice"] == 0
    # build_judge_score_context_message is NOT called in the new architecture
    prompt_builder.build_judge_score_context_message.assert_not_called()
    api_client.get_completion.assert_called_once()


def test_assess_scores_appends_to_turn_history(mock_game_manager):
    """assess_scores appends score_prompt and response to _turn_history."""

    prompt_builder = Mock()
    score_prompt_msg = ChatMessage(role="user", content="score")
    prompt_builder.build_judge_score_prompt.return_value = score_prompt_msg

    api_client = Mock()
    score_text = '{"private_thoughts":"ok","score_adjustments":[]}'
    api_client.get_completion.return_value = CompletionResult(
        text=score_text, raw_response=None, client_latency_ms=0
    )

    judge = _make_judge_with_history(
        prompt_builder=prompt_builder, api_client=api_client
    )
    history_len_before = len(judge._turn_history)

    judge.assess_scores(
        mock_game_manager, [], Mock(), [], [], proposal_passed=True
    )

    # score_prompt + assistant_response were appended
    assert len(judge._turn_history) == history_len_before + 2
    assert judge._turn_history[history_len_before] is score_prompt_msg
    assert judge._turn_history[history_len_before + 1].role == "assistant"
    assert judge._turn_history[history_len_before + 1].content == score_text


def test_maintain_state_appends_to_turn_history(mock_game_manager):
    """maintain_state appends its prompt and response to _turn_history."""

    prompt_builder = Mock()
    maintain_msg = ChatMessage(role="user", content="maintain")
    prompt_builder.build_judge_maintain_state_prompt.return_value = (
        maintain_msg
    )

    api_client = Mock()
    state_text = '{"private_thoughts":"none","flags":{},"target_score":null}'
    api_client.get_completion.return_value = CompletionResult(
        text=state_text, raw_response=None, client_latency_ms=0
    )

    judge = _make_judge_with_history(
        prompt_builder=prompt_builder, api_client=api_client
    )
    history_len_before = len(judge._turn_history)

    judge.maintain_state(mock_game_manager, Mock(), None, None)

    # maintain_prompt + assistant_response were appended
    assert len(judge._turn_history) == history_len_before + 2
    assert judge._turn_history[history_len_before] is maintain_msg
    assert judge._turn_history[history_len_before + 1].role == "assistant"
    assert judge._turn_history[history_len_before + 1].content == state_text


def test_turn_history_sent_to_api_in_assess_scores(mock_game_manager):
    """assess_scores sends the full _turn_history to the API.

    Captures messages at the time of the API call (before the success
    response is appended to _turn_history) by using a side_effect.
    """

    prompt_builder = Mock()
    score_prompt_msg = ChatMessage(role="user", content="score")
    prompt_builder.build_judge_score_prompt.return_value = score_prompt_msg

    judge = _make_judge_with_history(prompt_builder=prompt_builder)
    pre_history = list(judge._turn_history)  # snapshot before

    # Capture messages at call time (before mutation on success)
    captured: list[list[ChatMessage]] = []

    def capture_and_return(messages: list[ChatMessage]) -> CompletionResult:
        captured.append(list(messages))  # copy at call time
        return CompletionResult(
            text='{"private_thoughts":"ok","score_adjustments":[]}',
            raw_response=None,
            client_latency_ms=0,
        )

    judge.api_client.get_completion.side_effect = capture_and_return

    judge.assess_scores(
        mock_game_manager, [], Mock(), [], [], proposal_passed=True
    )

    assert len(captured) == 1
    sent_messages = captured[0]
    # Sent messages = pre-existing history + score_prompt
    assert len(sent_messages) == len(pre_history) + 1
    for i, msg in enumerate(pre_history):
        assert sent_messages[i] is msg
    assert sent_messages[-1] is score_prompt_msg


# =====================================================================
# RETRY BEHAVIOR TESTS
# =====================================================================


def test_get_veto_retries_on_malformed_json(mock_game_manager):
    """get_veto should retry when LLM returns malformed JSON."""

    prompt_builder = Mock()
    context_message = _dummy_messages()[1]
    prompt_builder.build_judge_context_message.return_value = context_message
    prompt_builder.build_judge_veto_prompt.return_value = ChatMessage(
        role="user", content="veto"
    )

    api_client = Mock()
    # First call: malformed JSON (extra closing brace)
    # Second call: valid JSON
    api_client.get_completion.side_effect = [
        CompletionResult(
            text=(
                '{"private_thoughts":"x","veto":true,'
                '"reason":"conflict"}\n}'
            ),
            raw_response=None,
            client_latency_ms=0,
        ),
        CompletionResult(
            text='{"private_thoughts":"x","veto":true,"reason":"conflict"}',
            raw_response=None,
            client_latency_ms=0,
        ),
    ]

    judge = LLMJudge(
        Mock(), prompt_builder=prompt_builder, api_client=api_client
    )

    decision = judge.get_veto(mock_game_manager, Mock(), [], [])

    assert decision["veto"] is True
    assert api_client.get_completion.call_count == 2


def test_get_veto_retry_appends_to_turn_history(mock_game_manager):
    """get_veto retry appends bad response + retry prompt to _turn_history."""

    prompt_builder = Mock()
    prompt_builder.build_judge_context_message.return_value = ChatMessage(
        role="user", content="ctx"
    )
    prompt_builder.build_judge_veto_prompt.return_value = ChatMessage(
        role="user", content="veto"
    )

    bad_text = "not json"
    good_text = '{"private_thoughts":"x","veto":false,"reason":"ok"}'
    api_client = Mock()
    api_client.get_completion.side_effect = [
        CompletionResult(
            text=bad_text, raw_response=None, client_latency_ms=0
        ),
        CompletionResult(
            text=good_text, raw_response=None, client_latency_ms=0
        ),
    ]

    judge = LLMJudge(
        Mock(), prompt_builder=prompt_builder, api_client=api_client
    )
    judge.get_veto(mock_game_manager, Mock(), [], [])

    # [system, ctx, veto_prompt, bad_response, retry_prompt, good_response]
    assert len(judge._turn_history) == 6
    assert judge._turn_history[3].role == "assistant"
    assert judge._turn_history[3].content == bad_text
    assert judge._turn_history[4].role == "user"
    assert "FINAL attempt" in judge._turn_history[4].content
    assert judge._turn_history[5].role == "assistant"
    assert judge._turn_history[5].content == good_text


def test_get_veto_raises_after_max_retries(mock_game_manager):
    """get_veto should raise RuntimeError after exhausting retries."""

    prompt_builder = Mock()
    context_message = _dummy_messages()[1]
    prompt_builder.build_judge_context_message.return_value = context_message
    prompt_builder.build_judge_veto_prompt.return_value = ChatMessage(
        role="user", content="veto"
    )

    api_client = Mock()
    # All attempts return malformed JSON
    api_client.get_completion.return_value = CompletionResult(
        text="not valid json", raw_response=None, client_latency_ms=0
    )

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
    prompt_builder.build_judge_context_message.return_value = context_message
    prompt_builder.build_judge_veto_prompt.return_value = ChatMessage(
        role="user", content="veto"
    )

    api_client = Mock()
    # First call: API error (None)
    # Second call: valid JSON
    api_client.get_completion.side_effect = [
        CompletionResult(text=None, raw_response=None, client_latency_ms=0),
        CompletionResult(
            text='{"private_thoughts":"x","veto":false,"reason":"ok"}',
            raw_response=None,
            client_latency_ms=0,
        ),
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
    prompt_builder.build_judge_context_message.return_value = context_message
    prompt_builder.build_judge_veto_prompt.return_value = ChatMessage(
        role="user", content="veto"
    )

    api_client = Mock()
    # Missing "reason" key
    api_client.get_completion.return_value = CompletionResult(
        text='{"private_thoughts":"x","veto":true}',
        raw_response=None,
        client_latency_ms=0,
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
    prompt_builder.build_judge_score_prompt.return_value = ChatMessage(
        role="user", content="score"
    )

    api_client = Mock()
    # First call: malformed JSON
    # Second call: valid JSON
    api_client.get_completion.side_effect = [
        CompletionResult(
            text="invalid json", raw_response=None, client_latency_ms=0
        ),
        CompletionResult(
            text='{"private_thoughts":"ok","score_adjustments":[]}',
            raw_response=None,
            client_latency_ms=0,
        ),
    ]

    judge = _make_judge_with_history(
        prompt_builder=prompt_builder, api_client=api_client
    )

    response = judge.assess_scores(
        mock_game_manager, [], Mock(), [], [], proposal_passed=True
    )

    assert response["score_adjustments"] == []
    assert api_client.get_completion.call_count == 2


def test_assess_scores_retry_appends_to_turn_history(mock_game_manager):
    """assess_scores retry appends bad response + retry prompt to history."""

    prompt_builder = Mock()
    score_prompt_msg = ChatMessage(role="user", content="score")
    prompt_builder.build_judge_score_prompt.return_value = score_prompt_msg

    bad_text = "invalid json"
    good_text = '{"private_thoughts":"ok","score_adjustments":[]}'
    api_client = Mock()
    api_client.get_completion.side_effect = [
        CompletionResult(
            text=bad_text, raw_response=None, client_latency_ms=0
        ),
        CompletionResult(
            text=good_text, raw_response=None, client_latency_ms=0
        ),
    ]

    judge = _make_judge_with_history(
        prompt_builder=prompt_builder, api_client=api_client
    )
    history_len_before = len(judge._turn_history)

    judge.assess_scores(
        mock_game_manager, [], Mock(), [], [], proposal_passed=True
    )

    # score_prompt, bad_response, retry_prompt, good_response were appended
    assert len(judge._turn_history) == history_len_before + 4
    assert judge._turn_history[history_len_before] is score_prompt_msg
    assert judge._turn_history[history_len_before + 1].role == "assistant"
    assert judge._turn_history[history_len_before + 1].content == bad_text
    assert judge._turn_history[history_len_before + 2].role == "user"
    assert judge._turn_history[history_len_before + 3].role == "assistant"
    assert judge._turn_history[history_len_before + 3].content == good_text


def test_assess_scores_raises_after_max_retries(mock_game_manager):
    """assess_scores should raise RuntimeError after exhausting retries."""

    prompt_builder = Mock()
    prompt_builder.build_judge_score_prompt.return_value = ChatMessage(
        role="user", content="score"
    )

    api_client = Mock()
    # All attempts return malformed JSON
    api_client.get_completion.return_value = CompletionResult(
        text="not valid json", raw_response=None, client_latency_ms=0
    )

    judge = _make_judge_with_history(
        prompt_builder=prompt_builder, api_client=api_client
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
    prompt_builder.build_judge_score_prompt.return_value = ChatMessage(
        role="user", content="score"
    )

    api_client = Mock()
    # All attempts return malformed JSON
    api_client.get_completion.return_value = CompletionResult(
        text="not valid json", raw_response=None, client_latency_ms=0
    )

    judge = _make_judge_with_history(
        prompt_builder=prompt_builder, api_client=api_client
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
    prompt_builder.build_judge_score_prompt.return_value = ChatMessage(
        role="user", content="score"
    )

    api_client = Mock()
    # First call: references non-existent player "Charlie"
    # Second call: valid response
    api_client.get_completion.side_effect = [
        CompletionResult(
            text=(
                '{"private_thoughts":"ok","score_adjustments":[{'
                '"player":"Charlie","delta":5,"reason":"bonus"}]}'
            ),
            raw_response=None,
            client_latency_ms=0,
        ),
        CompletionResult(
            text=(
                '{"private_thoughts":"ok","score_adjustments":[{'
                '"player":"Alice","delta":3,"reason":"bonus"}]}'
            ),
            raw_response=None,
            client_latency_ms=0,
        ),
    ]

    judge = _make_judge_with_history(
        prompt_builder=prompt_builder, api_client=api_client
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


# =====================================================================
# MEMORY INJECTION TESTS
# =====================================================================


def test_build_judge_system_message_with_memory_appends_block():
    """_build_judge_system_message with non-empty content appends the
    MEMORY_INJECTION block after JUDGE_SYSTEM_PROMPT."""
    from src.nomic_engine.llm import prompts as llm_prompts

    judge = LLMJudge(Mock(), api_client=Mock())
    memory = "# Judge Memory\n\nSome precedents."
    msg = judge._build_judge_system_message(memory_content=memory)

    assert msg.role == "system"
    assert llm_prompts.JUDGE_SYSTEM_PROMPT in msg.content
    assert "=== YOUR PRIVATE MEMORY ===" in msg.content
    assert "Some precedents." in msg.content
    # Memory block must come AFTER the base prompt
    base_pos = msg.content.index(llm_prompts.JUDGE_SYSTEM_PROMPT)
    mem_pos = msg.content.index("=== YOUR PRIVATE MEMORY ===")
    assert base_pos < mem_pos


def test_build_judge_system_message_empty_memory_equals_base_prompt():
    """_build_judge_system_message with empty content returns a message
    whose content equals JUDGE_SYSTEM_PROMPT exactly."""
    from src.nomic_engine.llm import prompts as llm_prompts

    judge = LLMJudge(Mock(), api_client=Mock())

    msg_default = judge._build_judge_system_message()
    msg_empty = judge._build_judge_system_message(memory_content="")
    msg_whitespace = judge._build_judge_system_message(memory_content="  \n  ")

    assert msg_default.content == llm_prompts.JUDGE_SYSTEM_PROMPT
    assert msg_empty.content == llm_prompts.JUDGE_SYSTEM_PROMPT
    assert msg_whitespace.content == llm_prompts.JUDGE_SYSTEM_PROMPT
    assert "=== YOUR PRIVATE MEMORY ===" not in msg_default.content
