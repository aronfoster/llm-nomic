"""API clients for LLM providers."""

from __future__ import annotations

import logging
import os
from typing import Any

import anthropic
import google.generativeai as genai
from openai import OpenAI, OpenAIError

from ..data_models import ChatMessage, ModelDefinition

logger = logging.getLogger(__name__)


class ApiClient:
    """Extensible API client that configures based on ModelDefinition."""

    model_config: ModelDefinition
    model_id_for_api: str

    def __init__(self, model_config: ModelDefinition):
        """Initialize the API client based on the provider.

        Args:
            model_config: The ModelDefinition containing provider and API info.

        Raises:
            ValueError: If the provider is unknown or API key is missing.
        """
        self.model_config = model_config
        self.model_id_for_api = model_config.id

        # TODO: change local to ollama
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

            api_key = os.getenv(api_key_name)
            if not api_key:
                raise ValueError(
                    (
                        "API key for provider xai not found in environment "
                        f"variable {api_key_name}"
                    )
                )

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

            api_key = os.getenv(api_key_name)
            if not api_key:
                raise ValueError(
                    (
                        "API key for provider openai not found in environment "
                        f"variable {api_key_name}"
                    )
                )

            self._openai_client = OpenAI(api_key=api_key)
            self.model_id_for_api = self.model_config.api_model_id
        elif model_config.provider == "anthropic":
            api_key_name = self.model_config.env_key_name
            if api_key_name is None:
                raise ValueError(
                    "env_key_name must be set for anthropic provider"
                )

            api_key = os.getenv(api_key_name)
            if not api_key:
                raise ValueError(
                    (
                        "API key for provider anthropic not found in "
                        f"environment variable {api_key_name}"
                    )
                )

            self._anthropic_client: anthropic.Anthropic = anthropic.Anthropic(
                api_key=api_key
            )
            self.model_id_for_api = self.model_config.api_model_id
        elif model_config.provider == "google":
            api_key_name = self.model_config.env_key_name
            if api_key_name is None:
                raise ValueError(
                    "env_key_name must be set for google provider"
                )

            api_key = os.getenv(api_key_name)
            if not api_key:
                raise ValueError(
                    (
                        "API key for provider google not found in environment "
                        f"variable {api_key_name}"
                    )
                )

            # google-generativeai module doesn't export these in type stubs
            genai.configure(api_key=api_key)  # type: ignore[attr-defined]
            self._google_client: Any = genai.GenerativeModel(  # type: ignore[attr-defined]
                self.model_config.api_model_id
            )
            self.model_id_for_api = self.model_config.api_model_id
        else:
            raise ValueError(f"Unknown provider: {self.model_config.provider}")

    def get_completion(self, messages: list[ChatMessage]) -> str | None:
        """Get a chat completion from the LLM.

        Args:
            messages: List of ChatMessage objects forming the conversation.

        Returns:
            The completion text from the LLM, or None if an error occurred.
        """
        try:
            if self.model_config.provider in ["local", "xai", "openai"]:
                # OpenAI-compatible providers
                message_dicts: list[dict[str, Any]] = [
                    msg.model_dump() for msg in messages
                ]
                # OpenAI SDK expects ChatCompletionMessageParam TypedDict, but
                # our Pydantic models serialize to compatible dicts
                openai_response = self._openai_client.chat.completions.create(
                    model=self.model_id_for_api, messages=message_dicts  # type: ignore[arg-type]
                )
                return openai_response.choices[0].message.content

            elif self.model_config.provider == "anthropic":
                # Anthropic requires separating system messages from the rest
                system_messages = [
                    msg.content for msg in messages if msg.role == "system"
                ]
                system_prompt = (
                    "\n\n".join(system_messages) if system_messages else None
                )

                # Convert non-system messages to Anthropic format
                anthropic_messages = [
                    {"role": msg.role, "content": msg.content}
                    for msg in messages
                    if msg.role != "system"
                ]

                # Create message with Anthropic client
                client = self._anthropic_client
                anthropic_response: anthropic.types.Message
                # Anthropic SDK expects MessageParam TypedDict, but our dicts
                # are compatible with the required structure
                if system_prompt:
                    anthropic_response = client.messages.create(
                        model=self.model_id_for_api,
                        max_tokens=8192,
                        system=system_prompt,
                        messages=anthropic_messages,  # type: ignore[arg-type]
                    )
                else:
                    anthropic_response = client.messages.create(
                        model=self.model_id_for_api,
                        max_tokens=8192,
                        messages=anthropic_messages,  # type: ignore[arg-type]
                    )

                # Extract text from the response
                first_block = anthropic_response.content[0]
                if hasattr(first_block, "text"):
                    return str(first_block.text)
                return None

            elif self.model_config.provider == "google":
                # Google Gemini requires converting to their format
                gemini_messages = []
                for msg in messages:
                    # Map roles: 'assistant' -> 'model', keep 'user'
                    # System messages prepended to first user message
                    if msg.role == "system":
                        # Prepend system message to the conversation
                        gemini_messages.append(
                            {"role": "user", "parts": [msg.content]}
                        )
                    elif msg.role == "assistant":
                        gemini_messages.append(
                            {"role": "model", "parts": [msg.content]}
                        )
                    else:  # user
                        gemini_messages.append(
                            {"role": "user", "parts": [msg.content]}
                        )

                # Generate content
                google_response = self._google_client.generate_content(
                    gemini_messages
                )
                return str(google_response.text)

            else:
                logger.error(
                    "Unknown provider: %s", self.model_config.provider
                )
                return None

        except OpenAIError as e:
            logger.error(
                "OpenAI API error for provider %s: %s",
                self.model_config.provider,
                e,
            )
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
