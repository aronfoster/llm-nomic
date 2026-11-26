"""API client that spends a signed-in ChatGPT plan, not an API key.

Follows OpenAI's "Sign in with ChatGPT for open-source apps" inference
rules (https://developers.openai.com/siwc/token-sharing-open-source):

* ``POST https://api.openai.com/v1/responses`` with the OAuth access token
  as ``Authorization: Bearer``. No ChatGPT backend-api endpoint.
* Every request sets ``store: false`` and ``stream: true`` and is read as
  a server-sent event stream that must end in ``response.completed``.
* System messages go in ``instructions``; the rest go in ``input``.
* None of the documented unsupported fields are sent (no
  ``max_output_tokens``, ``temperature``, ``metadata``,
  ``previous_response_id`` and so on), so a game's ``max_output_tokens``
  cannot be enforced server-side here. The token budget still applies.
* Usage for the budget guard comes from ``response.completed``. A stream
  without it reports usage as unavailable, which stops a token-capped
  game.
* On HTTP 401 the token is refreshed once and the request retried once.

The client is opt-in: ``create_api_client`` builds it only for provider
``openai_chatgpt_plan`` and only after a token provider is registered.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Iterator, Protocol

import httpx

from ..data_models import ChatMessage, CompletionResult, ModelDefinition
from ..usage_budget import LlmCallOptions

logger = logging.getLogger(__name__)

PROVIDER = "openai_chatgpt_plan"
RESPONSES_URL = "https://api.openai.com/v1/responses"

# Documented as rejected on this route. Never sent.
UNSUPPORTED_FIELDS = frozenset(
    {
        "background",
        "conversation",
        "max_output_tokens",
        "max_tool_calls",
        "metadata",
        "moderation",
        "multi_agent",
        "prompt",
        "prompt_cache_retention",
        "safety_identifier",
        "temperature",
        "top_logprobs",
        "top_p",
        "truncation",
        "user",
        "previous_response_id",
    }
)


class AccessTokenProvider(Protocol):
    """What this client needs from the sign-in layer."""

    def access_token(self) -> str: ...

    def force_refresh(self, rejected_token: str) -> str: ...


class ChatGptPlanError(RuntimeError):
    """A Responses call failed. ``code`` is the documented error code."""

    def __init__(
        self, message: str, *, status_code: int | None, code: str | None
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


@dataclass
class ResponsesUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_tokens: int | None = None
    cached_tokens: int | None = None


@dataclass
class ResponsesResult:
    """The parts of ``response.completed`` the engine records."""

    id: str | None = None
    status: str | None = None
    incomplete_reason: str | None = None
    usage: ResponsesUsage | None = None
    text: str = ""
    events: list[str] = field(default_factory=list)


def build_request_body(
    model: str, messages: list[ChatMessage]
) -> dict[str, Any]:
    """Responses body: system prompt in ``instructions``, history in input."""
    system = [m.content for m in messages if m.role == "system"]
    rest = [
        {"role": m.role, "content": m.content}
        for m in messages
        if m.role != "system"
    ]
    body: dict[str, Any] = {
        "model": model,
        "input": rest,
        "store": False,
        "stream": True,
    }
    if system:
        body["instructions"] = "\n\n".join(system)
    bad = UNSUPPORTED_FIELDS.intersection(body)
    assert not bad, f"unsupported Responses fields: {sorted(bad)}"
    return body


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return int(value)


def _usage_from(payload: Any) -> ResponsesUsage | None:
    if not isinstance(payload, dict):
        return None
    out = ResponsesUsage(
        input_tokens=_int_or_none(payload.get("input_tokens")),
        output_tokens=_int_or_none(payload.get("output_tokens")),
    )
    details = payload.get("output_tokens_details")
    if isinstance(details, dict):
        out.reasoning_tokens = _int_or_none(details.get("reasoning_tokens"))
    cached = payload.get("input_tokens_details")
    if isinstance(cached, dict):
        out.cached_tokens = _int_or_none(cached.get("cached_tokens"))
    return out


def _sse_events(lines: Iterator[str]) -> Iterator[dict[str, Any]]:
    """Yield JSON ``data:`` payloads from a server-sent event stream."""
    data: list[str] = []
    for line in lines:
        if line == "":
            if data:
                joined = "\n".join(data)
                data = []
                if joined.strip() == "[DONE]":
                    return
                try:
                    event = json.loads(joined)
                except ValueError:
                    continue
                if isinstance(event, dict):
                    yield event
            continue
        if line.startswith("data:"):
            data.append(line[5:].lstrip())
    if data:
        try:
            event = json.loads("\n".join(data))
        except ValueError:
            return
        if isinstance(event, dict):
            yield event


def parse_stream(lines: Iterator[str]) -> ResponsesResult:
    """Collect text deltas and the final ``response.completed`` event."""
    result = ResponsesResult()
    parts: list[str] = []
    completed = False
    for event in _sse_events(lines):
        kind = str(event.get("type", ""))
        result.events.append(kind)
        if kind == "response.output_text.delta":
            delta = event.get("delta")
            if isinstance(delta, str):
                parts.append(delta)
        elif kind in ("response.completed", "response.incomplete"):
            response = event.get("response")
            if isinstance(response, dict):
                rid = response.get("id")
                result.id = rid if isinstance(rid, str) else None
                status = response.get("status")
                result.status = status if isinstance(status, str) else kind
                details = response.get("incomplete_details")
                if isinstance(details, dict):
                    reason = details.get("reason")
                    if isinstance(reason, str):
                        result.incomplete_reason = reason
                result.usage = _usage_from(response.get("usage"))
            completed = True
        elif kind in ("response.failed", "error"):
            response = event.get("response")
            err: Any = event.get("error")
            if isinstance(response, dict):
                err = response.get("error")
            code = err.get("code") if isinstance(err, dict) else None
            raise ChatGptPlanError(
                f"Response failed: {code or 'unknown_error'}",
                status_code=None,
                code=code if isinstance(code, str) else None,
            )
    if not completed:
        raise ChatGptPlanError(
            "Stream ended without response.completed",
            status_code=None,
            code="stream_incomplete",
        )
    result.text = "".join(parts)
    return result


def _error_from(response: httpx.Response) -> ChatGptPlanError:
    code: str | None = None
    try:
        payload = json.loads(response.read() or b"{}")
        err = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(err, dict) and isinstance(err.get("code"), str):
            code = err["code"]
    except ValueError:
        pass
    return ChatGptPlanError(
        f"Responses API returned HTTP {response.status_code} "
        f"({code or 'no code'})",
        status_code=response.status_code,
        code=code,
    )


class OpenAIChatGptPlanApiClient:
    """``ApiClientProtocol`` implementation for ChatGPT plan usage."""

    def __init__(
        self,
        model_config: ModelDefinition,
        token_provider: AccessTokenProvider,
        call_options: LlmCallOptions | None = None,
        *,
        http_client: httpx.Client | None = None,
        url: str = RESPONSES_URL,
    ) -> None:
        if model_config.provider != PROVIDER:
            raise ValueError(
                f"OpenAIChatGptPlanApiClient needs provider {PROVIDER!r}"
            )
        self.model_config = model_config
        self.model_id_for_api = model_config.api_model_id
        self._tokens = token_provider
        self._options = call_options or LlmCallOptions()
        self._http = http_client or httpx.Client()
        self._url = url
        if self._options.max_output_tokens is not None:
            logger.warning(
                "max_output_tokens=%s cannot be sent on the ChatGPT plan "
                "route; only the game's token and call budgets apply.",
                self._options.max_output_tokens,
            )

    def _post(self, token: str, body: dict[str, Any]) -> ResponsesResult | int:
        timeout = self._options.per_call_timeout_seconds
        with self._http.stream(
            "POST",
            self._url,
            json=body,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "text/event-stream",
            },
            timeout=(
                timeout if timeout is not None else httpx.USE_CLIENT_DEFAULT
            ),
        ) as response:
            if response.status_code == 401:
                response.read()
                return 401
            if response.status_code != 200:
                raise _error_from(response)
            return parse_stream(response.iter_lines())

    def get_completion(
        self, messages: list[ChatMessage], *, use_cache_control: bool = True
    ) -> CompletionResult:
        from .api_clients import _failed_result

        start = time.monotonic()
        body = build_request_body(self.model_id_for_api, messages)
        try:
            token = self._tokens.access_token()
            outcome = self._post(token, body)
            if outcome == 401:
                token = self._tokens.force_refresh(token)
                outcome = self._post(token, body)
                if outcome == 401:
                    raise ChatGptPlanError(
                        "Responses API rejected the refreshed token (401). "
                        "Run the login command again.",
                        status_code=401,
                        code="unauthorized",
                    )
            assert isinstance(outcome, ResponsesResult)
            return CompletionResult(
                text=outcome.text,
                raw_response=outcome,
                client_latency_ms=int((time.monotonic() - start) * 1000),
            )
        except Exception as exc:
            return _failed_result(
                provider=PROVIDER,
                exc=exc,
                started=start,
                timeout_seconds=self._options.per_call_timeout_seconds,
            )


def extract_metadata(
    raw_response: Any, empty: dict[str, Any]
) -> dict[str, Any]:
    """Token metadata for ``build_token_usage_record`` and the guard."""
    result = dict(empty)
    if not isinstance(raw_response, ResponsesResult):
        return result
    usage = raw_response.usage
    if (
        usage is not None
        and usage.input_tokens is not None
        and usage.output_tokens is not None
    ):
        result["usage_available"] = True
        result["input_tokens"] = usage.input_tokens
        result["output_tokens"] = usage.output_tokens
        result["reasoning_tokens"] = usage.reasoning_tokens
        result["cache_read_tokens"] = usage.cached_tokens
    if raw_response.incomplete_reason:
        result["finish_reason"] = raw_response.incomplete_reason
    elif raw_response.status:
        result["finish_reason"] = raw_response.status
    result["request_id"] = raw_response.id
    return result
