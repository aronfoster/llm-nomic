"""Game API client that answers prompts through the opted-in grok CLI.

``GrokCliApiClient`` implements ``ApiClientProtocol`` on top of
``GrokCliProcessAdapter``. It is only reachable after a caller registers
a builder with ``register_grok_cli_client_builder``; ``create_api_client``
refuses ``provider="grok_cli"`` otherwise. Every failure is raised as a
typed ``GrokCliError``. There is no paid API fallback.
"""

from __future__ import annotations

import time

from ...data_models import ChatMessage, CompletionResult
from .grok_cli_adapter import GrokCliProcessAdapter

# One argv element is capped near 128 KiB on Linux. Stay well under it so
# a long game fails with a clear error, not an opaque spawn failure.
MAX_PROMPT_CHARS = 100_000

_ROLE_LABELS = {
    "system": "SYSTEM INSTRUCTIONS",
    "user": "USER",
    "assistant": "YOUR EARLIER REPLY",
}


class PromptTooLargeError(ValueError):
    """The rendered prompt would not fit in one CLI argument."""


def render_messages(messages: list[ChatMessage]) -> str:
    """Flatten a chat history into one prompt for ``grok -p``.

    The text always starts with a plain sentence, never a dash, so the
    CLI cannot read the prompt as an option.
    """
    parts = [
        "You are answering one step of a game. Follow the instructions in "
        "the last USER block exactly and reply with only what it asks for."
    ]
    for message in messages:
        label = _ROLE_LABELS.get(message.role, message.role.upper())
        parts.append(f"=== {label} ===\n{message.content}")
    prompt = "\n\n".join(parts)
    if len(prompt) > MAX_PROMPT_CHARS:
        raise PromptTooLargeError(
            f"prompt is {len(prompt)} characters; the grok CLI path "
            f"allows at most {MAX_PROMPT_CHARS}"
        )
    return prompt


class GrokCliApiClient:
    """One game actor's connection to the grok CLI."""

    def __init__(self, adapter: GrokCliProcessAdapter) -> None:
        self._adapter = adapter

    def get_completion(
        self, messages: list[ChatMessage], *, use_cache_control: bool = True
    ) -> CompletionResult:
        """Run one headless CLI prompt and return its text and usage."""
        prompt = render_messages(messages)
        started = time.monotonic()
        response = self._adapter.run(prompt)
        latency_ms = int((time.monotonic() - started) * 1000)
        return CompletionResult(
            text=response.text,
            raw_response=response,
            client_latency_ms=latency_ms,
        )
