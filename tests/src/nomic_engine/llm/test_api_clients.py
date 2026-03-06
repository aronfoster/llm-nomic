"""
Unit tests for the API client classes and create_api_client factory.
"""

from unittest.mock import MagicMock, patch

import pytest
from google.genai import types as google_types
from openai import OpenAIError

from src.nomic_engine.data_models import (
    ChatMessage,
    ModelDefinition,
)
from src.nomic_engine.llm.api_clients import (
    AnthropicApiClient,
    GoogleApiClient,
    OpenAICompatibleApiClient,
    create_api_client,
)

# ---------------------------------------------------------------------------
# OpenAICompatibleApiClient – construction
# ---------------------------------------------------------------------------


def test_openai_compatible_local_provider():
    """OpenAICompatibleApiClient initializes for local (Ollama) provider."""
    mock_model_def = ModelDefinition(
        id="llama2",
        provider="local",
        api_model_id="http://localhost:11434/v1",
        env_key_name=None,
    )

    with patch("src.nomic_engine.llm.api_clients.OpenAI") as mock_openai:
        api_client = OpenAICompatibleApiClient(mock_model_def)

        mock_openai.assert_called_once_with(
            base_url="http://localhost:11434/v1", api_key="local"
        )
        assert api_client.model_config == mock_model_def


def test_openai_compatible_openai_provider(monkeypatch):
    """OpenAICompatibleApiClient initializes correctly for openai provider."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")

    mock_model_def = ModelDefinition(
        id="gpt-5.1",
        provider="openai",
        api_model_id="gpt-5.1",
        env_key_name="OPENAI_API_KEY",
    )

    with patch("src.nomic_engine.llm.api_clients.OpenAI") as mock_openai:
        api_client = OpenAICompatibleApiClient(mock_model_def)

        mock_openai.assert_called_once_with(api_key="test-openai-key")
        assert api_client.model_id_for_api == "gpt-5.1"
        assert api_client.model_config == mock_model_def


def test_openai_compatible_xai_provider(monkeypatch):
    """OpenAICompatibleApiClient initializes correctly for xai provider."""
    monkeypatch.setenv("XAI_API_KEY", "secret-key")

    mock_model_def = ModelDefinition(
        id="grok-4-1-fast-reasoning",
        provider="xai",
        api_model_id="grok-4-1-fast-reasoning",
        env_key_name="XAI_API_KEY",
    )

    with patch("src.nomic_engine.llm.api_clients.OpenAI") as mock_openai:
        api_client = OpenAICompatibleApiClient(mock_model_def)

        mock_openai.assert_called_once_with(
            base_url="https://api.x.ai/v1", api_key="secret-key"
        )
        assert api_client.model_id_for_api == "grok-4-1-fast-reasoning"
        assert api_client.model_config == mock_model_def


def test_openai_compatible_xai_missing_key(monkeypatch):
    """OpenAICompatibleApiClient raises ValueError when xai key is missing."""
    monkeypatch.delenv("XAI_API_KEY", raising=False)

    mock_model_def = ModelDefinition(
        id="grok-4-1-fast-reasoning",
        provider="xai",
        api_model_id="grok-4-1-fast-reasoning",
        env_key_name="XAI_API_KEY",
    )

    with pytest.raises(ValueError) as exc_info:
        OpenAICompatibleApiClient(mock_model_def)

    assert "API key 'XAI_API_KEY' not found in environment variables" in str(
        exc_info.value
    )


# ---------------------------------------------------------------------------
# AnthropicApiClient – construction
# ---------------------------------------------------------------------------


def test_anthropic_api_client_provider(monkeypatch):
    """AnthropicApiClient initializes correctly for anthropic provider."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")

    mock_model_def = ModelDefinition(
        id="claude-sonnet-4-5",
        provider="anthropic",
        api_model_id="claude-sonnet-4-5",
        env_key_name="ANTHROPIC_API_KEY",
    )

    with patch(
        "src.nomic_engine.llm.api_clients.anthropic.Anthropic"
    ) as mock_anthropic:
        api_client = AnthropicApiClient(mock_model_def)

        mock_anthropic.assert_called_once_with(api_key="test-anthropic-key")
        assert api_client.model_id_for_api == "claude-sonnet-4-5"
        assert api_client.model_config == mock_model_def


# ---------------------------------------------------------------------------
# GoogleApiClient – construction
# ---------------------------------------------------------------------------


def test_google_api_client_provider(monkeypatch):
    """GoogleApiClient initializes correctly for google provider."""
    monkeypatch.setenv("GOOGLE_API_KEY", "test-google-key")

    mock_model_def = ModelDefinition(
        id="gemini-2.5-pro",
        provider="google",
        api_model_id="gemini-2.5-pro",
        env_key_name="GOOGLE_API_KEY",
    )

    with patch(
        "src.nomic_engine.llm.api_clients.genai.Client"
    ) as mock_client_class:
        api_client = GoogleApiClient(mock_model_def)

        mock_client_class.assert_called_once_with(api_key="test-google-key")
        assert api_client.model_id_for_api == "gemini-2.5-pro"
        assert api_client.model_config == mock_model_def


# ---------------------------------------------------------------------------
# create_api_client – factory dispatch and class types
# ---------------------------------------------------------------------------


def test_create_api_client_local_returns_openai_compatible():
    """create_api_client returns OpenAICompatibleApiClient for local."""
    mock_model_def = ModelDefinition(
        id="llama2",
        provider="local",
        api_model_id="http://localhost:11434/v1",
        env_key_name=None,
    )

    with patch("src.nomic_engine.llm.api_clients.OpenAI"):
        client = create_api_client(mock_model_def)

    assert isinstance(client, OpenAICompatibleApiClient)


def test_create_api_client_openai_returns_openai_compatible(monkeypatch):
    """create_api_client returns OpenAICompatibleApiClient for openai."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    mock_model_def = ModelDefinition(
        id="gpt-5.1",
        provider="openai",
        api_model_id="gpt-5.1",
        env_key_name="OPENAI_API_KEY",
    )

    with patch("src.nomic_engine.llm.api_clients.OpenAI"):
        client = create_api_client(mock_model_def)

    assert isinstance(client, OpenAICompatibleApiClient)


def test_create_api_client_xai_returns_openai_compatible(monkeypatch):
    """create_api_client returns OpenAICompatibleApiClient for xai provider."""
    monkeypatch.setenv("XAI_API_KEY", "secret-key")

    mock_model_def = ModelDefinition(
        id="grok-4-1-fast-reasoning",
        provider="xai",
        api_model_id="grok-4-1-fast-reasoning",
        env_key_name="XAI_API_KEY",
    )

    with patch("src.nomic_engine.llm.api_clients.OpenAI"):
        client = create_api_client(mock_model_def)

    assert isinstance(client, OpenAICompatibleApiClient)


def test_create_api_client_anthropic_returns_anthropic_client(monkeypatch):
    """create_api_client returns AnthropicApiClient for anthropic provider."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    mock_model_def = ModelDefinition(
        id="claude-sonnet-4-5",
        provider="anthropic",
        api_model_id="claude-sonnet-4-5",
        env_key_name="ANTHROPIC_API_KEY",
    )

    with patch("src.nomic_engine.llm.api_clients.anthropic.Anthropic"):
        client = create_api_client(mock_model_def)

    assert isinstance(client, AnthropicApiClient)


def test_create_api_client_google_returns_google_client(monkeypatch):
    """create_api_client returns GoogleApiClient for google provider."""
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")

    mock_model_def = ModelDefinition(
        id="gemini-2.5-pro",
        provider="google",
        api_model_id="gemini-2.5-pro",
        env_key_name="GOOGLE_API_KEY",
    )

    with patch("src.nomic_engine.llm.api_clients.genai.Client"):
        client = create_api_client(mock_model_def)

    assert isinstance(client, GoogleApiClient)


def test_create_api_client_unknown_provider_raises_error():
    """create_api_client raises ValueError for unknown provider."""
    mock_model_def = ModelDefinition(
        id="test-unknown",
        provider="unknown_provider",
        api_model_id="some-model",
        env_key_name=None,
    )

    with pytest.raises(ValueError) as exc_info:
        create_api_client(mock_model_def)

    assert "Unknown provider: unknown_provider" in str(exc_info.value)


# ---------------------------------------------------------------------------
# OpenAICompatibleApiClient – get_completion
# ---------------------------------------------------------------------------


def test_get_completion_local_success():
    """Successful completion from local (Ollama) provider."""
    mock_model_def = ModelDefinition(
        id="llama2",
        provider="local",
        api_model_id="http://localhost:11434/v1",
        env_key_name=None,
    )

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "This is a test response"

    with patch("src.nomic_engine.llm.api_clients.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_http_response = MagicMock()
        mock_http_response.parse.return_value = mock_response
        mock_client.chat.completions.with_raw_response.create.return_value = (
            mock_http_response
        )
        mock_openai.return_value = mock_client

        api_client = OpenAICompatibleApiClient(mock_model_def)

        messages = [
            ChatMessage(role="system", content="You are a helpful assistant."),
            ChatMessage(role="user", content="Hello!"),
        ]

        result = api_client.get_completion(messages)

        mock_client.chat.completions.with_raw_response.create.assert_called_once_with(
            model="llama2",
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Hello!"},
            ],
        )
        assert result.text == "This is a test response"


def test_get_completion_xai_uses_api_model_id(monkeypatch):
    """Successful completion uses the API model ID for xai provider."""
    monkeypatch.setenv("XAI_API_KEY", "secret-key")

    mock_model_def = ModelDefinition(
        id="grok-friendly",
        provider="xai",
        api_model_id="grok-4-1-fast-reasoning",
        env_key_name="XAI_API_KEY",
    )

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "Grok says hello"

    with patch("src.nomic_engine.llm.api_clients.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_http_response = MagicMock()
        mock_http_response.parse.return_value = mock_response
        mock_client.chat.completions.with_raw_response.create.return_value = (
            mock_http_response
        )
        mock_openai.return_value = mock_client

        api_client = OpenAICompatibleApiClient(mock_model_def)

        result = api_client.get_completion(
            [ChatMessage(role="user", content="Hello!")]
        )

        mock_client.chat.completions.with_raw_response.create.assert_called_once_with(
            model="grok-4-1-fast-reasoning",
            messages=[{"role": "user", "content": "Hello!"}],
        )
        assert result.text == "Grok says hello"


def test_get_completion_openai_compatible_openai_error():
    """OpenAICompatibleApiClient handles OpenAIError gracefully."""
    mock_model_def = ModelDefinition(
        id="llama2",
        provider="local",
        api_model_id="http://localhost:11434/v1",
        env_key_name=None,
    )

    with patch("src.nomic_engine.llm.api_clients.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_client.chat.completions.with_raw_response.create.side_effect = (
            OpenAIError("Connection error")
        )
        mock_openai.return_value = mock_client

        api_client = OpenAICompatibleApiClient(mock_model_def)
        result = api_client.get_completion(
            [ChatMessage(role="user", content="Hello!")]
        )
        assert result.text is None


def test_get_completion_openai_success(monkeypatch):
    """Successful completion from OpenAI provider."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    mock_model_def = ModelDefinition(
        id="gpt-5.1",
        provider="openai",
        api_model_id="gpt-5.1",
        env_key_name="OPENAI_API_KEY",
    )

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "OpenAI response"

    with patch("src.nomic_engine.llm.api_clients.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_http_response = MagicMock()
        mock_http_response.parse.return_value = mock_response
        mock_client.chat.completions.with_raw_response.create.return_value = (
            mock_http_response
        )
        mock_openai.return_value = mock_client

        api_client = OpenAICompatibleApiClient(mock_model_def)

        messages = [
            ChatMessage(role="system", content="You are helpful."),
            ChatMessage(role="user", content="Hello!"),
        ]

        result = api_client.get_completion(messages)

        mock_client.chat.completions.with_raw_response.create.assert_called_once_with(
            model="gpt-5.1",
            messages=[
                {"role": "system", "content": "You are helpful."},
                {"role": "user", "content": "Hello!"},
            ],
        )
        assert result.text == "OpenAI response"


def test_get_completion_openai_error(monkeypatch):
    """OpenAI provider handles errors gracefully."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    mock_model_def = ModelDefinition(
        id="gpt-5.1",
        provider="openai",
        api_model_id="gpt-5.1",
        env_key_name="OPENAI_API_KEY",
    )

    with patch("src.nomic_engine.llm.api_clients.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_client.chat.completions.with_raw_response.create.side_effect = (
            OpenAIError("API error")
        )
        mock_openai.return_value = mock_client

        api_client = OpenAICompatibleApiClient(mock_model_def)
        result = api_client.get_completion(
            [ChatMessage(role="user", content="Hello!")]
        )
        assert result.text is None


# ---------------------------------------------------------------------------
# AnthropicApiClient – get_completion
# ---------------------------------------------------------------------------


def test_get_completion_anthropic_success(monkeypatch):
    """Successful completion from Anthropic provider."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    mock_model_def = ModelDefinition(
        id="claude-sonnet-4-5",
        provider="anthropic",
        api_model_id="claude-sonnet-4-5",
        env_key_name="ANTHROPIC_API_KEY",
    )

    mock_text_block = MagicMock()
    mock_text_block.text = "Anthropic response"
    mock_response = MagicMock()
    mock_response.content = [mock_text_block]

    with patch(
        "src.nomic_engine.llm.api_clients.anthropic.Anthropic"
    ) as mock_anthropic_class:
        mock_client = MagicMock()
        mock_http_response = MagicMock()
        mock_http_response.parse.return_value = mock_response
        mock_client.messages.with_raw_response.create.return_value = (
            mock_http_response
        )
        mock_anthropic_class.return_value = mock_client

        api_client = AnthropicApiClient(mock_model_def)

        messages = [
            ChatMessage(role="system", content="You are helpful."),
            ChatMessage(role="user", content="Hello!"),
            ChatMessage(role="assistant", content="Hi there!"),
            ChatMessage(role="user", content="How are you?"),
        ]

        result = api_client.get_completion(messages)

        call_args = mock_client.messages.with_raw_response.create.call_args
        assert call_args.kwargs["model"] == "claude-sonnet-4-5"
        assert call_args.kwargs["max_tokens"] == 8192
        assert call_args.kwargs["cache_control"] == {"type": "ephemeral"}
        assert call_args.kwargs["system"] == "You are helpful."
        assert call_args.kwargs["messages"] == [
            {"role": "user", "content": "Hello!"},
            {"role": "assistant", "content": "Hi there!"},
            {"role": "user", "content": "How are you?"},
        ]
        assert result.text == "Anthropic response"


def test_get_completion_anthropic_no_system(monkeypatch):
    """Anthropic completion without system message."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    mock_model_def = ModelDefinition(
        id="claude-sonnet-4-5",
        provider="anthropic",
        api_model_id="claude-sonnet-4-5",
        env_key_name="ANTHROPIC_API_KEY",
    )

    mock_text_block = MagicMock()
    mock_text_block.text = "Response"
    mock_response = MagicMock()
    mock_response.content = [mock_text_block]

    with patch(
        "src.nomic_engine.llm.api_clients.anthropic.Anthropic"
    ) as mock_anthropic_class:
        mock_client = MagicMock()
        mock_http_response = MagicMock()
        mock_http_response.parse.return_value = mock_response
        mock_client.messages.with_raw_response.create.return_value = (
            mock_http_response
        )
        mock_anthropic_class.return_value = mock_client

        api_client = AnthropicApiClient(mock_model_def)
        result = api_client.get_completion(
            [ChatMessage(role="user", content="Hello!")]
        )

        call_args = mock_client.messages.with_raw_response.create.call_args
        assert "system" not in call_args.kwargs
        assert call_args.kwargs["cache_control"] == {"type": "ephemeral"}
        assert result.text == "Response"


def test_get_completion_anthropic_automatic_cache_control_always_sent(
    monkeypatch,
):
    """cache_control is sent by default (default path)."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    mock_model_def = ModelDefinition(
        id="claude-sonnet-4-5",
        provider="anthropic",
        api_model_id="claude-sonnet-4-5",
        env_key_name="ANTHROPIC_API_KEY",
    )

    mock_text_block = MagicMock()
    mock_text_block.text = "Cached response"
    mock_response = MagicMock()
    mock_response.content = [mock_text_block]

    with patch(
        "src.nomic_engine.llm.api_clients.anthropic.Anthropic"
    ) as mock_anthropic_class:
        mock_client = MagicMock()
        mock_http_response = MagicMock()
        mock_http_response.parse.return_value = mock_response
        mock_client.messages.with_raw_response.create.return_value = (
            mock_http_response
        )
        mock_anthropic_class.return_value = mock_client

        api_client = AnthropicApiClient(mock_model_def)

        # With system message — default path sends cache_control
        api_client.get_completion(
            [
                ChatMessage(role="system", content="System prompt."),
                ChatMessage(role="user", content="Hello!"),
            ]
        )
        call_args = mock_client.messages.with_raw_response.create.call_args
        assert call_args.kwargs["cache_control"] == {"type": "ephemeral"}
        assert call_args.kwargs["system"] == "System prompt."

        # Without system message — default path still sends cache_control
        api_client.get_completion([ChatMessage(role="user", content="Hello!")])
        call_args = mock_client.messages.with_raw_response.create.call_args
        assert call_args.kwargs["cache_control"] == {"type": "ephemeral"}
        assert "system" not in call_args.kwargs


def test_get_completion_anthropic_opt_out_omits_cache_control(
    monkeypatch,
):
    """cache_control is absent when use_cache_control=False (opt-out path)."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    mock_model_def = ModelDefinition(
        id="claude-sonnet-4-5",
        provider="anthropic",
        api_model_id="claude-sonnet-4-5",
        env_key_name="ANTHROPIC_API_KEY",
    )

    mock_text_block = MagicMock()
    mock_text_block.text = "Response without cache write"
    mock_response = MagicMock()
    mock_response.content = [mock_text_block]

    with patch(
        "src.nomic_engine.llm.api_clients.anthropic.Anthropic"
    ) as mock_anthropic_class:
        mock_client = MagicMock()
        mock_http_response = MagicMock()
        mock_http_response.parse.return_value = mock_response
        mock_client.messages.with_raw_response.create.return_value = (
            mock_http_response
        )
        mock_anthropic_class.return_value = mock_client

        api_client = AnthropicApiClient(mock_model_def)

        # With system message — opt-out path omits cache_control
        result = api_client.get_completion(
            [
                ChatMessage(role="system", content="System prompt."),
                ChatMessage(role="user", content="Hello!"),
            ],
            use_cache_control=False,
        )
        call_args = mock_client.messages.with_raw_response.create.call_args
        assert "cache_control" not in call_args.kwargs
        assert call_args.kwargs["system"] == "System prompt."
        assert result.text == "Response without cache write"

        # Without system message — opt-out path omits cache_control
        api_client.get_completion(
            [ChatMessage(role="user", content="Hello!")],
            use_cache_control=False,
        )
        call_args = mock_client.messages.with_raw_response.create.call_args
        assert "cache_control" not in call_args.kwargs
        assert "system" not in call_args.kwargs


def test_get_completion_anthropic_error(monkeypatch):
    """Anthropic provider handles errors gracefully."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    mock_model_def = ModelDefinition(
        id="claude-sonnet-4-5",
        provider="anthropic",
        api_model_id="claude-sonnet-4-5",
        env_key_name="ANTHROPIC_API_KEY",
    )

    with patch(
        "src.nomic_engine.llm.api_clients.anthropic.Anthropic"
    ) as mock_anthropic_class:
        mock_client = MagicMock()
        mock_client.messages.with_raw_response.create.side_effect = Exception(
            "Anthropic API error"
        )
        mock_anthropic_class.return_value = mock_client

        api_client = AnthropicApiClient(mock_model_def)
        result = api_client.get_completion(
            [ChatMessage(role="user", content="Hello!")]
        )
        assert result.text is None


# ---------------------------------------------------------------------------
# GoogleApiClient – get_completion
# ---------------------------------------------------------------------------


def test_get_completion_google_success(monkeypatch):
    """Successful completion from Google provider."""
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")

    mock_model_def = ModelDefinition(
        id="gemini-2.5-pro",
        provider="google",
        api_model_id="gemini-2.5-pro",
        env_key_name="GOOGLE_API_KEY",
    )

    mock_response = MagicMock()
    mock_response.text = "Google response"

    with patch(
        "src.nomic_engine.llm.api_clients.genai.Client"
    ) as mock_client_class:
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        mock_client_class.return_value = mock_client

        api_client = GoogleApiClient(mock_model_def)

        messages = [
            ChatMessage(role="system", content="You are helpful."),
            ChatMessage(role="user", content="Hello!"),
            ChatMessage(role="assistant", content="Hi there!"),
            ChatMessage(role="user", content="How are you?"),
        ]

        result = api_client.get_completion(messages)

        call_args = mock_client.models.generate_content.call_args
        expected_messages = [
            google_types.Content(
                role="user",
                parts=[google_types.Part(text="Hello!")],
            ),
            google_types.Content(
                role="model",
                parts=[google_types.Part(text="Hi there!")],
            ),
            google_types.Content(
                role="user",
                parts=[google_types.Part(text="How are you?")],
            ),
        ]
        assert call_args.kwargs["model"] == "gemini-2.5-pro"
        assert call_args.kwargs["contents"] == expected_messages
        assert call_args.kwargs["config"] == {
            "system_instruction": "You are helpful.",
        }
        assert result.text == "Google response"


def test_get_completion_google_error(monkeypatch):
    """Google provider handles errors gracefully."""
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")

    mock_model_def = ModelDefinition(
        id="gemini-2.5-pro",
        provider="google",
        api_model_id="gemini-2.5-pro",
        env_key_name="GOOGLE_API_KEY",
    )

    with patch(
        "src.nomic_engine.llm.api_clients.genai.Client"
    ) as mock_client_class:
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception(
            "API error"
        )
        mock_client_class.return_value = mock_client

        api_client = GoogleApiClient(mock_model_def)
        result = api_client.get_completion(
            [ChatMessage(role="user", content="Hello!")]
        )
        assert result.text is None


def test_get_completion_google_system_messages_use_system_instruction(
    monkeypatch,
):
    """Gemini system messages are not serialized as user messages."""
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")

    mock_model_def = ModelDefinition(
        id="gemini-2.5-pro",
        provider="google",
        api_model_id="gemini-2.5-pro",
        env_key_name="GOOGLE_API_KEY",
    )

    mock_response = MagicMock()
    mock_response.text = "Google response"

    with patch(
        "src.nomic_engine.llm.api_clients.genai.Client"
    ) as mock_client_class:
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        mock_client_class.return_value = mock_client

        api_client = GoogleApiClient(mock_model_def)

        messages = [
            ChatMessage(role="system", content="System 1"),
            ChatMessage(role="system", content="System 2"),
            ChatMessage(role="user", content="First user message"),
        ]

        result = api_client.get_completion(messages)

        call_args = mock_client.models.generate_content.call_args
        assert call_args.kwargs["contents"] == [
            google_types.Content(
                role="user",
                parts=[google_types.Part(text="First user message")],
            ),
        ]
        assert call_args.kwargs["config"] == {
            "system_instruction": "System 1\n\nSystem 2"
        }
        assert result.text == "Google response"


def test_get_completion_google_system_only_falls_back_to_user_message(
    monkeypatch,
):
    """Google falls back when only system messages exist."""
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")

    mock_model_def = ModelDefinition(
        id="gemini-2.5-pro",
        provider="google",
        api_model_id="gemini-2.5-pro",
        env_key_name="GOOGLE_API_KEY",
    )

    mock_response = MagicMock()
    mock_response.text = "Google response"

    with patch(
        "src.nomic_engine.llm.api_clients.genai.Client"
    ) as mock_client_class:
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        mock_client_class.return_value = mock_client

        api_client = GoogleApiClient(mock_model_def)

        messages = [
            ChatMessage(role="system", content="You are a helpful assistant."),
        ]

        result = api_client.get_completion(messages)

        call_args = mock_client.models.generate_content.call_args
        assert call_args.kwargs["contents"] == [
            google_types.Content(
                role="user",
                parts=[google_types.Part(text="You are a helpful assistant.")],
            ),
        ]
        assert call_args.kwargs["config"] is None
        assert result.text == "Google response"
