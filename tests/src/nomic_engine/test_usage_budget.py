"""Mock tests for the fail-closed usage budget and usage report.

No test in this module calls a live model or the network. Provider SDKs
are patched.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import yaml
from google.genai import types as google_types
from openai import OpenAIError
from pydantic import ValidationError

from src.nomic_engine.core.game_manager import GameManager
from src.nomic_engine.data_models import (
    ChatMessage,
    CompletionResult,
    GameConfig,
    GameState,
    JudgeType,
    ModelDefinition,
    ModelLibrary,
    PlayerConfig,
    Rule,
    RuleStatus,
    UsageBudget,
    WithdrawalPolicy,
)
from src.nomic_engine.llm.api_clients import (
    AnthropicApiClient,
    BudgetedApiClient,
    GoogleApiClient,
    OpenAICompatibleApiClient,
    build_token_usage_record,
)
from src.nomic_engine.llm.retry_helper import llm_retry_loop
from src.nomic_engine.main import instantiate_judge, instantiate_players
from src.nomic_engine.usage_budget import (
    UsageBudgetExceeded,
    UsageBudgetGuard,
    format_usage_report,
    summarize_token_usage_log,
)
from src.nomic_engine.utils.token_usage_logger import TokenUsageLogger

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CHEAP_CONFIG = _REPO_ROOT / "docs" / "examples" / "cheap-test" / "config.yml"


def _message() -> list[ChatMessage]:
    return [ChatMessage(role="user", content="hello")]


def _openai_model(model_id: str = "gpt-5-mini") -> ModelDefinition:
    return ModelDefinition(
        id=model_id,
        provider="openai",
        api_model_id=model_id,
        env_key_name="OPENAI_API_KEY",
    )


class _QuotaError(OpenAIError):
    """429-shaped error that does not touch the network."""

    status_code = 429


class _TimeoutError(OpenAIError):
    """Timeout-shaped error that does not touch the network."""


def _write_game_dir(game_dir: Path, config: dict[str, object]) -> None:
    (game_dir / "config.yml").write_text(
        yaml.safe_dump(config), encoding="utf-8"
    )
    state = GameState(
        scores={"Ada": 0},
        current_player_name="Ada",
        move_number=1,
        turn_order=["Ada"],
        next_proposal_id=301,
    )
    (game_dir / "game_state.json").write_text(
        state.model_dump_json(), encoding="utf-8"
    )
    rule = Rule(
        rule_id="101",
        text="Follow the rules.",
        status=RuleStatus.IMMUTABLE,
    )
    (game_dir / "rules.jsonl").write_text(
        rule.model_dump_json() + "\n", encoding="utf-8"
    )


def test_default_budget_is_unlimited() -> None:
    """Unset budget fields keep the historical unlimited behavior."""
    config = GameConfig(players=[PlayerConfig(name="Ada", model_id="human")])
    assert config.budget.max_calls_per_game is None
    assert config.budget.max_total_tokens_per_game is None
    assert config.budget.max_wall_seconds is None
    assert config.budget.per_call_timeout_seconds is None
    assert config.budget.max_output_tokens is None

    guard = UsageBudgetGuard(config.budget)
    for _ in range(5):
        guard.before_call()
        guard.after_call(
            usage_available=True,
            input_tokens=999_999,
            output_tokens=999_999,
        )
    assert guard.calls == 5


def test_budget_rejects_non_positive_limits() -> None:
    with pytest.raises(ValidationError):
        UsageBudget(max_calls_per_game=0)
    with pytest.raises(ValidationError):
        UsageBudget(per_call_timeout_seconds=0)
    with pytest.raises(ValidationError):
        UsageBudget(max_output_tokens=-1)


def test_guard_stops_before_call_when_call_cap_is_reached() -> None:
    inner = MagicMock()
    guard = UsageBudgetGuard(UsageBudget(max_calls_per_game=1))
    client = BudgetedApiClient(inner, guard, "openai")
    inner.get_completion.return_value = CompletionResult(
        text="ok", raw_response=None, client_latency_ms=1
    )

    client.get_completion(_message())
    with pytest.raises(UsageBudgetExceeded) as exc_info:
        client.get_completion(_message())

    assert inner.get_completion.call_count == 1
    assert exc_info.value.limit_name == "max_calls_per_game"
    assert "Refusing the next provider call" in str(exc_info.value)


def test_retries_count_toward_max_calls() -> None:
    """Each retry is a provider call. The next one is not sent."""
    inner = MagicMock()
    inner.get_completion.return_value = CompletionResult(
        text=None,
        raw_response=None,
        client_latency_ms=1,
        error_kind="api_error",
    )
    guard = UsageBudgetGuard(UsageBudget(max_calls_per_game=2))
    client = BudgetedApiClient(inner, guard, "openai")

    with pytest.raises(UsageBudgetExceeded) as exc_info:
        llm_retry_loop(
            history=_message(),
            api_client=client,
            parse_fn=lambda text: text,
            max_retries=5,
            retry_template="retry {validation_error}",
            actor_label="Ada",
            action_description="thinking",
        )

    assert inner.get_completion.call_count == 2
    assert guard.calls == 2
    assert exc_info.value.limit_name == "max_calls_per_game"


def test_missing_usage_stops_token_capped_retry() -> None:
    """Unavailable usage is not zero, so the retry is not sent."""
    inner = MagicMock()
    inner.get_completion.return_value = CompletionResult(
        text=None,
        raw_response=None,
        client_latency_ms=4,
        error_kind="timeout",
    )
    guard = UsageBudgetGuard(UsageBudget(max_total_tokens_per_game=1000))
    client = BudgetedApiClient(inner, guard, "openai")

    with pytest.raises(UsageBudgetExceeded) as exc_info:
        llm_retry_loop(
            history=_message(),
            api_client=client,
            parse_fn=lambda text: text,
            max_retries=4,
            retry_template="retry {validation_error}",
            actor_label="Ada",
            action_description="thinking",
        )

    assert inner.get_completion.call_count == 1
    message = str(exc_info.value)
    assert "unavailable" in message
    assert "not zero" in message
    assert guard.unavailable_calls == 1
    assert guard.known_total_tokens == 0


def test_missing_usage_is_reported_separately_from_zero(
    tmp_path: Path,
) -> None:
    raw_zero = MagicMock()
    raw_zero.usage.prompt_tokens = 0
    raw_zero.usage.completion_tokens = 0
    raw_zero.choices = [MagicMock(finish_reason="stop")]
    zero_result = CompletionResult(
        text="ok", raw_response=raw_zero, client_latency_ms=2
    )
    missing_result = CompletionResult(
        text=None, raw_response=None, client_latency_ms=3, error_kind="quota"
    )
    model = _openai_model()
    log_path = tmp_path / "token_usage.jsonl"
    usage_logger = TokenUsageLogger(log_path)
    usage_logger.log(
        build_token_usage_record(
            result=zero_result,
            model_config=model,
            call_type="propose",
            move_number=1,
            player_name="Ada",
        )
    )
    usage_logger.log(
        build_token_usage_record(
            result=missing_result,
            model_config=model,
            call_type="propose",
            move_number=1,
            player_name="Ada",
        )
    )

    _per_turn, game = summarize_token_usage_log(log_path)
    assert game.calls == 2
    assert game.calls_with_zero_tokens == 1
    assert game.calls_with_unavailable_usage == 1
    assert game.input_tokens == 0
    assert game.output_tokens == 0
    assert game.calls_quota == 1
    report = format_usage_report(log_path)
    assert "calls_with_unavailable_usage: 1" in report
    assert "calls_with_zero_tokens: 1" in report
    assert "Unavailable usage is not counted as zero." in report
    assert "not a precise token cap" in report

    inner = MagicMock()
    inner.get_completion.return_value = missing_result
    guard = UsageBudgetGuard(
        UsageBudget(max_total_tokens_per_game=500),
        log_path=log_path,
    )
    client = BudgetedApiClient(inner, guard, "openai")
    with pytest.raises(UsageBudgetExceeded):
        client.get_completion(_message())
    inner.get_completion.assert_not_called()


def test_explicit_zero_usage_does_not_stop_a_token_capped_game() -> None:
    raw = MagicMock()
    raw.usage.prompt_tokens = 0
    raw.usage.completion_tokens = 0
    raw.choices = []
    inner = MagicMock()
    inner.get_completion.return_value = CompletionResult(
        text="ok", raw_response=raw, client_latency_ms=1
    )
    guard = UsageBudgetGuard(UsageBudget(max_total_tokens_per_game=10))
    client = BudgetedApiClient(inner, guard, "openai")

    client.get_completion(_message())
    client.get_completion(_message())

    assert inner.get_completion.call_count == 2
    assert guard.zero_token_calls == 2
    assert guard.unavailable_calls == 0


def test_token_cap_allows_overshoot_then_stops() -> None:
    raw = MagicMock()
    raw.usage.prompt_tokens = 80
    raw.usage.completion_tokens = 50
    raw.choices = []
    inner = MagicMock()
    inner.get_completion.return_value = CompletionResult(
        text="ok", raw_response=raw, client_latency_ms=1
    )
    guard = UsageBudgetGuard(UsageBudget(max_total_tokens_per_game=100))
    client = BudgetedApiClient(inner, guard, "openai")

    client.get_completion(_message())
    with pytest.raises(UsageBudgetExceeded) as exc_info:
        client.get_completion(_message())

    assert inner.get_completion.call_count == 1
    assert guard.known_total_tokens == 130
    assert "overshoot" in str(exc_info.value)
    assert "not a precise" in str(exc_info.value)


def test_wall_clock_stops_before_the_call() -> None:
    now = {"t": 0.0}
    guard = UsageBudgetGuard(
        UsageBudget(max_wall_seconds=5),
        clock=lambda: now["t"],
    )
    inner = MagicMock()
    client = BudgetedApiClient(inner, guard, "openai")
    now["t"] = 5.0

    with pytest.raises(UsageBudgetExceeded) as exc_info:
        client.get_completion(_message())

    inner.get_completion.assert_not_called()
    assert exc_info.value.limit_name == "max_wall_seconds"


def test_restart_restores_call_cap_from_the_log(tmp_path: Path) -> None:
    log_path = tmp_path / "token_usage.jsonl"
    line = json.dumps(
        {
            "move_number": 2,
            "usage_available": True,
            "input_tokens": 3,
            "output_tokens": 4,
        }
    )
    log_path.write_text(line + "\n" + line + "\n", encoding="utf-8")
    guard = UsageBudgetGuard(
        UsageBudget(max_calls_per_game=2),
        log_path=log_path,
    )
    inner = MagicMock()
    client = BudgetedApiClient(inner, guard, "openai")

    with pytest.raises(UsageBudgetExceeded):
        client.get_completion(_message())

    inner.get_completion.assert_not_called()
    assert guard.known_total_tokens == 14


def test_loaded_game_attaches_guard_from_config_and_log(
    tmp_path: Path,
) -> None:
    _write_game_dir(
        tmp_path,
        {
            "players": [{"name": "Ada", "model_id": "human"}],
            "budget": {"max_total_tokens_per_game": 50},
        },
    )
    log_path = tmp_path / "token_usage.jsonl"
    log_path.write_text(
        json.dumps(
            {
                "move_number": 1,
                "usage_available": False,
                "input_tokens": None,
                "output_tokens": None,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    manager = GameManager(tmp_path)
    manager.load_game()

    assert manager.usage_guard is not None
    assert manager.usage_guard.calls == 1
    with pytest.raises(UsageBudgetExceeded) as exc_info:
        manager.usage_guard.before_call()
    assert "unavailable" in str(exc_info.value)


def test_report_lists_turns_and_truncated_calls(tmp_path: Path) -> None:
    log_path = tmp_path / "token_usage.jsonl"
    rows = [
        {
            "move_number": 2,
            "usage_available": True,
            "input_tokens": 10,
            "output_tokens": 5,
            "finish_reason": "length",
            "error_kind": None,
        },
        {
            "move_number": 1,
            "usage_available": True,
            "input_tokens": 1,
            "output_tokens": 1,
            "finish_reason": "stop",
        },
    ]
    log_path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )
    per_turn, game = summarize_token_usage_log(log_path)
    assert game.total_tokens == 17
    assert game.calls_truncated == 1
    assert sorted(per_turn) == [1, 2]
    report = format_usage_report(log_path)
    assert "move 1:" in report
    assert "move 2:" in report
    assert report.index("move 1:") < report.index("move 2:")


def test_partial_output_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    raw = MagicMock()
    raw.usage.input_tokens = 4
    raw.usage.output_tokens = 1024
    raw.stop_reason = "max_tokens"
    result = CompletionResult(
        text="partial", raw_response=raw, client_latency_ms=1
    )
    with caplog.at_level("WARNING"):
        record = build_token_usage_record(
            result=result,
            model_config=ModelDefinition(
                id="claude",
                provider="anthropic",
                api_model_id="claude",
                env_key_name=None,
            ),
            call_type="propose",
            move_number=1,
            player_name="Ada",
        )
    assert record.usage_available is True
    assert record.finish_reason == "max_tokens"
    assert "Partial output" in caplog.text


def test_quota_error_is_named_and_counts_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    model = _openai_model()
    with (
        patch("src.nomic_engine.llm.api_clients.OpenAI") as mock_openai,
        patch(
            "src.nomic_engine.llm.api_clients.anthropic.Anthropic"
        ) as mock_anthropic,
        patch("src.nomic_engine.llm.api_clients.genai.Client") as mock_google,
    ):
        mock_client = MagicMock()
        mock_client.chat.completions.with_raw_response.create.side_effect = (
            _QuotaError("limited")
        )
        mock_openai.return_value = mock_client
        inner = OpenAICompatibleApiClient(model)
        guard = UsageBudgetGuard(UsageBudget(max_calls_per_game=2))
        wrapped = BudgetedApiClient(inner, guard, "openai")
        with caplog.at_level("ERROR"):
            result = wrapped.get_completion(_message())

    assert result.text is None
    assert result.error_kind == "quota"
    assert guard.calls == 1
    assert guard.unavailable_calls == 1
    assert "no fallback provider" in caplog.text
    assert "quota" in caplog.text.lower()
    mock_anthropic.assert_not_called()
    mock_google.assert_not_called()
    mock_client.chat.completions.with_raw_response.create.assert_called_once()


def test_timeout_error_is_named(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    with patch("src.nomic_engine.llm.api_clients.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_client.chat.completions.with_raw_response.create.side_effect = (
            _TimeoutError("timed out")
        )
        mock_openai.return_value = mock_client
        client = OpenAICompatibleApiClient(_openai_model())
        with caplog.at_level("ERROR"):
            result = client.get_completion(_message())
    assert result.error_kind == "timeout"
    assert "timed out" in caplog.text
    assert "no fallback provider" in caplog.text


def _patch_openai_completion() -> MagicMock:
    """Return a mocked OpenAI SDK whose chat call yields a short completion."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "ok"
    mock_http = MagicMock()
    mock_http.parse.return_value = mock_response
    mock_sdk = MagicMock()
    mock_sdk.chat.completions.with_raw_response.create.return_value = mock_http
    return mock_sdk


def test_openai_gpt5_receives_timeout_and_max_completion_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    from src.nomic_engine.usage_budget import LlmCallOptions

    model = _openai_model("gpt-5-mini")
    mock_sdk = _patch_openai_completion()
    with patch(
        "src.nomic_engine.llm.api_clients.OpenAI", return_value=mock_sdk
    ):
        client = OpenAICompatibleApiClient(
            model,
            call_options=LlmCallOptions(
                per_call_timeout_seconds=60,
                max_output_tokens=1024,
            ),
        )
        client.get_completion(_message())
    kwargs = (
        mock_sdk.chat.completions.with_raw_response.create.call_args.kwargs
    )
    assert kwargs["timeout"] == 60
    assert kwargs["max_completion_tokens"] == 1024
    assert "max_tokens" not in kwargs


def test_older_openai_and_xai_and_ollama_use_max_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("XAI_API_KEY", "test-key")
    from src.nomic_engine.usage_budget import LlmCallOptions

    options = LlmCallOptions(
        per_call_timeout_seconds=15,
        max_output_tokens=256,
    )
    cases = [
        _openai_model("gpt-4o"),
        ModelDefinition(
            id="grok",
            provider="xai",
            api_model_id="grok-4-1-fast-reasoning",
            env_key_name="XAI_API_KEY",
        ),
        ModelDefinition(
            id="llama2",
            provider="local",
            api_model_id="http://localhost:11434/v1",
            env_key_name=None,
        ),
    ]
    for model in cases:
        mock_sdk = _patch_openai_completion()
        with patch(
            "src.nomic_engine.llm.api_clients.OpenAI", return_value=mock_sdk
        ):
            client = OpenAICompatibleApiClient(model, call_options=options)
            client.get_completion(_message())
        kwargs = (
            mock_sdk.chat.completions.with_raw_response.create.call_args.kwargs
        )
        assert kwargs["timeout"] == 15
        assert kwargs["max_tokens"] == 256
        assert "max_completion_tokens" not in kwargs


def test_anthropic_keeps_8192_until_output_cap_is_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    from src.nomic_engine.usage_budget import LlmCallOptions

    model = ModelDefinition(
        id="claude",
        provider="anthropic",
        api_model_id="claude-sonnet-4-5",
        env_key_name="ANTHROPIC_API_KEY",
    )
    text_block = MagicMock()
    text_block.text = "ok"
    response = MagicMock()
    response.content = [text_block]
    http_response = MagicMock()
    http_response.parse.return_value = response

    with patch(
        "src.nomic_engine.llm.api_clients.anthropic.Anthropic"
    ) as mock_cls:
        sdk = MagicMock()
        sdk.messages.with_raw_response.create.return_value = http_response
        mock_cls.return_value = sdk
        default_client = AnthropicApiClient(model)
        default_client.get_completion(_message())
        default_kwargs = sdk.messages.with_raw_response.create.call_args.kwargs
        assert default_kwargs["max_tokens"] == 8192
        assert "timeout" not in default_kwargs

        capped = AnthropicApiClient(
            model,
            call_options=LlmCallOptions(
                per_call_timeout_seconds=60,
                max_output_tokens=1024,
            ),
        )
        capped.get_completion(_message())
        capped_kwargs = sdk.messages.with_raw_response.create.call_args.kwargs
        assert capped_kwargs["max_tokens"] == 1024
        assert capped_kwargs["timeout"] == 60


def test_google_receives_max_output_tokens_and_timeout_ms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    from src.nomic_engine.usage_budget import LlmCallOptions

    model = ModelDefinition(
        id="gemini",
        provider="google",
        api_model_id="gemini-2.5-flash",
        env_key_name="GOOGLE_API_KEY",
    )
    response = MagicMock()
    response.text = "ok"
    with patch("src.nomic_engine.llm.api_clients.genai.Client") as mock_cls:
        sdk = MagicMock()
        sdk.models.generate_content.return_value = response
        mock_cls.return_value = sdk
        client = GoogleApiClient(
            model,
            call_options=LlmCallOptions(
                per_call_timeout_seconds=60,
                max_output_tokens=1024,
            ),
        )
        client.get_completion(
            [
                ChatMessage(role="system", content="Be brief."),
                ChatMessage(role="user", content="hello"),
            ]
        )
    config = sdk.models.generate_content.call_args.kwargs["config"]
    parsed = google_types.GenerateContentConfig.model_validate(config)
    assert parsed.max_output_tokens == 1024
    assert parsed.http_options is not None
    assert parsed.http_options.timeout == 60_000
    assert parsed.system_instruction == "Be brief."


def test_cheap_example_config_loads() -> None:
    loaded = yaml.safe_load(_CHEAP_CONFIG.read_text(encoding="utf-8"))
    config = GameConfig(**loaded)
    assert [player.model_id for player in config.players] == [
        "gpt-5-mini",
        "gpt-5-mini",
    ]
    assert config.target_score == 100
    assert config.judge_type == JudgeType.LLM
    assert config.judge_model is not None
    assert config.judge_model.api_model_id == "gpt-5-mini"
    assert config.withdrawal_policy == WithdrawalPolicy.FORFEIT
    assert config.max_withdrawal_retries == 0
    assert config.tuning.max_propose_retries == 2
    assert config.tuning.max_vote_retries == 2
    assert config.tuning.max_judge_score_retries == 2
    assert config.budget.max_calls_per_game == 60
    assert config.budget.per_call_timeout_seconds == 60
    assert config.budget.max_output_tokens == 1024
    assert config.budget.max_total_tokens_per_game is None
    assert config.budget.max_wall_seconds is None


@patch("src.nomic_engine.judge.llm_judge.create_api_client")
@patch("src.nomic_engine.players.llm_player.create_api_client")
def test_players_and_judge_share_one_guard(
    mock_player_factory: MagicMock,
    mock_judge_factory: MagicMock,
) -> None:
    budget = UsageBudget(
        max_calls_per_game=60,
        per_call_timeout_seconds=60,
        max_output_tokens=1024,
    )
    guard = UsageBudgetGuard(budget)
    model = _openai_model()
    config = GameConfig(
        players=[
            PlayerConfig(name="Ada", model_id="gpt-5-mini"),
            PlayerConfig(name="Grace", model_id="gpt-5-mini"),
        ],
        judge_type=JudgeType.LLM,
        judge_model=model,
        budget=budget,
    )
    manager = SimpleNamespace(
        game_config=config,
        memory_manager=None,
        token_usage_logger=None,
        usage_guard=guard,
    )
    instantiate_players(manager, ModelLibrary(models=[model]))  # type: ignore[arg-type]
    instantiate_judge(manager)  # type: ignore[arg-type]

    assert mock_player_factory.call_count == 2
    for call in mock_player_factory.call_args_list:
        assert call.kwargs["usage_guard"] is guard
        options = call.kwargs["call_options"]
        assert options.per_call_timeout_seconds == 60
        assert options.max_output_tokens == 1024
    assert mock_judge_factory.call_args.kwargs["usage_guard"] is guard
