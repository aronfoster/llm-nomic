"""Unit tests for the llm_retry_loop shared helper."""

from unittest.mock import Mock

import pytest

from src.nomic_engine.data_models import ChatMessage, CompletionResult
from src.nomic_engine.llm.retry_helper import llm_retry_loop


def _make_api_client(*responses):
    """Return a mock API client yielding the given CompletionResult values."""
    client = Mock()
    client.get_completion.side_effect = list(responses)
    return client


def _completion(text):
    """Return a CompletionResult with the given text."""
    return CompletionResult(text=text, raw_response=None, client_latency_ms=0)


def _history():
    """Return a minimal history list."""
    return [ChatMessage(role="system", content="sys")]


TEMPLATE = "Error: {validation_error}\nRetry now."


# =====================================================================
# (a) Success on first attempt
# =====================================================================


def test_success_on_first_attempt():
    """Helper returns parsed result immediately when parse_fn succeeds."""
    parse_fn = Mock(return_value={"result": "ok"})
    history = _history()
    api_client = _make_api_client(_completion('{"result": "ok"}'))

    result = llm_retry_loop(
        history=history,
        api_client=api_client,
        parse_fn=parse_fn,
        max_retries=3,
        retry_template=TEMPLATE,
        actor_label="TestActor",
        action_description="doing something",
    )

    assert result == {"result": "ok"}
    assert api_client.get_completion.call_count == 1
    parse_fn.assert_called_once_with('{"result": "ok"}')
    # Successful assistant message appended to history
    assert history[-1].role == "assistant"
    assert history[-1].content == '{"result": "ok"}'


def test_success_appends_to_secondary():
    """On success, assistant message is appended to secondary_append list."""
    secondary = []
    history = _history()
    api_client = _make_api_client(_completion("good"))

    llm_retry_loop(
        history=history,
        api_client=api_client,
        parse_fn=Mock(return_value={"x": 1}),
        max_retries=2,
        retry_template=TEMPLATE,
        actor_label="Actor",
        action_description="action",
        secondary_append=secondary,
    )

    assert len(secondary) == 1
    assert secondary[0].role == "assistant"
    assert secondary[0].content == "good"


# =====================================================================
# (b) Failure then success (retry path)
# =====================================================================


def test_retry_on_parse_failure_then_success():
    """Helper retries when parse_fn raises ValueError, succeeds on next."""
    bad_text = "bad response"
    good_text = "good response"

    parse_fn = Mock(side_effect=[ValueError("invalid JSON"), {"result": "ok"}])
    api_client = _make_api_client(
        _completion(bad_text), _completion(good_text)
    )
    history = _history()

    result = llm_retry_loop(
        history=history,
        api_client=api_client,
        parse_fn=parse_fn,
        max_retries=3,
        retry_template=TEMPLATE,
        actor_label="Actor",
        action_description="action",
    )

    assert result == {"result": "ok"}
    assert api_client.get_completion.call_count == 2
    # History: [system, bad_assistant, retry_user, good_assistant]
    assert len(history) == 4
    assert history[1].role == "assistant"
    assert history[1].content == bad_text
    assert history[2].role == "user"
    assert "invalid JSON" in history[2].content
    assert history[3].role == "assistant"
    assert history[3].content == good_text


def test_retry_message_formats_validation_error():
    """Retry message contains the validation error from the ValueError."""
    parse_fn = Mock(
        side_effect=[ValueError("specific error detail"), {"x": 1}]
    )
    api_client = _make_api_client(_completion("bad"), _completion("good"))
    history = _history()

    llm_retry_loop(
        history=history,
        api_client=api_client,
        parse_fn=parse_fn,
        max_retries=3,
        retry_template=TEMPLATE,
        actor_label="Actor",
        action_description="action",
    )

    retry_user_msg = history[2]
    assert retry_user_msg.role == "user"
    assert "specific error detail" in retry_user_msg.content


def test_retry_does_not_append_to_secondary():
    """Retried/rejected responses are never added to secondary_append."""
    secondary = []
    good_text = "good"

    parse_fn = Mock(side_effect=[ValueError("bad"), {"x": 1}])
    api_client = _make_api_client(_completion("bad"), _completion(good_text))
    history = _history()

    llm_retry_loop(
        history=history,
        api_client=api_client,
        parse_fn=parse_fn,
        max_retries=3,
        retry_template=TEMPLATE,
        actor_label="Actor",
        action_description="action",
        secondary_append=secondary,
    )

    assert len(secondary) == 1
    assert secondary[0].content == good_text


# =====================================================================
# (c) Exhaustion with raise
# =====================================================================


def test_exhaustion_raises_runtime_error():
    """Helper raises RuntimeError when all retries are exhausted."""
    parse_fn = Mock(side_effect=ValueError("always bad"))
    api_client = _make_api_client(
        _completion("bad"),
        _completion("bad"),
        _completion("bad"),
    )
    history = _history()

    with pytest.raises(RuntimeError):
        llm_retry_loop(
            history=history,
            api_client=api_client,
            parse_fn=parse_fn,
            max_retries=3,
            retry_template=TEMPLATE,
            actor_label="Actor",
            action_description="action",
        )

    assert api_client.get_completion.call_count == 3
    assert parse_fn.call_count == 3


def test_exhaustion_call_count_matches_max_retries():
    """API is called exactly max_retries times on full exhaustion."""
    for max_retries in (1, 2, 5):
        parse_fn = Mock(side_effect=ValueError("bad"))
        responses = [_completion("bad")] * max_retries
        api_client = _make_api_client(*responses)

        with pytest.raises(RuntimeError):
            llm_retry_loop(
                history=_history(),
                api_client=api_client,
                parse_fn=parse_fn,
                max_retries=max_retries,
                retry_template=TEMPLATE,
                actor_label="Actor",
                action_description="action",
            )

        assert api_client.get_completion.call_count == max_retries


# =====================================================================
# (d) Exhaustion with graceful fallback return (caller catches)
# =====================================================================


def test_caller_can_catch_exhaustion_and_return_fallback():
    """Caller can catch RuntimeError and return a fallback value."""
    parse_fn = Mock(side_effect=ValueError("bad"))
    api_client = _make_api_client(_completion("bad"), _completion("bad"))

    fallback = {"vote": "ABSTAIN"}

    try:
        result = llm_retry_loop(
            history=_history(),
            api_client=api_client,
            parse_fn=parse_fn,
            max_retries=2,
            retry_template=TEMPLATE,
            actor_label="Actor",
            action_description="voting",
        )
    except RuntimeError:
        result = fallback

    assert result == fallback


# =====================================================================
# (e) None API response handling (skip and continue)
# =====================================================================


def test_none_response_skips_and_continues():
    """A None response is treated as an API error; loop continues to retry."""
    good_text = "good response"
    parse_fn = Mock(return_value={"ok": True})
    api_client = _make_api_client(
        _completion(None),
        _completion(good_text),
    )
    history = _history()

    result = llm_retry_loop(
        history=history,
        api_client=api_client,
        parse_fn=parse_fn,
        max_retries=3,
        retry_template=TEMPLATE,
        actor_label="Actor",
        action_description="action",
    )

    assert result == {"ok": True}
    assert api_client.get_completion.call_count == 2
    # None response must NOT be appended to history
    assert all(msg.content != "None" for msg in history)


def test_all_none_responses_raise():
    """When all API calls return None, RuntimeError is raised on exhaustion."""
    parse_fn = Mock()
    api_client = _make_api_client(
        _completion(None),
        _completion(None),
    )

    with pytest.raises(RuntimeError):
        llm_retry_loop(
            history=_history(),
            api_client=api_client,
            parse_fn=parse_fn,
            max_retries=2,
            retry_template=TEMPLATE,
            actor_label="Actor",
            action_description="action",
        )

    # parse_fn should never have been called (no text to parse)
    parse_fn.assert_not_called()


# =====================================================================
# Log usage callback
# =====================================================================


def test_log_usage_called_after_each_api_call():
    """log_usage callback is invoked once per API call."""
    logged = []
    parse_fn = Mock(side_effect=[ValueError("bad"), {"ok": True}])
    r1 = _completion("bad")
    r2 = _completion("good")
    api_client = _make_api_client(r1, r2)

    llm_retry_loop(
        history=_history(),
        api_client=api_client,
        parse_fn=parse_fn,
        max_retries=3,
        retry_template=TEMPLATE,
        actor_label="Actor",
        action_description="action",
        log_usage=logged.append,
    )

    assert len(logged) == 2
    assert logged[0] is r1
    assert logged[1] is r2


def test_log_usage_not_required():
    """Helper works correctly when log_usage is None (default)."""
    api_client = _make_api_client(_completion("good"))

    result = llm_retry_loop(
        history=_history(),
        api_client=api_client,
        parse_fn=Mock(return_value={"x": 1}),
        max_retries=2,
        retry_template=TEMPLATE,
        actor_label="Actor",
        action_description="action",
        log_usage=None,
    )

    assert result == {"x": 1}
