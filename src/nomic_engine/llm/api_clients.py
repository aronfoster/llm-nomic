"""API clients for LLM providers."""

from __future__ import annotations

import datetime
import logging
import time
from typing import Any, Iterable, Optional, Protocol, cast

import anthropic
import anthropic.types
import httpx
from google import genai
from google.genai import types as google_types
from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam

from ..config import get_api_key_from_env
from ..data_models import (
    ChatMessage,
    CompletionResult,
    ModelDefinition,
    TokenUsageRecord,
)
from ..usage_budget import (
    LlmCallOptions,
    UsageBudgetExceeded,
    UsageBudgetGuard,
    is_truncated_finish_reason,
)
from .providers.grok_cli_adapter import TOOL_ISOLATION_GATE

logger = logging.getLogger(__name__)

# Anthropic requires max_tokens. 8192 is the historical request size
# used when a game does not configure max_output_tokens.
_DEFAULT_ANTHROPIC_MAX_TOKENS = 8192

# The provider SDKs retry 429s, 5xxs, and timeouts on their own. Those
# retries would not pass the usage guard, so every SDK client is built
# with retries disabled. Further attempts happen only in llm_retry_loop.
_SDK_MAX_RETRIES = 0


def _text_or_none(value: Any) -> str | None:
    """Return visible text. None stays None and is never the string 'None'."""
    if isinstance(value, str):
        return value
    return None


def _sdk_client_kwargs(
    *,
    http_client: httpx.Client | None,
) -> dict[str, Any]:
    """Shared SDK options: no internal retries, optional mock transport."""
    kwargs: dict[str, Any] = {"max_retries": _SDK_MAX_RETRIES}
    if http_client is not None:
        kwargs["http_client"] = http_client
    return kwargs


def _empty_usage_meta() -> dict[str, Any]:
    """Metadata for a call whose token counts are unknown, not zero."""
    return {
        "usage_available": False,
        "input_tokens": None,
        "output_tokens": None,
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


def _optional_token(value: Any) -> Optional[int]:
    """Return an int token count, or None when the value is unusable.

    Booleans are rejected because ``bool`` is a subclass of ``int``.
    A missing or non-integer count is unavailable, not zero.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return int(value)


def _set_token_pair(
    result: dict[str, Any],
    usage: Any,
    input_name: str,
    output_name: str,
) -> None:
    """Record input and output tokens only when both counts are ints."""
    if usage is None:
        return
    input_tokens = _optional_token(getattr(usage, input_name, None))
    output_tokens = _optional_token(getattr(usage, output_name, None))
    if input_tokens is None or output_tokens is None:
        return
    result["usage_available"] = True
    result["input_tokens"] = input_tokens
    result["output_tokens"] = output_tokens


def _uses_max_completion_tokens(model_id: str) -> bool:
    """True for OpenAI models that reject ``max_tokens``.

    gpt-5 and the o-series require ``max_completion_tokens``. Older chat
    models, xAI, and Ollama still accept ``max_tokens``. This helper is
    only used for the OpenAI provider.
    """
    name = model_id.lower()
    return name.startswith(("gpt-5", "o1", "o3", "o4"))


def _timeout_kwargs(options: LlmCallOptions) -> dict[str, float]:
    """Per-call timeout, omitted when the game left it unset."""
    if options.per_call_timeout_seconds is None:
        return {}
    return {"timeout": options.per_call_timeout_seconds}


def _openai_output_limit_kwargs(
    provider: str, model_id: str, options: LlmCallOptions
) -> dict[str, int]:
    """Output cap for an OpenAI-compatible request, or nothing if unset."""
    limit = options.max_output_tokens
    if limit is None:
        return {}
    if provider == "openai" and _uses_max_completion_tokens(model_id):
        return {"max_completion_tokens": limit}
    return {"max_tokens": limit}


def classify_provider_error(exc: BaseException) -> str:
    """Classify a provider exception as timeout, quota, or api_error.

    Quota covers HTTP 429 and rate-limit exception types. The engine
    does not fall back to another provider.
    """
    status = getattr(exc, "status_code", None)
    if status == 429:
        return "quota"
    code = getattr(exc, "code", None)
    if isinstance(code, str) and code in {
        "insufficient_quota",
        "rate_limit_exceeded",
        "billing_hard_limit_reached",
    }:
        return "quota"
    name = type(exc).__name__.lower()
    if "timeout" in name:
        return "timeout"
    if "ratelimit" in name or "rate_limit" in name:
        return "quota"
    return "api_error"


def _failed_result(
    *,
    provider: str,
    exc: BaseException,
    started: float,
    timeout_seconds: float | None,
) -> CompletionResult:
    """Log a failed provider call and return an empty completion.

    The attempt still counts against the usage budget. Quota and timeout
    are named in the log. No other provider is tried.
    """
    kind = classify_provider_error(exc)
    if kind == "quota":
        logger.error(
            "Provider quota or rate limit for %s "
            "(counted against the usage budget; no fallback provider): %s",
            provider,
            exc,
        )
    elif kind == "timeout":
        shown = "unset" if timeout_seconds is None else timeout_seconds
        logger.error(
            "Provider call timed out for %s "
            "(per-call timeout %s seconds; counted against the usage "
            "budget; no fallback provider): %s",
            provider,
            shown,
            exc,
        )
    else:
        logger.error(
            "Error getting completion for provider %s: %s",
            provider,
            exc,
        )
    client_latency_ms = int((time.monotonic() - started) * 1000)
    return CompletionResult(
        text=None,
        raw_response=None,
        client_latency_ms=client_latency_ms,
        error_kind=kind,
    )


class ApiClientProtocol(Protocol):
    """Protocol defining the interface for all LLM API clients."""

    def get_completion(
        self, messages: list[ChatMessage], *, use_cache_control: bool = True
    ) -> CompletionResult: ...


class OpenAICompatibleApiClient:
    """API client for OpenAI-compatible providers.

    Handles local (Ollama), openai, and xai providers.
    """

    model_config: ModelDefinition
    model_id_for_api: str

    def __init__(
        self,
        model_config: ModelDefinition,
        call_options: LlmCallOptions | None = None,
        *,
        http_client: httpx.Client | None = None,
    ) -> None:
        """Initialize the OpenAI-compatible client.

        Args:
            model_config: The ModelDefinition containing provider and API info.
            call_options: Optional per-call timeout and output cap. None
                keeps the historical request (no timeout, no output cap).
            http_client: Optional httpx client. Tests pass one backed by
                ``httpx.MockTransport``. Production leaves it unset.

        Raises:
            ValueError: If env_key_name is missing for providers that
                require it.
        """
        self.model_config = model_config
        self._call_options = call_options or LlmCallOptions()
        self.model_id_for_api = model_config.id
        sdk_kwargs = _sdk_client_kwargs(http_client=http_client)

        if model_config.provider == "local":
            # For local (Ollama) provider
            self._openai_client: OpenAI = OpenAI(
                base_url=self.model_config.api_model_id,
                api_key="local",  # Ollama doesn't check the API key
                **sdk_kwargs,
            )
            self.model_id_for_api = self.model_config.id
        elif model_config.provider == "xai":
            api_key_name = self.model_config.env_key_name
            if api_key_name is None:
                raise ValueError("env_key_name must be set for xai provider")

            api_key = get_api_key_from_env(api_key_name)

            self._openai_client = OpenAI(
                base_url="https://api.x.ai/v1",
                api_key=api_key,
                **sdk_kwargs,
            )
            self.model_id_for_api = self.model_config.api_model_id
        elif model_config.provider == "openai":
            api_key_name = self.model_config.env_key_name
            if api_key_name is None:
                raise ValueError(
                    "env_key_name must be set for openai provider"
                )

            api_key = get_api_key_from_env(api_key_name)

            self._openai_client = OpenAI(api_key=api_key, **sdk_kwargs)
            self.model_id_for_api = self.model_config.api_model_id
        else:
            raise ValueError(
                f"OpenAICompatibleApiClient does not support provider: "
                f"{model_config.provider}"
            )

    def get_completion(
        self, messages: list[ChatMessage], *, use_cache_control: bool = True
    ) -> CompletionResult:
        """Get a chat completion from an OpenAI-compatible API.

        Args:
            messages: List of ChatMessage objects forming the conversation.
            use_cache_control: Ignored for OpenAI-compatible providers.

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
            request_kwargs: dict[str, Any] = {
                "model": self.model_id_for_api,
                "messages": openai_messages,
            }
            request_kwargs.update(
                _openai_output_limit_kwargs(
                    self.model_config.provider,
                    self.model_id_for_api,
                    self._call_options,
                )
            )
            request_kwargs.update(_timeout_kwargs(self._call_options))
            http_response = (
                self._openai_client.chat.completions.with_raw_response.create(
                    **request_kwargs
                )
            )
            openai_response = http_response.parse()
            client_latency_ms = int((time.monotonic() - start) * 1000)
            choices = openai_response.choices or []
            content = choices[0].message.content if choices else None
            return CompletionResult(
                text=_text_or_none(content),
                raw_response=openai_response,
                client_latency_ms=client_latency_ms,
                raw_http=http_response,
            )
        except Exception as e:
            return _failed_result(
                provider=self.model_config.provider,
                exc=e,
                started=start,
                timeout_seconds=self._call_options.per_call_timeout_seconds,
            )


class AnthropicApiClient:
    """API client for the Anthropic provider."""

    model_config: ModelDefinition
    model_id_for_api: str

    def __init__(
        self,
        model_config: ModelDefinition,
        call_options: LlmCallOptions | None = None,
        *,
        http_client: httpx.Client | None = None,
    ) -> None:
        """Initialize the Anthropic client.

        Args:
            model_config: The ModelDefinition containing provider and API info.
            call_options: Optional per-call timeout and output cap. When
                the output cap is unset, max_tokens stays 8192.
            http_client: Optional httpx client. Tests pass one backed by
                ``httpx.MockTransport``. Production leaves it unset.

        Raises:
            ValueError: If env_key_name is missing.
        """
        self.model_config = model_config
        self._call_options = call_options or LlmCallOptions()

        api_key_name = self.model_config.env_key_name
        if api_key_name is None:
            raise ValueError("env_key_name must be set for anthropic provider")

        api_key = get_api_key_from_env(api_key_name)

        self._anthropic_client: anthropic.Anthropic = anthropic.Anthropic(
            api_key=api_key,
            **_sdk_client_kwargs(http_client=http_client),
        )
        self.model_id_for_api = self.model_config.api_model_id

    def get_completion(
        self, messages: list[ChatMessage], *, use_cache_control: bool = True
    ) -> CompletionResult:
        """Get a chat completion from the Anthropic API.

        Args:
            messages: List of ChatMessage objects forming the conversation.
            use_cache_control: When True (default), sends
                ``cache_control: {"type": "ephemeral"}`` to trigger an
                Anthropic cache write. When False, omits the header so
                the call reads from an existing cache entry without
                refreshing it (useful for memory-update calls where the
                system prefix was already cached earlier in the turn).

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

            extra_kwargs: dict[str, Any] = {}
            if use_cache_control:
                extra_kwargs["cache_control"] = {"type": "ephemeral"}
            extra_kwargs.update(_timeout_kwargs(self._call_options))
            max_tokens = self._call_options.max_output_tokens
            if max_tokens is None:
                max_tokens = _DEFAULT_ANTHROPIC_MAX_TOKENS

            client = self._anthropic_client
            if system_prompt:
                http_response = client.messages.with_raw_response.create(
                    model=self.model_id_for_api,
                    max_tokens=max_tokens,
                    system=system_prompt,
                    messages=anthropic_messages,
                    **extra_kwargs,
                )
            else:
                http_response = client.messages.with_raw_response.create(
                    model=self.model_id_for_api,
                    max_tokens=max_tokens,
                    messages=anthropic_messages,
                    **extra_kwargs,
                )
            anthropic_response = http_response.parse()

            client_latency_ms = int((time.monotonic() - start) * 1000)
            blocks = anthropic_response.content or []
            block_text = getattr(blocks[0], "text", None) if blocks else None
            return CompletionResult(
                text=_text_or_none(block_text),
                raw_response=anthropic_response,
                client_latency_ms=client_latency_ms,
                raw_http=http_response,
            )

        except Exception as e:
            return _failed_result(
                provider=self.model_config.provider,
                exc=e,
                started=start,
                timeout_seconds=self._call_options.per_call_timeout_seconds,
            )


class GoogleApiClient:
    """API client for the Google (Gemini) provider."""

    model_config: ModelDefinition
    model_id_for_api: str

    def __init__(
        self,
        model_config: ModelDefinition,
        call_options: LlmCallOptions | None = None,
        *,
        http_client: httpx.Client | None = None,
    ) -> None:
        """Initialize the Google GenAI client.

        Args:
            model_config: The ModelDefinition containing provider and API info.
            call_options: Optional per-call timeout and output cap. The
                Google SDK takes ``HttpOptions.timeout`` in milliseconds.
                When the timeout is unset, no per-request timeout is sent.
            http_client: Optional httpx client. Tests pass one backed by
                ``httpx.MockTransport``. Production leaves it unset.

        Raises:
            ValueError: If env_key_name is missing.
        """
        self.model_config = model_config
        self._call_options = call_options or LlmCallOptions()

        api_key_name = self.model_config.env_key_name
        if api_key_name is None:
            raise ValueError("env_key_name must be set for google provider")

        api_key = get_api_key_from_env(api_key_name)

        # attempts=1 means the original request only. Leaving retry
        # options unset is also one attempt today, but the field docs
        # say an omitted attempts value can mean five. Set it explicitly.
        http_options_kwargs: dict[str, Any] = {
            "retry_options": google_types.HttpRetryOptions(attempts=1),
        }
        if http_client is not None:
            http_options_kwargs["httpx_client"] = http_client
        self._google_client = genai.Client(
            api_key=api_key,
            http_options=google_types.HttpOptions(**http_options_kwargs),
        )
        self.model_id_for_api = self.model_config.api_model_id

    def get_completion(
        self, messages: list[ChatMessage], *, use_cache_control: bool = True
    ) -> CompletionResult:
        """Get a chat completion from the Google Gemini API.

        Args:
            messages: List of ChatMessage objects forming the conversation.
            use_cache_control: Ignored for Google provider.

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
                config=self._google_config(system_instruction),
            )
            client_latency_ms = int((time.monotonic() - start) * 1000)
            return CompletionResult(
                text=_text_or_none(google_response.text),
                raw_response=google_response,
                client_latency_ms=client_latency_ms,
            )

        except Exception as e:
            return _failed_result(
                provider=self.model_config.provider,
                exc=e,
                started=start,
                timeout_seconds=self._call_options.per_call_timeout_seconds,
            )

    def _google_config(
        self, system_instruction: str | None
    ) -> google_types.GenerateContentConfigDict | None:
        """Build the generate_content config dict.

        With no output cap and no timeout this matches the historical
        request: a system_instruction dict, or None when there is no
        system text. ``http_options.timeout`` is milliseconds, which is
        the unit ``google.genai.types.HttpOptions`` documents.
        """
        config: google_types.GenerateContentConfigDict = {}
        if system_instruction:
            config["system_instruction"] = system_instruction
        limit = self._call_options.max_output_tokens
        if limit is not None:
            config["max_output_tokens"] = limit
        timeout = self._call_options.per_call_timeout_seconds
        if timeout is not None:
            # HttpOptions.timeout is an integer number of milliseconds.
            # attempts=1 keeps this per-request override from enabling
            # the SDK's multi-attempt retry path.
            config["http_options"] = {
                "timeout": max(1, int(timeout * 1000)),
                "retry_options": {"attempts": 1},
            }
        if not config:
            return None
        return config


def create_api_client(
    model_config: ModelDefinition,
    *,
    call_options: LlmCallOptions | None = None,
    usage_guard: UsageBudgetGuard | None = None,
) -> ApiClientProtocol:
    """Factory function that creates the appropriate API client for a provider.

    Args:
        model_config: The ModelDefinition containing provider and API info.
        call_options: Per-call timeout and output cap. None keeps each
            provider's historical request parameters.
        usage_guard: When set, every get_completion passes through the
            guard before the provider call, including retries.

    Returns:
        An API client instance implementing ApiClientProtocol.

    Raises:
        ValueError: If the provider is unknown, grok_cli is requested,
            or required config is missing. grok_cli is never selected
            here. There is no paid API fallback from that refusal.
    """
    if model_config.provider == "grok_cli":
        raise ValueError(
            "provider grok_cli is disabled in the game factory. "
            "select_grok_cli_adapter accepts it only when enabled is "
            f"True and {TOOL_ISOLATION_GATE} is True. "
            "There is no paid API fallback."
        )
    options = call_options or LlmCallOptions()
    if model_config.provider in ("local", "openai", "xai"):
        client: ApiClientProtocol = OpenAICompatibleApiClient(
            model_config, call_options=options
        )
    elif model_config.provider == "anthropic":
        client = AnthropicApiClient(model_config, call_options=options)
    elif model_config.provider == "google":
        client = GoogleApiClient(model_config, call_options=options)
    else:
        raise ValueError(f"Unknown provider: {model_config.provider}")
    if usage_guard is None:
        return client
    return BudgetedApiClient(client, usage_guard, model_config.provider)


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
    result = _empty_usage_meta()
    if raw_response is None:
        return result
    try:
        usage = getattr(raw_response, "usage", None)
        _set_token_pair(result, usage, "input_tokens", "output_tokens")
        if usage is not None:
            result["cache_creation_tokens"] = _optional_token(
                getattr(usage, "cache_creation_input_tokens", None)
            )
            result["cache_read_tokens"] = _optional_token(
                getattr(usage, "cache_read_input_tokens", None)
            )
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
    result = _empty_usage_meta()
    if raw_response is None:
        return result
    try:
        usage = getattr(raw_response, "usage", None)
        _set_token_pair(result, usage, "prompt_tokens", "completion_tokens")
        if usage is not None:
            if provider in ("openai", "xai"):
                details = getattr(usage, "completion_tokens_details", None)
                if details is not None:
                    result["reasoning_tokens"] = _optional_token(
                        getattr(details, "reasoning_tokens", None)
                    )
            if provider == "xai":
                ptd = getattr(usage, "prompt_tokens_details", None)
                if ptd is not None:
                    result["cache_read_tokens"] = _optional_token(
                        getattr(ptd, "cached_tokens", None)
                    )
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
                    result["ttft_ms"] = (
                        float(headers.get("x-metrics-ttft-ms") or 0) or None
                    )
                    result["mean_itl_ms"] = (
                        float(headers.get("x-metrics-mean-itl-ms") or 0)
                        or None
                    )
                    result["server_latency_ms"] = (
                        float(headers.get("x-metrics-e2e-ms") or 0) or None
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
    result = _empty_usage_meta()
    if raw_response is None:
        return result
    try:
        usage = getattr(raw_response, "usage_metadata", None)
        _set_token_pair(
            result, usage, "prompt_token_count", "candidates_token_count"
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
    and other metadata from CompletionResult.raw_response. Missing input
    or output counts are null and ``usage_available`` is false. They are
    not stored as zero. A truncated finish reason is logged as a partial
    output. Extraction failures are logged and treated as unavailable.

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
    meta = _metadata_for_result(result, provider)
    finish_reason = meta["finish_reason"]
    if isinstance(finish_reason, str) and is_truncated_finish_reason(
        finish_reason
    ):
        logger.warning(
            "Partial output from provider %s: finish_reason=%s. "
            "The response hit the output token limit and may be "
            "incomplete.",
            provider,
            finish_reason,
        )

    return TokenUsageRecord(
        timestamp=_utc_timestamp(),
        move_number=move_number,
        player_name=player_name,
        provider=provider,
        model_id=model_config.api_model_id,
        call_type=call_type,
        input_tokens=meta["input_tokens"],
        output_tokens=meta["output_tokens"],
        usage_available=bool(meta["usage_available"]),
        error_kind=result.error_kind,
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


def _metadata_for_result(
    result: CompletionResult, provider: str
) -> dict[str, Any]:
    """Return provider metadata, or an unavailable record for unknown ones."""
    if provider == "anthropic":
        return _extract_anthropic_metadata(
            result.raw_response, result.raw_http
        )
    if provider in ("openai", "xai", "local"):
        return _extract_openai_metadata(
            result.raw_response, provider, result.raw_http
        )
    if provider == "google":
        return _extract_google_metadata(result.raw_response)
    return _empty_usage_meta()


def observe_token_usage(
    result: CompletionResult, provider: str
) -> tuple[bool, int | None, int | None]:
    """Return availability and token counts for the usage guard.

    A missing count makes the whole call unavailable. The counts are not
    coerced to zero.
    """
    meta = _metadata_for_result(result, provider)
    input_tokens = meta["input_tokens"]
    output_tokens = meta["output_tokens"]
    if (
        not meta["usage_available"]
        or not isinstance(input_tokens, int)
        or isinstance(input_tokens, bool)
        or not isinstance(output_tokens, int)
        or isinstance(output_tokens, bool)
    ):
        return False, None, None
    return True, input_tokens, output_tokens


class BudgetedApiClient:
    """Choke point that checks the usage budget before every provider call.

    Retries and direct calls such as memory updates both go through
    ``get_completion``, so they share this check. The wrapped client is
    not called when the next call would exceed a configured limit.
    """

    def __init__(
        self,
        inner: ApiClientProtocol,
        guard: UsageBudgetGuard,
        provider: str,
    ) -> None:
        self._inner = inner
        self._guard = guard
        self._provider = provider

    def get_completion(
        self,
        messages: list[ChatMessage],
        *,
        use_cache_control: bool = True,
    ) -> CompletionResult:
        """Check the budget, then forward the call and record its usage."""
        self._guard.before_call()
        try:
            result = self._inner.get_completion(
                messages, use_cache_control=use_cache_control
            )
        except UsageBudgetExceeded:
            raise
        except Exception:
            logger.warning(
                "Provider client raised for %s; counting the attempt "
                "as unavailable usage",
                self._provider,
                exc_info=True,
            )
            self._guard.after_call(
                usage_available=False,
                input_tokens=None,
                output_tokens=None,
            )
            raise
        try:
            available, input_tokens, output_tokens = observe_token_usage(
                result, self._provider
            )
        except Exception:
            logger.warning(
                "Could not read usage for provider %s; treating it as "
                "unavailable",
                self._provider,
                exc_info=True,
            )
            available = False
            input_tokens = None
            output_tokens = None
        self._guard.after_call(
            usage_available=available,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        return result
