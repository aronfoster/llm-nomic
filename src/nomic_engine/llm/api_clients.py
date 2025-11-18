"""API clients for LLM providers."""

import logging
from typing import Any

from openai import OpenAI, OpenAIError

from ..data_models import ChatMessage, ModelDefinition

logger = logging.getLogger(__name__)


class ApiClient:
    """Extensible API client that configures based on ModelDefinition."""

    def __init__(self, model_config: ModelDefinition):
        """Initialize the API client based on the provider.

        Args:
            model_config: The ModelDefinition containing provider and API info.

        Raises:
            NotImplementedError: If the provider is not yet implemented.
            ValueError: If the provider is unknown.
        """
        self.model_config = model_config

        if model_config.provider == "local":
            # For local (Ollama) provider
            self.client = OpenAI(
                base_url=self.model_config.api_model_id,
                api_key="local",  # Ollama doesn't check the API key
            )
        elif model_config.provider in ["openai", "xai", "anthropic", "google"]:
            # Cloud providers - to be implemented later
            raise NotImplementedError(
                f"Provider {self.model_config.provider} not yet implemented."
            )
        else:
            raise ValueError(f"Unknown provider: {self.model_config.provider}")

    def get_completion(self, messages: list[ChatMessage]) -> str | None:
        """Get a chat completion from the LLM.

        Args:
            messages: List of ChatMessage objects forming the conversation.

        Returns:
            The completion text from the LLM, or None if an error occurred.
        """
        # Convert Pydantic models to dicts
        message_dicts: list[dict[str, Any]] = [
            msg.model_dump() for msg in messages
        ]

        try:
            response = self.client.chat.completions.create(
                model=self.model_config.id, messages=message_dicts  # type: ignore[arg-type]
            )
            return response.choices[0].message.content
        except OpenAIError as e:
            logger.error(f"Error getting completion: {e}")
            return None
