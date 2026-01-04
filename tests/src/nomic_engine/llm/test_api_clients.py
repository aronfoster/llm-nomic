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

    with (
        patch(
            "src.nomic_engine.llm.api_clients.genai.configure"
        ) as mock_configure,
        patch(
            "src.nomic_engine.llm.api_clients.genai.GenerativeModel"
        ) as mock_model,
    ):
        api_client = ApiClient(mock_model_def)

        mock_configure.assert_called_once_with(api_key="test-google-key")
        mock_model.assert_called_once_with("gemini-2.5-pro")
        assert api_client.model_id_for_api == "gemini-2.5-pro"
        assert api_client.model_config == mock_model_def


def test_api_client_cloud_providers_missing_key():
    """Test that cloud providers raise ValueError when API key is missing."""
    cloud_providers = ["openai", "anthropic", "google"]

    for provider in cloud_providers:
        mock_model_def = ModelDefinition(
            id=f"test-{provider}",
            provider=provider,
            api_model_id=f"{provider}-model-id",
            env_key_name=f"{provider.upper()}_API_KEY",
        )

        with pytest.raises(ValueError) as exc_info:
            ApiClient(mock_model_def)

        assert f"API key for provider {provider} not found" in str(
            exc_info.value
        )


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

    assert "API key for provider xai not found" in str(exc_info.value)


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
