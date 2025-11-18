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


def test_api_client_cloud_providers_raise_error():
    """Test that cloud providers raise NotImplementedError."""
    cloud_providers = ["openai", "xai", "anthropic", "google"]

    for provider in cloud_providers:
        mock_model_def = ModelDefinition(
            id=f"test-{provider}",
            provider=provider,
            api_model_id=f"{provider}-model-id",
            env_key_name=f"{provider.upper()}_API_KEY",
        )

        with pytest.raises(NotImplementedError) as exc_info:
            ApiClient(mock_model_def)

        assert f"Provider {provider} not yet implemented" in str(
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
