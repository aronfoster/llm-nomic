"""
Unit tests for the ApiClient class.
"""

from unittest.mock import MagicMock, patch

import pytest
from openai import OpenAIError

from src.nomic_engine.data_models import ChatMessage, ModelDefinition
from src.nomic_engine.llm.api_clients import ApiClient


def test_api_client_local_provider():
    """Test ApiClient initializes correctly for local (Ollama) provider."""
    # Create a mock local ModelDefinition
    mock_model_def = ModelDefinition(
        id="llama2",
        provider="local",
        api_model_id="http://localhost:11434/v1",
        env_key_name=None,
    )

    # Patch the OpenAI client
    with patch("src.nomic_engine.llm.api_clients.OpenAI") as mock_openai:
        # Instantiate ApiClient
        api_client = ApiClient(mock_model_def)

        # Assert OpenAI was called with correct parameters
        mock_openai.assert_called_once_with(
            base_url="http://localhost:11434/v1", api_key="local"
        )
        assert api_client.model_config == mock_model_def


def test_api_client_openai_provider(monkeypatch):
    """Test ApiClient initializes correctly for openai provider."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")

    mock_model_def = ModelDefinition(
        id="gpt-5.1",
        provider="openai",
        api_model_id="gpt-5.1",
        env_key_name="OPENAI_API_KEY",
    )

    with patch("src.nomic_engine.llm.api_clients.OpenAI") as mock_openai:
        api_client = ApiClient(mock_model_def)

        mock_openai.assert_called_once_with(api_key="test-openai-key")
        assert api_client.model_id_for_api == "gpt-5.1"
        assert api_client.model_config == mock_model_def


def test_api_client_anthropic_provider(monkeypatch):
    """Test ApiClient initializes correctly for anthropic provider."""
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
        api_client = ApiClient(mock_model_def)

        mock_anthropic.assert_called_once_with(api_key="test-anthropic-key")
        assert api_client.model_id_for_api == "claude-sonnet-4-5"
        assert api_client.model_config == mock_model_def


def test_api_client_google_provider(monkeypatch):
    """Test ApiClient initializes correctly for google provider."""
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
        api_client = ApiClient(mock_model_def)

        mock_client_class.assert_called_once_with(api_key="test-google-key")
        assert api_client.model_id_for_api == "gemini-2.5-pro"
        assert api_client.model_config == mock_model_def


def test_api_client_xai_provider(monkeypatch):
    """Test ApiClient initializes correctly for xai provider."""
    monkeypatch.setenv("XAI_API_KEY", "secret-key")

    mock_model_def = ModelDefinition(
        id="grok-4-1-fast-reasoning",
        provider="xai",
        api_model_id="grok-4-1-fast-reasoning",
        env_key_name="XAI_API_KEY",
    )

    with patch("src.nomic_engine.llm.api_clients.OpenAI") as mock_openai:
        api_client = ApiClient(mock_model_def)

        mock_openai.assert_called_once_with(
            base_url="https://api.x.ai/v1", api_key="secret-key"
        )
        assert api_client.model_id_for_api == "grok-4-1-fast-reasoning"
        assert api_client.model_config == mock_model_def


def test_api_client_xai_provider_missing_key(monkeypatch):
    """Test xai provider raises ValueError when API key is missing."""
    monkeypatch.delenv("XAI_API_KEY", raising=False)

    mock_model_def = ModelDefinition(
        id="grok-4-1-fast-reasoning",
        provider="xai",
        api_model_id="grok-4-1-fast-reasoning",
        env_key_name="XAI_API_KEY",
    )

    with pytest.raises(ValueError) as exc_info:
        ApiClient(mock_model_def)

    assert "API key 'XAI_API_KEY' not found in environment variables" in str(
        exc_info.value
    )


def test_api_client_unknown_provider_raises_error():
    """Test that an unknown provider raises ValueError."""
    mock_model_def = ModelDefinition(
        id="test-unknown",
        provider="unknown_provider",
        api_model_id="some-model",
        env_key_name=None,
    )

    with pytest.raises(ValueError) as exc_info:
        ApiClient(mock_model_def)

    assert "Unknown provider: unknown_provider" in str(exc_info.value)


def test_get_completion_success():
    """Test successful completion from ApiClient."""
    # Create a mock local ModelDefinition
    mock_model_def = ModelDefinition(
        id="llama2",
        provider="local",
        api_model_id="http://localhost:11434/v1",
        env_key_name=None,
    )

    # Create mock response
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "This is a test response"

    with patch("src.nomic_engine.llm.api_clients.OpenAI") as mock_openai:
        # Setup mock client
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client

        # Instantiate ApiClient
        api_client = ApiClient(mock_model_def)

        # Create test messages
        messages = [
            ChatMessage(role="system", content="You are a helpful assistant."),
            ChatMessage(role="user", content="Hello!"),
        ]

        # Call get_completion
        result = api_client.get_completion(messages)

        # Assert the client method was called with correct parameters
        mock_client.chat.completions.create.assert_called_once_with(
            model="llama2",
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Hello!"},
            ],
        )

        # Assert the result is correct
        assert result == "This is a test response"


def test_get_completion_success_xai(monkeypatch):
    """Test successful completion uses the API model ID for xai provider."""
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
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client

        api_client = ApiClient(mock_model_def)

        result = api_client.get_completion(
            [ChatMessage(role="user", content="Hello!")]
        )

        mock_client.chat.completions.create.assert_called_once_with(
            model="grok-4-1-fast-reasoning",
            messages=[{"role": "user", "content": "Hello!"}],
        )
        assert result == "Grok says hello"


def test_get_completion_failure():
    """Test that get_completion handles OpenAIError gracefully."""
    # Create a mock local ModelDefinition
    mock_model_def = ModelDefinition(
        id="llama2",
        provider="local",
        api_model_id="http://localhost:11434/v1",
        env_key_name=None,
    )

    with patch("src.nomic_engine.llm.api_clients.OpenAI") as mock_openai:
        # Setup mock client to raise OpenAIError
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = OpenAIError(
            "Connection error"
        )
        mock_openai.return_value = mock_client

        # Instantiate ApiClient
        api_client = ApiClient(mock_model_def)

        # Create test messages
        messages = [ChatMessage(role="user", content="Hello!")]

        # Call get_completion and assert it returns None
        result = api_client.get_completion(messages)
        assert result is None


def test_get_completion_openai_success(monkeypatch):
    """Test successful completion from OpenAI provider."""
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
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client

        api_client = ApiClient(mock_model_def)

        messages = [
            ChatMessage(role="system", content="You are helpful."),
            ChatMessage(role="user", content="Hello!"),
        ]

        result = api_client.get_completion(messages)

        mock_client.chat.completions.create.assert_called_once_with(
            model="gpt-5.1",
            messages=[
                {"role": "system", "content": "You are helpful."},
                {"role": "user", "content": "Hello!"},
            ],
        )
        assert result == "OpenAI response"


def test_get_completion_openai_error(monkeypatch):
    """Test that OpenAI provider handles errors gracefully."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    mock_model_def = ModelDefinition(
        id="gpt-5.1",
        provider="openai",
        api_model_id="gpt-5.1",
        env_key_name="OPENAI_API_KEY",
    )

    with patch("src.nomic_engine.llm.api_clients.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = OpenAIError(
            "API error"
        )
        mock_openai.return_value = mock_client

        api_client = ApiClient(mock_model_def)
        messages = [ChatMessage(role="user", content="Hello!")]

        result = api_client.get_completion(messages)
        assert result is None


def test_get_completion_anthropic_success(monkeypatch):
    """Test successful completion from Anthropic provider."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    mock_model_def = ModelDefinition(
        id="claude-sonnet-4-5",
        provider="anthropic",
        api_model_id="claude-sonnet-4-5",
        env_key_name="ANTHROPIC_API_KEY",
    )

    # Mock Anthropic response
    mock_text_block = MagicMock()
    mock_text_block.text = "Anthropic response"
    mock_response = MagicMock()
    mock_response.content = [mock_text_block]

    with patch(
        "src.nomic_engine.llm.api_clients.anthropic.Anthropic"
    ) as mock_anthropic_class:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_anthropic_class.return_value = mock_client

        api_client = ApiClient(mock_model_def)

        messages = [
            ChatMessage(role="system", content="You are helpful."),
            ChatMessage(role="user", content="Hello!"),
            ChatMessage(role="assistant", content="Hi there!"),
            ChatMessage(role="user", content="How are you?"),
        ]

        result = api_client.get_completion(messages)

        # Verify system message was extracted and non-system messages passed
        call_args = mock_client.messages.create.call_args
        assert call_args.kwargs["model"] == "claude-sonnet-4-5"
        assert call_args.kwargs["max_tokens"] == 8192
        assert call_args.kwargs["system"] == "You are helpful."
        assert call_args.kwargs["messages"] == [
            {"role": "user", "content": "Hello!"},
            {"role": "assistant", "content": "Hi there!"},
            {"role": "user", "content": "How are you?"},
        ]
        assert result == "Anthropic response"


def test_get_completion_anthropic_no_system(monkeypatch):
    """Test Anthropic completion without system message."""
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
        mock_client.messages.create.return_value = mock_response
        mock_anthropic_class.return_value = mock_client

        api_client = ApiClient(mock_model_def)

        messages = [ChatMessage(role="user", content="Hello!")]

        result = api_client.get_completion(messages)

        # Verify no system parameter when no system messages
        call_args = mock_client.messages.create.call_args
        assert "system" not in call_args.kwargs
        assert result == "Response"


def test_get_completion_anthropic_error(monkeypatch):
    """Test that Anthropic provider handles errors gracefully."""
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
        # Use generic Exception for testing error handling
        mock_client.messages.create.side_effect = Exception(
            "Anthropic API error"
        )
        mock_anthropic_class.return_value = mock_client

        api_client = ApiClient(mock_model_def)
        messages = [ChatMessage(role="user", content="Hello!")]

        result = api_client.get_completion(messages)
        assert result is None


def test_get_completion_google_success(monkeypatch):
    """Test successful completion from Google provider."""
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

        api_client = ApiClient(mock_model_def)

        messages = [
            ChatMessage(role="system", content="You are helpful."),
            ChatMessage(role="user", content="Hello!"),
            ChatMessage(role="assistant", content="Hi there!"),
            ChatMessage(role="user", content="How are you?"),
        ]

        result = api_client.get_completion(messages)

        # Verify message format conversion and API call
        call_args = mock_client.models.generate_content.call_args
        expected_messages = [
            {"role": "user", "parts": ["Hello!"]},
            {"role": "model", "parts": ["Hi there!"]},
            {"role": "user", "parts": ["How are you?"]},
        ]
        assert call_args.kwargs["model"] == "gemini-2.5-pro"
        assert call_args.kwargs["contents"] == expected_messages
        assert call_args.kwargs["config"] == {
            "system_instruction": "You are helpful.",
        }
        assert result == "Google response"


def test_get_completion_google_error(monkeypatch):
    """Test that Google provider handles errors gracefully."""
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

        api_client = ApiClient(mock_model_def)
        messages = [ChatMessage(role="user", content="Hello!")]

        result = api_client.get_completion(messages)
        assert result is None


def test_get_completion_google_system_messages_use_system_instruction(
    monkeypatch,
):
    """Test Gemini system messages are not serialized as user messages."""
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

        api_client = ApiClient(mock_model_def)

        messages = [
            ChatMessage(role="system", content="System 1"),
            ChatMessage(role="system", content="System 2"),
            ChatMessage(role="user", content="First user message"),
        ]

        result = api_client.get_completion(messages)

        call_args = mock_client.models.generate_content.call_args
        assert call_args.kwargs["contents"] == [
            {"role": "user", "parts": ["First user message"]}
        ]
        assert call_args.kwargs["config"] == {
            "system_instruction": "System 1\n\nSystem 2"
        }
        assert result == "Google response"
