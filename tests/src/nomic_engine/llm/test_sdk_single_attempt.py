"""One guarded provider call must make one HTTP attempt.

These tests use httpx.MockTransport against the real SDK clients. If a
client kept the SDK's default retries, a 500, 429, or timeout would
show up as more than one request while the usage guard still counted
one call. No live network is used.
"""

from __future__ import annotations

import httpx
import pytest

from src.nomic_engine.data_models import ChatMessage, ModelDefinition
from src.nomic_engine.llm.api_clients import (
    AnthropicApiClient,
    BudgetedApiClient,
    GoogleApiClient,
    OpenAICompatibleApiClient,
)
from src.nomic_engine.usage_budget import UsageBudget, UsageBudgetGuard


def _model(provider: str) -> ModelDefinition:
    if provider == "local":
        return ModelDefinition(
            id="llama",
            provider="local",
            api_model_id="http://localhost:11434/v1",
            env_key_name=None,
        )
    if provider == "xai":
        return ModelDefinition(
            id="grok",
            provider="xai",
            api_model_id="grok-4",
            env_key_name="XAI_API_KEY",
        )
    if provider == "anthropic":
        return ModelDefinition(
            id="claude",
            provider="anthropic",
            api_model_id="claude-sonnet-4-5",
            env_key_name="ANTHROPIC_API_KEY",
        )
    if provider == "google":
        return ModelDefinition(
            id="gemini",
            provider="google",
            api_model_id="gemini-2.5-flash",
            env_key_name="GOOGLE_API_KEY",
        )
    return ModelDefinition(
        id="gpt-5-mini",
        provider="openai",
        api_model_id="gpt-5-mini",
        env_key_name="OPENAI_API_KEY",
    )


def _handler(failure: str, seen: list[httpx.Request]) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("timed out", request=request)
        status = 500 if failure == "500" else 429
        host = request.url.host
        if host.endswith("anthropic.com"):
            body: dict[str, object] = {
                "type": "error",
                "error": {"type": "api_error", "message": failure},
            }
        elif host.endswith("googleapis.com"):
            body = {
                "error": {
                    "message": failure,
                    "code": status,
                    "status": "INTERNAL",
                }
            }
        else:
            body = {"error": {"message": failure, "type": "server_error"}}
        headers = {"retry-after": "0"} if status == 429 else None
        return httpx.Response(status, json=body, headers=headers)

    return httpx.MockTransport(handle)


@pytest.mark.parametrize(
    "provider", ["openai", "xai", "local", "anthropic", "google"]
)
@pytest.mark.parametrize("failure", ["500", "429", "timeout"])
def test_guarded_call_makes_one_http_attempt(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    failure: str,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("XAI_API_KEY", "test-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    seen: list[httpx.Request] = []
    http_client = httpx.Client(transport=_handler(failure, seen))
    model = _model(provider)
    if provider == "anthropic":
        inner: object = AnthropicApiClient(model, http_client=http_client)
    elif provider == "google":
        inner = GoogleApiClient(model, http_client=http_client)
    else:
        inner = OpenAICompatibleApiClient(model, http_client=http_client)
    guard = UsageBudgetGuard(UsageBudget(max_calls_per_game=1))
    wrapped = BudgetedApiClient(inner, guard, model.provider)  # type: ignore[arg-type]
    try:
        result = wrapped.get_completion(
            [ChatMessage(role="user", content="hi")]
        )
    finally:
        http_client.close()

    assert len(seen) == 1
    assert guard.calls == 1
    assert result.text is None
