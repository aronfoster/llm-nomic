"""Offline tests for the ChatGPT-plan Responses client (MockTransport)."""

from __future__ import annotations

import json
from typing import Any, Iterator

import httpx
import pytest

from src.nomic_engine.data_models import (
    ChatMessage,
    ModelDefinition,
    UsageBudget,
)
from src.nomic_engine.llm import api_clients
from src.nomic_engine.llm.chatgpt_plan_client import (
    PROVIDER,
    RESPONSES_URL,
    UNSUPPORTED_FIELDS,
    OpenAIChatGptPlanApiClient,
    build_request_body,
)
from src.nomic_engine.usage_budget import (
    LlmCallOptions,
    UsageBudgetExceeded,
    UsageBudgetGuard,
)

MODEL = ModelDefinition(
    id="chatgpt-plan",
    provider=PROVIDER,
    api_model_id="gpt-test",
    env_key_name=None,
)


def _sse(*events: dict[str, Any]) -> bytes:
    return b"".join(
        b"event: "
        + e["type"].encode()
        + b"\ndata: "
        + json.dumps(e).encode()
        + b"\n\n"
        for e in events
    )


def _completed(text: str = "hi", usage: Any = "default") -> bytes:
    if usage == "default":
        usage = {
            "input_tokens": 11,
            "output_tokens": 7,
            "output_tokens_details": {"reasoning_tokens": 3},
        }
    response: dict[str, Any] = {"id": "resp_1", "status": "completed"}
    if usage is not None:
        response["usage"] = usage
    return _sse(
        {"type": "response.created", "response": {"id": "resp_1"}},
        {"type": "response.output_text.delta", "delta": text[:1]},
        {"type": "response.output_text.delta", "delta": text[1:]},
        {"type": "response.completed", "response": response},
    )


class Tokens:
    def __init__(self) -> None:
        self.token = "tok-1"
        self.refreshes = 0

    def access_token(self) -> str:
        return self.token

    def force_refresh(self, rejected_token: str) -> str:
        assert rejected_token == self.token
        self.refreshes += 1
        self.token = f"tok-{self.refreshes + 1}"
        return self.token


class Server:
    def __init__(self, replies: list[httpx.Response]) -> None:
        self.replies: Iterator[httpx.Response] = iter(replies)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return next(self.replies)


def _client(
    server: Server, tokens: Tokens | None = None, **kw: Any
) -> OpenAIChatGptPlanApiClient:
    return OpenAIChatGptPlanApiClient(
        MODEL,
        tokens or Tokens(),
        http_client=httpx.Client(transport=httpx.MockTransport(server)),
        **kw,
    )


MESSAGES = [
    ChatMessage(role="system", content="You are a Nomic player."),
    ChatMessage(role="user", content="Propose a rule."),
    ChatMessage(role="assistant", content="Rule 1"),
    ChatMessage(role="user", content="Vote."),
]


def test_request_shape_is_the_documented_one() -> None:
    server = Server([httpx.Response(200, content=_completed())])
    result = _client(server).get_completion(MESSAGES)
    assert result.text == "hi" and result.error_kind is None
    request = server.requests[0]
    assert str(request.url) == RESPONSES_URL
    assert request.headers["authorization"] == "Bearer tok-1"
    body = json.loads(request.content)
    assert body["store"] is False and body["stream"] is True
    assert body["model"] == "gpt-test"
    assert body["instructions"] == "You are a Nomic player."
    assert [m["role"] for m in body["input"]] == [
        "user",
        "assistant",
        "user",
    ]
    assert not UNSUPPORTED_FIELDS.intersection(body)


def test_output_cap_is_not_sent() -> None:
    server = Server([httpx.Response(200, content=_completed())])
    _client(
        server, call_options=LlmCallOptions(max_output_tokens=50)
    ).get_completion(MESSAGES)
    assert "max_output_tokens" not in json.loads(server.requests[0].content)


def test_no_system_message_omits_instructions() -> None:
    body = build_request_body("m", [ChatMessage(role="user", content="x")])
    assert "instructions" not in body


def test_usage_from_response_completed_feeds_record_and_guard() -> None:
    server = Server([httpx.Response(200, content=_completed())])
    result = _client(server).get_completion(MESSAGES)
    available, i, o = api_clients.observe_token_usage(result, PROVIDER)
    assert (available, i, o) == (True, 11, 7)
    record = api_clients.build_token_usage_record(
        result, MODEL, "propose", 1, "P1"
    )
    assert record.reasoning_tokens == 3
    assert record.request_id == "resp_1"
    assert record.finish_reason == "completed"


def test_missing_usage_is_unavailable_not_zero() -> None:
    server = Server([httpx.Response(200, content=_completed(usage=None))])
    result = _client(server).get_completion(MESSAGES)
    assert api_clients.observe_token_usage(result, PROVIDER) == (
        False,
        None,
        None,
    )


def test_stream_without_completed_is_an_error() -> None:
    body = _sse({"type": "response.output_text.delta", "delta": "x"})
    server = Server([httpx.Response(200, content=body)])
    result = _client(server).get_completion(MESSAGES)
    assert result.text is None and result.error_kind == "api_error"


def test_401_refreshes_once_and_retries() -> None:
    tokens = Tokens()
    server = Server(
        [httpx.Response(401), httpx.Response(200, content=_completed())]
    )
    result = _client(server, tokens).get_completion(MESSAGES)
    assert result.text == "hi" and tokens.refreshes == 1
    assert server.requests[1].headers["authorization"] == "Bearer tok-2"


def test_second_401_gives_up() -> None:
    tokens = Tokens()
    server = Server([httpx.Response(401), httpx.Response(401)])
    result = _client(server, tokens).get_completion(MESSAGES)
    assert result.text is None and tokens.refreshes == 1
    assert len(server.requests) == 2


def test_plan_usage_limit_is_quota() -> None:
    err = {"error": {"code": "subscription_sharing_usage_limit_exceeded"}}
    server = Server([httpx.Response(429, json=err)])
    result = _client(server).get_completion(MESSAGES)
    assert result.error_kind == "quota"


def test_unsupported_capability_is_api_error() -> None:
    err = {"error": {"code": "subscription_sharing_unsupported_capability"}}
    server = Server([httpx.Response(400, json=err)])
    assert _client(server).get_completion(MESSAGES).error_kind == "api_error"


def test_response_failed_event_is_an_error() -> None:
    body = _sse(
        {
            "type": "response.failed",
            "response": {"error": {"code": "server_error"}},
        }
    )
    server = Server([httpx.Response(200, content=body)])
    assert _client(server).get_completion(MESSAGES).text is None


def test_factory_refuses_without_registered_sign_in() -> None:
    api_clients.clear_chatgpt_plan_token_provider()
    with pytest.raises(ValueError, match="ChatGPT sign-in"):
        api_clients.create_api_client(MODEL)


def test_factory_builds_budgeted_client_when_registered() -> None:
    api_clients.register_chatgpt_plan_token_provider(Tokens())
    try:
        guard = UsageBudgetGuard(UsageBudget(max_calls_per_game=1))
        client = api_clients.create_api_client(MODEL, usage_guard=guard)
        assert isinstance(client, api_clients.BudgetedApiClient)
        inner = client._inner
        assert isinstance(inner, OpenAIChatGptPlanApiClient)
        inner._http = httpx.Client(
            transport=httpx.MockTransport(
                Server([httpx.Response(200, content=_completed())])
            )
        )
        assert client.get_completion(MESSAGES).text == "hi"
        with pytest.raises(UsageBudgetExceeded):
            client.get_completion(MESSAGES)
    finally:
        api_clients.clear_chatgpt_plan_token_provider()


def test_wrong_provider_is_refused() -> None:
    other = MODEL.model_copy(update={"provider": "openai"})
    with pytest.raises(ValueError):
        OpenAIChatGptPlanApiClient(other, Tokens())
