"""
Unit tests for startup_validation.py.

All tests use mocked clients — no real network calls are made.
"""

from unittest.mock import MagicMock, patch

import httpx
import openai
import pytest
from google.genai import errors as google_errors

from src.nomic_engine.data_models import ModelDefinition
from src.nomic_engine.startup_validation import (
    _validate_anthropic,
    _validate_google,
    _validate_local,
    _validate_openai,
    _validate_xai,
    validate_startup,
)

# Module-level path prefix for patch() calls.
_MOD = "src.nomic_engine.startup_validation"


# ---------------------------------------------------------------------------
# Helpers for constructing openai exceptions
# ---------------------------------------------------------------------------


def _make_auth_error(url: str = "https://api.openai.com/v1/models"):
    req = httpx.Request("GET", url)
    resp = httpx.Response(401, request=req)
    return openai.AuthenticationError("Unauthorized", response=resp, body=None)


def _make_api_error(url: str = "https://api.openai.com/v1/models"):
    req = httpx.Request("GET", url)
    return openai.APIError("Generic API error", req, body=None)


def _make_connection_error(url: str = "http://localhost:11434/v1"):
    req = httpx.Request("GET", url)
    return openai.APIConnectionError(message="Connection refused", request=req)


# ---------------------------------------------------------------------------
# _validate_anthropic
# ---------------------------------------------------------------------------


def test_validate_anthropic_valid_key(monkeypatch):
    """A key starting with 'sk-ant-' passes format validation."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-validkey")
    result = _validate_anthropic("ANTHROPIC_API_KEY", 'Player "Alice"')
    assert result is None


def test_validate_anthropic_wrong_prefix(monkeypatch):
    """A key that does not start with 'sk-ant-' fails format check."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-proj-wrongprefix")
    result = _validate_anthropic("ANTHROPIC_API_KEY", 'Player "Alice"')
    assert result is not None
    assert "invalid format" in result
    assert "sk-ant-" in result


def test_validate_anthropic_missing_key(monkeypatch):
    """A missing env var produces an actionable error."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = _validate_anthropic("ANTHROPIC_API_KEY", 'Player "Alice"')
    assert result is not None
    assert "ANTHROPIC_API_KEY" in result


def test_validate_anthropic_placeholder_key(monkeypatch):
    """The placeholder value 'YOUR_KEY_HERE' is treated as missing."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "YOUR_KEY_HERE")
    result = _validate_anthropic("ANTHROPIC_API_KEY", 'Player "Alice"')
    assert result is not None
    assert "ANTHROPIC_API_KEY" in result


def test_validate_anthropic_none_env_key_name():
    """None env_key_name returns a configuration error."""
    result = _validate_anthropic(None, 'Player "Alice"')
    assert result is not None
    assert "env_key_name" in result


# ---------------------------------------------------------------------------
# _validate_openai
# ---------------------------------------------------------------------------


def test_validate_openai_valid_key(monkeypatch):
    """A working API key (models.list succeeds) returns None."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-valid-key")
    with patch(f"{_MOD}.OpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.models.list.return_value = MagicMock()
        mock_cls.return_value = mock_client

        result = _validate_openai("OPENAI_API_KEY", 'Player "Bob"')

    assert result is None
    mock_cls.assert_called_once_with(api_key="sk-valid-key")


def test_validate_openai_auth_error(monkeypatch):
    """A 401 from models.list is reported as rejected key."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-bad-key")
    with patch(f"{_MOD}.OpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.models.list.side_effect = _make_auth_error()
        mock_cls.return_value = mock_client

        result = _validate_openai("OPENAI_API_KEY", 'Player "Bob"')

    assert result is not None
    assert "401 Unauthorized" in result
    assert "OPENAI_API_KEY" in result


def test_validate_openai_api_error(monkeypatch):
    """A non-auth API error is reported with a generic message."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-some-key")
    with patch(f"{_MOD}.OpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.models.list.side_effect = _make_api_error()
        mock_cls.return_value = mock_client

        result = _validate_openai("OPENAI_API_KEY", 'Player "Bob"')

    assert result is not None
    assert "openai" in result


def test_validate_openai_missing_key(monkeypatch):
    """Missing env var is caught before any network call."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with patch(f"{_MOD}.OpenAI") as mock_cls:
        result = _validate_openai("OPENAI_API_KEY", 'Player "Bob"')

    mock_cls.assert_not_called()
    assert result is not None
    assert "OPENAI_API_KEY" in result


def test_validate_openai_none_env_key_name():
    """None env_key_name returns a config error without a network call."""
    with patch(f"{_MOD}.OpenAI") as mock_cls:
        result = _validate_openai(None, 'Player "Bob"')

    mock_cls.assert_not_called()
    assert result is not None
    assert "env_key_name" in result


# ---------------------------------------------------------------------------
# _validate_xai
# ---------------------------------------------------------------------------


def test_validate_xai_valid_key(monkeypatch):
    """A working XAI key (models.list succeeds) returns None."""
    monkeypatch.setenv("XAI_API_KEY", "xai-valid-key")
    with patch(f"{_MOD}.OpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.models.list.return_value = MagicMock()
        mock_cls.return_value = mock_client

        result = _validate_xai("XAI_API_KEY", 'Player "Charlie"')

    assert result is None
    mock_cls.assert_called_once_with(
        base_url="https://api.x.ai/v1", api_key="xai-valid-key"
    )


def test_validate_xai_auth_error(monkeypatch):
    """A 401 from XAI is reported as rejected key."""
    monkeypatch.setenv("XAI_API_KEY", "xai-bad-key")
    with patch(f"{_MOD}.OpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.models.list.side_effect = _make_auth_error(
            "https://api.x.ai/v1/models"
        )
        mock_cls.return_value = mock_client

        result = _validate_xai("XAI_API_KEY", 'Player "Charlie"')

    assert result is not None
    assert "401 Unauthorized" in result
    assert "XAI_API_KEY" in result


def test_validate_xai_missing_key(monkeypatch):
    """Missing env var is caught before any network call."""
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    with patch(f"{_MOD}.OpenAI") as mock_cls:
        result = _validate_xai("XAI_API_KEY", 'Player "Charlie"')

    mock_cls.assert_not_called()
    assert result is not None
    assert "XAI_API_KEY" in result


def test_validate_xai_none_env_key_name():
    """None env_key_name returns a configuration error."""
    with patch(f"{_MOD}.OpenAI") as mock_cls:
        result = _validate_xai(None, 'Player "Charlie"')

    mock_cls.assert_not_called()
    assert result is not None
    assert "env_key_name" in result


# ---------------------------------------------------------------------------
# _validate_google
# ---------------------------------------------------------------------------


def test_validate_google_valid_key(monkeypatch):
    """A working Google API key (models.list succeeds) returns None."""
    monkeypatch.setenv("GOOGLE_API_KEY", "AIzaValid")
    with patch(f"{_MOD}.genai") as mock_genai:
        mock_client = MagicMock()
        mock_client.models.list.return_value = []
        mock_genai.Client.return_value = mock_client

        result = _validate_google("GOOGLE_API_KEY", "Judge")

    assert result is None
    mock_genai.Client.assert_called_once_with(api_key="AIzaValid")


def test_validate_google_auth_error(monkeypatch):
    """An auth error from models.list is reported as rejected key."""
    monkeypatch.setenv("GOOGLE_API_KEY", "AIzaBad")
    auth_err = google_errors.ClientError(
        401, {"error": {"message": "API key not valid."}}
    )
    with patch(f"{_MOD}.genai") as mock_genai:
        mock_client = MagicMock()
        mock_client.models.list.side_effect = auth_err
        mock_genai.Client.return_value = mock_client

        result = _validate_google("GOOGLE_API_KEY", "Judge")

    assert result is not None
    assert "API key rejected" in result
    assert "GOOGLE_API_KEY" in result


def test_validate_google_generic_error(monkeypatch):
    """Any exception from models.list is treated as an auth failure."""
    monkeypatch.setenv("GOOGLE_API_KEY", "AIzaSomething")
    with patch(f"{_MOD}.genai") as mock_genai:
        mock_client = MagicMock()
        mock_client.models.list.side_effect = Exception("Unexpected")
        mock_genai.Client.return_value = mock_client

        result = _validate_google("GOOGLE_API_KEY", "Judge")

    assert result is not None
    assert "GOOGLE_API_KEY" in result


def test_validate_google_missing_key(monkeypatch):
    """Missing env var is caught before any network call."""
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with patch(f"{_MOD}.genai") as mock_genai:
        result = _validate_google("GOOGLE_API_KEY", "Judge")

    mock_genai.Client.assert_not_called()
    assert result is not None
    assert "GOOGLE_API_KEY" in result


def test_validate_google_none_env_key_name():
    """None env_key_name returns a configuration error."""
    with patch(f"{_MOD}.genai") as mock_genai:
        result = _validate_google(None, "Judge")

    mock_genai.Client.assert_not_called()
    assert result is not None
    assert "env_key_name" in result


# ---------------------------------------------------------------------------
# _validate_local
# ---------------------------------------------------------------------------


def _local_model_def() -> ModelDefinition:
    return ModelDefinition(
        id="qwen3:32b",
        provider="local",
        api_model_id="http://localhost:11434/v1",
        env_key_name=None,
    )


def test_validate_local_success():
    """A successful completions.create call returns None."""
    model_def = _local_model_def()
    with patch(f"{_MOD}.OpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = MagicMock()
        mock_cls.return_value = mock_client

        result = _validate_local(model_def, 'Player "Chaos"')

    assert result is None
    mock_cls.assert_called_once_with(
        base_url="http://localhost:11434/v1", api_key="local"
    )
    mock_client.chat.completions.create.assert_called_once_with(
        model="qwen3:32b",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=1,
    )


def test_validate_local_connection_error():
    """A connection error is reported with url and model name."""
    model_def = _local_model_def()
    with patch(f"{_MOD}.OpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = (
            _make_connection_error()
        )
        mock_cls.return_value = mock_client

        result = _validate_local(model_def, 'Player "Chaos"')

    assert result is not None
    assert "http://localhost:11434/v1" in result
    assert "qwen3:32b" in result


def test_validate_local_generic_error():
    """Any exception from the endpoint is treated as unreachable."""
    model_def = _local_model_def()
    with patch(f"{_MOD}.OpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception(
            "Model not found"
        )
        mock_cls.return_value = mock_client

        result = _validate_local(model_def, 'Player "Chaos"')

    assert result is not None
    assert "http://localhost:11434/v1" in result
    assert "qwen3:32b" in result


# ---------------------------------------------------------------------------
# validate_startup — integration-style tests using real LLMPlayer/LLMJudge
# with patched ApiClient
# ---------------------------------------------------------------------------


def _make_llm_player(
    name: str = "TestPlayer",
    provider: str = "anthropic",
    personality: str = "friendly",
    env_key_name: str = "ANTHROPIC_API_KEY",
):
    """Create an LLMPlayer with a patched ApiClient (no real network)."""
    from src.nomic_engine.llm.api_clients import ApiClient
    from src.nomic_engine.players.llm_player import LLMPlayer

    model_def = ModelDefinition(
        id="claude-test",
        provider=provider,
        api_model_id="claude-test",
        env_key_name=env_key_name,
    )
    with patch.object(ApiClient, "__init__", return_value=None):
        player = LLMPlayer(name, model_def, personality)
    return player


def _make_llm_judge(
    provider: str = "anthropic",
    env_key_name: str = "ANTHROPIC_API_KEY",
):
    """Create an LLMJudge with a patched ApiClient (no real network)."""
    from src.nomic_engine.judge.llm_judge import LLMJudge
    from src.nomic_engine.llm.api_clients import ApiClient

    model_def = ModelDefinition(
        id="claude-test",
        provider=provider,
        api_model_id="claude-test",
        env_key_name=env_key_name,
    )
    with patch.object(ApiClient, "__init__", return_value=None):
        judge = LLMJudge(model_def)
    return judge


def _make_human_player(name: str = "HumanAlice"):
    from src.nomic_engine.players.human_player import HumanPlayer

    return HumanPlayer(name)


def _make_human_judge():
    from src.nomic_engine.judge.human_judge import HumanJudge

    return HumanJudge()


def test_validate_startup_human_players_and_judge_skipped():
    """Human player and human judge skip all validation (no sys.exit)."""
    player = _make_human_player()
    judge = _make_human_judge()
    game_manager = MagicMock()

    # Should complete without error
    validate_startup([player], judge, game_manager)


def test_validate_startup_valid_llm_player_and_judge(monkeypatch):
    """Valid anthropic keys and existing personality → no exit."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-validkey")

    player = _make_llm_player(personality="friendly")
    judge = _make_llm_judge()
    game_manager = MagicMock()

    validate_startup([player], judge, game_manager)


def test_validate_startup_exits_on_bad_player_api_key(monkeypatch):
    """Invalid player API key causes sys.exit(1)."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "wrong-prefix-key")

    player = _make_llm_player(personality="friendly")
    judge = _make_human_judge()
    game_manager = MagicMock()

    with pytest.raises(SystemExit) as exc_info:
        validate_startup([player], judge, game_manager)

    assert exc_info.value.code == 1


def test_validate_startup_exits_on_missing_personality(monkeypatch, capsys):
    """Missing personality file causes sys.exit(1) with actionable message."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-validkey")

    player = _make_llm_player(personality="nonexistent_personality_xyz")
    judge = _make_human_judge()
    game_manager = MagicMock()

    with pytest.raises(SystemExit) as exc_info:
        validate_startup([player], judge, game_manager)

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "personality file not found" in captured.err
    assert "nonexistent_personality_xyz" in captured.err


def test_validate_startup_exits_on_bad_judge_api_key(monkeypatch):
    """Invalid judge API key causes sys.exit(1)."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-validkey")
    monkeypatch.setenv("JUDGE_API_KEY", "wrong-prefix-key")

    player = _make_llm_player(personality="friendly")
    judge = _make_llm_judge(env_key_name="JUDGE_API_KEY")
    game_manager = MagicMock()

    with pytest.raises(SystemExit) as exc_info:
        validate_startup([player], judge, game_manager)

    assert exc_info.value.code == 1


def test_validate_startup_fail_fast_stops_at_first_error(monkeypatch, capsys):
    """Two invalid players: only the first error is reported (fail-fast)."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "wrong-prefix")

    player1 = _make_llm_player(name="Alice", personality="friendly")
    player2 = _make_llm_player(name="Bob", personality="friendly")
    judge = _make_human_judge()
    game_manager = MagicMock()

    with pytest.raises(SystemExit) as exc_info:
        validate_startup([player1, player2], judge, game_manager)

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    # Only Alice's error should appear, not Bob's
    assert "Alice" in captured.err
    assert "Bob" not in captured.err


def test_validate_startup_personality_checked_after_api_key(monkeypatch):
    """Personality check is skipped when the API key already fails."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "wrong-prefix")

    # Nonexistent personality — API key check must fail first
    player = _make_llm_player(personality="nonexistent_xyz")
    judge = _make_human_judge()
    game_manager = MagicMock()

    with pytest.raises(SystemExit) as exc_info:
        validate_startup([player], judge, game_manager)

    assert exc_info.value.code == 1


def test_validate_startup_openai_live_check_called(monkeypatch):
    """For openai players, models.list() is called to verify the key."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-live-key")

    player = _make_llm_player(provider="openai", env_key_name="OPENAI_API_KEY")
    judge = _make_human_judge()
    game_manager = MagicMock()

    with patch(f"{_MOD}.OpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.models.list.return_value = MagicMock()
        mock_cls.return_value = mock_client

        validate_startup([player], judge, game_manager)

    mock_client.models.list.assert_called_once()


def test_validate_startup_human_player_mixed_with_llm(monkeypatch):
    """Human player is skipped; only LLM player is validated."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-validkey")

    human = _make_human_player("Alice")
    llm = _make_llm_player(name="Bob", personality="friendly")
    judge = _make_human_judge()
    game_manager = MagicMock()

    # Should pass without error
    validate_startup([human, llm], judge, game_manager)
