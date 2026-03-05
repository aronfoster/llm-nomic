"""Shared retry loop helper for LLM-powered player and judge actions."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable, TypeVar

from ..data_models import ChatMessage, CompletionResult

if TYPE_CHECKING:
    from .api_clients import ApiClientProtocol

logger = logging.getLogger(__name__)

T = TypeVar("T")


def llm_retry_loop(
    *,
    history: list[ChatMessage],
    api_client: "ApiClientProtocol",
    parse_fn: Callable[[str], T],
    max_retries: int,
    retry_template: str,
    actor_label: str,
    action_description: str,
    log_usage: Callable[[CompletionResult], None] | None = None,
    secondary_append: list[ChatMessage] | None = None,
) -> T:
    """Run a retry loop for an LLM action.

    Prints a status message before each API call, handles None responses,
    and attempts to parse the response. On success, appends the assistant
    ChatMessage to history (and to secondary_append if provided) and returns
    the parsed result. On exhaustion, raises RuntimeError.

    Args:
        history: Conversation history list. Modified in-place: on each retry
            the bad response and a retry prompt are appended; on success the
            successful assistant message is appended.
        api_client: The LLM API client to use.
        parse_fn: Callable that parses a response string. Must raise
            ValueError on invalid input.
        max_retries: Maximum number of attempts.
        retry_template: Template string for retry messages. Must contain
            a ``{validation_error}`` placeholder that will be formatted with
            the string representation of the caught ValueError.
        actor_label: Display label for the actor (printed before each call).
        action_description: Short description of what the actor is doing
            (e.g. ``"thinking about a proposal"``).
        log_usage: Optional callable invoked with the CompletionResult
            immediately after each API call (for token usage logging).
        secondary_append: Optional list to which the successful assistant
            ChatMessage is also appended. Used by LLMJudge to track
            per-turn responses separately from the full turn history.
            Retried or rejected responses are never added to this list.

    Returns:
        The value returned by ``parse_fn`` on the first successful attempt.

    Raises:
        RuntimeError: When all retry attempts are exhausted without a
            successful parse.
    """
    for attempt in range(max_retries):
        print(f"\n{actor_label} is {action_description}...")

        result = api_client.get_completion(history)
        if log_usage is not None:
            log_usage(result)
        response_text = result.text

        if response_text is None:
            logger.error(
                "%s: API error on attempt %d/%d",
                actor_label,
                attempt + 1,
                max_retries,
            )
            continue

        logger.info(
            "Raw LLM response from %s:\n%s", actor_label, response_text
        )

        try:
            parsed = parse_fn(response_text)

            assistant_msg = ChatMessage(
                role="assistant", content=response_text
            )
            history.append(assistant_msg)
            if secondary_append is not None:
                secondary_append.append(assistant_msg)

            return parsed

        except ValueError as e:
            logger.warning(
                "%s: Invalid response on attempt %d/%d. Error: %s",
                actor_label,
                attempt + 1,
                max_retries,
                e,
            )

            if attempt >= max_retries - 1:
                break

            history.append(
                ChatMessage(role="assistant", content=response_text)
            )
            retry_msg = retry_template.format(validation_error=str(e))
            history.append(ChatMessage(role="user", content=retry_msg))

    raise RuntimeError(
        f"LLM failed to complete '{action_description}' after "
        f"{max_retries} attempts."
    )
