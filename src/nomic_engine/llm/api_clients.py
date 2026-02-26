"""API clients for LLM providers."""

from __future__ import annotations

import datetime
import logging
import time
from typing import Any, Iterable, Optional, Protocol, cast

import anthropic
import anthropic.types
from google import genai
from google.genai import types as google_types
from openai import OpenAI, OpenAIError
from openai.types.chat import ChatCompletionMessageParam

from ..config import get_api_key_from_env
from ..data_models import (
    ChatMessage,
    CompletionResult,
    ModelDefinition,
    TokenUsageRecord,
)

logger = logging.getLogger(__name__)


class ApiClientProtocol(Protocol):
    """Protocol defining the interface for all LLM API clients."""

    def get_completion(
        self, messages: list[ChatMessage]
    ) -> CompletionResult: ...


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

    def get_completion(self, messages: list[ChatMessage]) -> CompletionResult:
        """Get a chat completion from an OpenAI-compatible API.

        Args:
            messages: List of ChatMessage objects forming the conversation.

        Returns:
            A CompletionResult with text (or None on error), the raw
            response object, and measured client latency.
        """
        start = time.monotonic()
        try:
            openai_messages = cast(
                Iterable[ChatCompletionMessageParam],
                [msg.model_dump() for msg in messages],
            )
            http_response = (
                self._openai_client.chat.completions.with_raw_response.create(
                    model=self.model_id_for_api, messages=openai_messages
                )
            )
            openai_response = http_response.parse()
            client_latency_ms = int((time.monotonic() - start) * 1000)
            return CompletionResult(
                text=openai_response.choices[0].message.content,
                raw_response=openai_response,
                client_latency_ms=client_latency_ms,
                raw_http=http_response,
            )
        except OpenAIError as e:
            client_latency_ms = int((time.monotonic() - start) * 1000)
            logger.error(
                "OpenAI API error for provider %s: %s",
                self.model_config.provider,
                e,
            )
            return CompletionResult(
                text=None,
                raw_response=None,
                client_latency_ms=client_latency_ms,
            )
        except Exception as e:
            client_latency_ms = int((time.monotonic() - start) * 1000)
            logger.error(
                "Error getting completion for provider %s: %s",
                self.model_config.provider,
                e,
            )
            return CompletionResult(
                text=None,
                raw_response=None,
                client_latency_ms=client_latency_ms,
            )


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

    def get_completion(self, messages: list[ChatMessage]) -> CompletionResult:
        """Get a chat completion from the Anthropic API.

        Args:
            messages: List of ChatMessage objects forming the conversation.

        Returns:
            A CompletionResult with text (or None on error), the raw
            response object, and measured client latency.
        """
        start = time.monotonic()
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
            if system_prompt:
                http_response = client.messages.with_raw_response.create(
                    model=self.model_id_for_api,
                    max_tokens=8192,
                    system=system_prompt,
                    messages=anthropic_messages,
                )
            else:
                http_response = client.messages.with_raw_response.create(
                    model=self.model_id_for_api,
                    max_tokens=8192,
                    messages=anthropic_messages,
                )
            anthropic_response = http_response.parse()

            client_latency_ms = int((time.monotonic() - start) * 1000)
            first_block = anthropic_response.content[0]
            text: str | None = None
            if hasattr(first_block, "text"):
                text = str(first_block.text)
            return CompletionResult(
                text=text,
                raw_response=anthropic_response,
                client_latency_ms=client_latency_ms,
                raw_http=http_response,
            )

        except anthropic.APIError as e:
            client_latency_ms = int((time.monotonic() - start) * 1000)
            logger.error(
                "Anthropic API error: %s",
                e,
            )
            return CompletionResult(
                text=None,
                raw_response=None,
                client_latency_ms=client_latency_ms,
            )
        except Exception as e:
            client_latency_ms = int((time.monotonic() - start) * 1000)
            logger.error(
                "Error getting completion for provider %s: %s",
                self.model_config.provider,
                e,
            )
            return CompletionResult(
                text=None,
                raw_response=None,
                client_latency_ms=client_latency_ms,
            )


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

    def get_completion(self, messages: list[ChatMessage]) -> CompletionResult:
        """Get a chat completion from the Google Gemini API.

        Args:
            messages: List of ChatMessage objects forming the conversation.

        Returns:
            A CompletionResult with text (or None on error), the raw
            response object, and measured client latency.
        """
        start = time.monotonic()
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
            client_latency_ms = int((time.monotonic() - start) * 1000)
            return CompletionResult(
                text=str(google_response.text),
                raw_response=google_response,
                client_latency_ms=client_latency_ms,
            )

        except Exception as e:
            client_latency_ms = int((time.monotonic() - start) * 1000)
            logger.error(
                "Error getting completion for provider %s: %s",
                self.model_config.provider,
                e,
            )
            return CompletionResult(
                text=None,
                raw_response=None,
                client_latency_ms=client_latency_ms,
            )


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


def _utc_timestamp() -> str:
    """Return the current UTC time as an ISO 8601 string ending with Z."""
    now = datetime.datetime.now(datetime.timezone.utc)
    # Format with millisecond precision
    ms = f"{now.microsecond // 1000:03d}"
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + ms + "Z"


def _safe_int(value: Any) -> Optional[int]:
    """Convert value to int, returning None on failure."""
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _extract_anthropic_metadata(
    raw_response: Any,
    raw_http: Any = None,
) -> dict[str, Any]:
    """Extract token usage metadata from an Anthropic Message response."""
    result: dict[str, Any] = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_tokens": None,
        "cache_read_tokens": None,
        "reasoning_tokens": None,
        "finish_reason": None,
        "server_latency_ms": None,
        "ttft_ms": None,
        "mean_itl_ms": None,
        "request_id": None,
        "ratelimit_remaining_requests": None,
        "ratelimit_remaining_tokens": None,
    }
    if raw_response is None:
        return result
    try:
        usage = getattr(raw_response, "usage", None)
        if usage is not None:
            result["input_tokens"] = getattr(usage, "input_tokens", 0) or 0
            result["output_tokens"] = getattr(usage, "output_tokens", 0) or 0
            cct = getattr(usage, "cache_creation_input_tokens", None)
            result["cache_creation_tokens"] = cct
            crt = getattr(usage, "cache_read_input_tokens", None)
            result["cache_read_tokens"] = crt
        stop_reason = getattr(raw_response, "stop_reason", None)
        if stop_reason is not None:
            result["finish_reason"] = str(stop_reason)
        _id = getattr(raw_response, "id", None)
        result["request_id"] = _id if isinstance(_id, str) else None
    except Exception as exc:
        logger.warning("Failed to extract Anthropic token metadata: %s", exc)
    if raw_http is not None:
        try:
            headers = getattr(raw_http, "headers", None)
            if headers is not None:
                rid = headers.get("x-request-id")
                if rid is not None:
                    result["request_id"] = rid
                result["ratelimit_remaining_requests"] = _safe_int(
                    headers.get("anthropic-ratelimit-requests-remaining")
                )
                result["ratelimit_remaining_tokens"] = _safe_int(
                    headers.get("anthropic-ratelimit-tokens-remaining")
                )
        except Exception as exc:
            logger.warning("Failed to extract Anthropic HTTP headers: %s", exc)
    return result


def _extract_openai_metadata(
    raw_response: Any,
    provider: str,
    raw_http: Any = None,
) -> dict[str, Any]:
    """Extract token usage metadata from an OpenAI-compatible response."""
    result: dict[str, Any] = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_tokens": None,
        "cache_read_tokens": None,
        "reasoning_tokens": None,
        "finish_reason": None,
        "server_latency_ms": None,
        "ttft_ms": None,
        "mean_itl_ms": None,
        "request_id": None,
        "ratelimit_remaining_requests": None,
        "ratelimit_remaining_tokens": None,
    }
    if raw_response is None:
        return result
    try:
        usage = getattr(raw_response, "usage", None)
        if usage is not None:
            result["input_tokens"] = getattr(usage, "prompt_tokens", 0) or 0
            result["output_tokens"] = (
                getattr(usage, "completion_tokens", 0) or 0
            )
            if provider == "openai":
                details = getattr(usage, "completion_tokens_details", None)
                if details is not None:
                    rt = getattr(details, "reasoning_tokens", None)
                    result["reasoning_tokens"] = rt
            if provider == "xai":
                ptd = getattr(usage, "prompt_tokens_details", None)
                if ptd is not None:
                    ct = getattr(ptd, "cached_tokens", None)
                    result["cache_read_tokens"] = ct
        choices = getattr(raw_response, "choices", None)
        if choices:
            fr = getattr(choices[0], "finish_reason", None)
            if fr is not None:
                result["finish_reason"] = str(fr)
        _id = getattr(raw_response, "id", None)
        result["request_id"] = _id if isinstance(_id, str) else None
    except Exception as exc:
        logger.warning("Failed to extract OpenAI token metadata: %s", exc)
    if raw_http is not None:
        try:
            headers = getattr(raw_http, "headers", None)
            if headers is not None:
                rid = headers.get("x-request-id")
                if rid is not None:
                    result["request_id"] = rid
                result["ratelimit_remaining_requests"] = _safe_int(
                    headers.get("x-ratelimit-remaining-requests")
                )
                result["ratelimit_remaining_tokens"] = _safe_int(
                    headers.get("x-ratelimit-remaining-tokens")
                )
                try:
                    result["ttft_ms"] = _safe_int(
                        float(headers.get("x-metrics-ttft-ms", 0) or 0)
                    )
                    result["mean_itl_ms"] = _safe_int(
                        float(headers.get("x-metrics-mean-itl-ms", 0) or 0)
                    )
                    result["server_latency_ms"] = _safe_int(
                        float(headers.get("x-metrics-e2e-ms", 0) or 0)
                    )
                except (ValueError, TypeError) as exc:
                    logger.warning(
                        "Failed to parse xAI timing headers: %s", exc
                    )
        except Exception as exc:
            logger.warning("Failed to extract OpenAI HTTP headers: %s", exc)
    return result


def _extract_google_metadata(raw_response: Any) -> dict[str, Any]:
    """Extract token usage metadata from a Google GenerateContentResponse."""
    result: dict[str, Any] = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_tokens": None,
        "cache_read_tokens": None,
        "reasoning_tokens": None,
        "finish_reason": None,
        "server_latency_ms": None,
        "ttft_ms": None,
        "mean_itl_ms": None,
        "request_id": None,
        "ratelimit_remaining_requests": None,
        "ratelimit_remaining_tokens": None,
    }
    if raw_response is None:
        return result
    try:
        usage = getattr(raw_response, "usage_metadata", None)
        if usage is not None:
            result["input_tokens"] = (
                getattr(usage, "prompt_token_count", 0) or 0
            )
            result["output_tokens"] = (
                getattr(usage, "candidates_token_count", 0) or 0
            )
        candidates = getattr(raw_response, "candidates", None)
        if candidates:
            fr = getattr(candidates[0], "finish_reason", None)
            if fr is not None:
                result["finish_reason"] = str(fr)
    except Exception as exc:
        logger.warning("Failed to extract Google token metadata: %s", exc)
    return result


def build_token_usage_record(
    result: CompletionResult,
    model_config: ModelDefinition,
    call_type: str,
    move_number: int,
    player_name: str,
) -> TokenUsageRecord:
    """Build a fully populated TokenUsageRecord from a CompletionResult.

    Performs provider-specific extraction of token counts, finish reason,
    and other metadata from CompletionResult.raw_response. Fields that
    cannot be extracted are set to null. All exceptions are caught and
    logged as warnings so this function never raises.

    Args:
        result: The CompletionResult returned by get_completion().
        model_config: The ModelDefinition used for this call.
        call_type: The type of call (propose, discuss, vote, etc.).
        move_number: The current game move number.
        player_name: The player name (or "Judge" for judge calls).

    Returns:
        A fully populated TokenUsageRecord ready for logging.
    """
    provider = model_config.provider

    if provider == "anthropic":
        meta = _extract_anthropic_metadata(
            result.raw_response, result.raw_http
        )
    elif provider in ("openai", "xai", "local"):
        meta = _extract_openai_metadata(
            result.raw_response, provider, result.raw_http
        )
    elif provider == "google":
        meta = _extract_google_metadata(result.raw_response)
    else:
        meta = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_tokens": None,
            "cache_read_tokens": None,
            "reasoning_tokens": None,
            "finish_reason": None,
            "server_latency_ms": None,
            "ttft_ms": None,
            "mean_itl_ms": None,
            "request_id": None,
            "ratelimit_remaining_requests": None,
            "ratelimit_remaining_tokens": None,
        }

    return TokenUsageRecord(
        timestamp=_utc_timestamp(),
        move_number=move_number,
        player_name=player_name,
        provider=provider,
        model_id=model_config.api_model_id,
        call_type=call_type,
        input_tokens=meta["input_tokens"],
        output_tokens=meta["output_tokens"],
        cache_creation_tokens=meta["cache_creation_tokens"],
        cache_read_tokens=meta["cache_read_tokens"],
        reasoning_tokens=meta["reasoning_tokens"],
        finish_reason=meta["finish_reason"],
        client_latency_ms=result.client_latency_ms,
        server_latency_ms=meta["server_latency_ms"],
        ttft_ms=meta["ttft_ms"],
        mean_itl_ms=meta["mean_itl_ms"],
        request_id=meta["request_id"],
        ratelimit_remaining_requests=meta["ratelimit_remaining_requests"],
        ratelimit_remaining_tokens=meta["ratelimit_remaining_tokens"],
    )
