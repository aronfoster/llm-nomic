"""API clients for LLM providers."""

from __future__ import annotations

import logging
from typing import Iterable, Protocol, cast

import anthropic
import anthropic.types
from google import genai
from google.genai import types as google_types
from openai import OpenAI, OpenAIError
from openai.types.chat import ChatCompletionMessageParam

from ..config import get_api_key_from_env
from ..data_models import ChatMessage, ModelDefinition

logger = logging.getLogger(__name__)


class ApiClientProtocol(Protocol):
    """Protocol defining the interface for all LLM API clients."""

    def get_completion(self, messages: list[ChatMessage]) -> str | None: ...


class OpenAICompatibleApiClient:
    """API client for OpenAI-compatible providers.

    Handles local (Ollama), openai, and xai providers.
    """

    model_config: ModelDefinition
    model_id_for_api: str

    def __init__(self, model_config: ModelDefinition) -> None:
        """Initialize the OpenAI-compatible client.

        Args:
            model_config: The ModelDefinition containing provider and API info.

        Raises:
            ValueError: If env_key_name is missing for providers that
                require it.
        """
        self.model_config = model_config
        self.model_id_for_api = model_config.id

        if model_config.provider == "local":
            # For local (Ollama) provider
            self._openai_client: OpenAI = OpenAI(
                base_url=self.model_config.api_model_id,
                api_key="local",  # Ollama doesn't check the API key
            )
            self.model_id_for_api = self.model_config.id
        elif model_config.provider == "xai":
            api_key_name = self.model_config.env_key_name
            if api_key_name is None:
                raise ValueError("env_key_name must be set for xai provider")

            api_key = get_api_key_from_env(api_key_name)

            self._openai_client = OpenAI(
                base_url="https://api.x.ai/v1", api_key=api_key
            )
            self.model_id_for_api = self.model_config.api_model_id
        elif model_config.provider == "openai":
            api_key_name = self.model_config.env_key_name
            if api_key_name is None:
                raise ValueError(
                    "env_key_name must be set for openai provider"
                )

            api_key = get_api_key_from_env(api_key_name)

            self._openai_client = OpenAI(api_key=api_key)
            self.model_id_for_api = self.model_config.api_model_id
        else:
            raise ValueError(
                f"OpenAICompatibleApiClient does not support provider: "
                f"{model_config.provider}"
            )

    def get_completion(self, messages: list[ChatMessage]) -> str | None:
        """Get a chat completion from an OpenAI-compatible API.

        Args:
            messages: List of ChatMessage objects forming the conversation.

        Returns:
            The completion text from the LLM, or None if an error occurred.
        """
        try:
            openai_messages = cast(
                Iterable[ChatCompletionMessageParam],
                [msg.model_dump() for msg in messages],
            )
            openai_response = self._openai_client.chat.completions.create(
                model=self.model_id_for_api, messages=openai_messages
            )
            return openai_response.choices[0].message.content
        except OpenAIError as e:
            logger.error(
                "OpenAI API error for provider %s: %s",
                self.model_config.provider,
                e,
            )
            return None
        except Exception as e:
            logger.error(
                "Error getting completion for provider %s: %s",
                self.model_config.provider,
                e,
            )
            return None


class AnthropicApiClient:
    """API client for the Anthropic provider."""

    model_config: ModelDefinition
    model_id_for_api: str

    def __init__(self, model_config: ModelDefinition) -> None:
        """Initialize the Anthropic client.

        Args:
            model_config: The ModelDefinition containing provider and API info.

        Raises:
            ValueError: If env_key_name is missing.
        """
        self.model_config = model_config

        api_key_name = self.model_config.env_key_name
        if api_key_name is None:
            raise ValueError("env_key_name must be set for anthropic provider")

        api_key = get_api_key_from_env(api_key_name)

        self._anthropic_client: anthropic.Anthropic = anthropic.Anthropic(
            api_key=api_key
        )
        self.model_id_for_api = self.model_config.api_model_id

    def get_completion(self, messages: list[ChatMessage]) -> str | None:
        """Get a chat completion from the Anthropic API.

        Args:
            messages: List of ChatMessage objects forming the conversation.

        Returns:
            The completion text from the LLM, or None if an error occurred.
        """
        try:
            # Anthropic requires separating system messages from the rest
            system_messages = [
                msg.content for msg in messages if msg.role == "system"
            ]
            system_prompt = (
                "\n\n".join(system_messages) if system_messages else None
            )

            # Convert non-system messages to Anthropic's MessageParam type
            anthropic_messages: list[anthropic.types.MessageParam] = []
            for msg in messages:
                if msg.role == "system":
                    continue
                elif msg.role in ("user", "assistant"):
                    anthropic_messages.append(
                        cast(
                            anthropic.types.MessageParam,
                            {"role": msg.role, "content": msg.content},
                        )
                    )
                else:
                    logger.warning(
                        "Unexpected role '%s' for Anthropic, skipping",
                        msg.role,
                    )

            # Anthropic requires at least one user message.
            # If all messages were system-role, use the system prompt
            # as a user message instead.
            if not anthropic_messages and system_prompt:
                anthropic_messages = [
                    cast(
                        anthropic.types.MessageParam,
                        {"role": "user", "content": system_prompt},
                    )
                ]
                system_prompt = None

            client = self._anthropic_client
            anthropic_response: anthropic.types.Message
            if system_prompt:
                anthropic_response = client.messages.create(
                    model=self.model_id_for_api,
                    max_tokens=8192,
                    system=system_prompt,
                    messages=anthropic_messages,
                )
            else:
                anthropic_response = client.messages.create(
                    model=self.model_id_for_api,
                    max_tokens=8192,
                    messages=anthropic_messages,
                )

            first_block = anthropic_response.content[0]
            if hasattr(first_block, "text"):
                return str(first_block.text)
            return None

        except anthropic.APIError as e:
            logger.error(
                "Anthropic API error: %s",
                e,
            )
            return None
        except Exception as e:
            logger.error(
                "Error getting completion for provider %s: %s",
                self.model_config.provider,
                e,
            )
            return None


class GoogleApiClient:
    """API client for the Google (Gemini) provider."""

    model_config: ModelDefinition
    model_id_for_api: str

    def __init__(self, model_config: ModelDefinition) -> None:
        """Initialize the Google GenAI client.

        Args:
            model_config: The ModelDefinition containing provider and API info.

        Raises:
            ValueError: If env_key_name is missing.
        """
        self.model_config = model_config

        api_key_name = self.model_config.env_key_name
        if api_key_name is None:
            raise ValueError("env_key_name must be set for google provider")

        api_key = get_api_key_from_env(api_key_name)

        self._google_client = genai.Client(api_key=api_key)
        self.model_id_for_api = self.model_config.api_model_id

    def get_completion(self, messages: list[ChatMessage]) -> str | None:
        """Get a chat completion from the Google Gemini API.

        Args:
            messages: List of ChatMessage objects forming the conversation.

        Returns:
            The completion text from the LLM, or None if an error occurred.
        """
        try:
            # Google Gemini requires system prompts to be sent via
            # system_instruction (not as a user role message).
            system_messages = [
                msg.content for msg in messages if msg.role == "system"
            ]
            system_instruction = (
                "\n\n".join(system_messages) if system_messages else None
            )

            gemini_messages: list[google_types.Content] = []
            for msg in messages:
                if msg.role == "system":
                    continue
                elif msg.role == "assistant":
                    gemini_messages.append(
                        google_types.Content(
                            role="model",
                            parts=[google_types.Part(text=msg.content)],
                        )
                    )
                elif msg.role == "user":
                    gemini_messages.append(
                        google_types.Content(
                            role="user",
                            parts=[google_types.Part(text=msg.content)],
                        )
                    )
                else:
                    logger.warning(
                        "Unexpected role '%s' for Google, skipping",
                        msg.role,
                    )

            # Google requires at least one content message.
            # If all messages were system-role, use the system
            # instruction as a user message instead.
            if not gemini_messages and system_instruction:
                gemini_messages = [
                    google_types.Content(
                        role="user",
                        parts=[google_types.Part(text=system_instruction)],
                    )
                ]
                system_instruction = None

            google_response = self._google_client.models.generate_content(
                model=self.model_id_for_api,
                contents=gemini_messages,
                config=(
                    {"system_instruction": system_instruction}
                    if system_instruction
                    else None
                ),
            )
            return str(google_response.text)

        except Exception as e:
            logger.error(
                "Error getting completion for provider %s: %s",
                self.model_config.provider,
                e,
            )
            return None


def create_api_client(model_config: ModelDefinition) -> ApiClientProtocol:
    """Factory function that creates the appropriate API client for a provider.

    Args:
        model_config: The ModelDefinition containing provider and API info.

    Returns:
        An API client instance implementing ApiClientProtocol.

    Raises:
        ValueError: If the provider is unknown or required config is missing.
    """
    if model_config.provider in ("local", "openai", "xai"):
        return OpenAICompatibleApiClient(model_config)
    elif model_config.provider == "anthropic":
        return AnthropicApiClient(model_config)
    elif model_config.provider == "google":
        return GoogleApiClient(model_config)
    else:
        raise ValueError(f"Unknown provider: {model_config.provider}")


# Backward-compatible alias
ApiClient = create_api_client
