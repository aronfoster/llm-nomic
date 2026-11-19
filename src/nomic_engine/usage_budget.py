"""Fail-closed usage bounds and reports built on token_usage.jsonl.

The guard runs before every provider call. Configured limits default to
unlimited, which keeps existing games on their previous behavior. A token
limit is not exact: the call that crosses it can overshoot by up to
max_output_tokens plus that call's prompt, and a call with no usage
metadata is unknown rather than zero.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .data_models import UsageBudget

_TRUNCATED_FINISH_REASONS = frozenset(
    {"LENGTH", "MAX_TOKENS", "MAX_COMPLETION_TOKENS"}
)

_REPORT_NOTE = (
    "Unavailable usage is not counted as zero. "
    "max_total_tokens_per_game is not a precise token cap: "
    "one call can overshoot by up to max_output_tokens plus "
    "that call's prompt, and the engine stops before the next "
    "provider call."
)


class UsageBudgetExceeded(Exception):
    """Raised when the next provider call would break a configured limit.

    The call is not made. ``limit_name`` is the configured field that
    refused the call.
    """

    def __init__(self, message: str, *, limit_name: str) -> None:
        super().__init__(message)
        self.limit_name = limit_name


@dataclass(frozen=True)
class LlmCallOptions:
    """Per-call SDK options derived from a game's usage budget.

    Both fields default to None. None leaves the provider client's
    historical parameters unchanged.
    """

    per_call_timeout_seconds: float | None = None
    max_output_tokens: int | None = None


def call_options_for(budget: object) -> LlmCallOptions:
    """Return SDK options for a real UsageBudget, else unlimited options."""
    if not isinstance(budget, UsageBudget):
        return LlmCallOptions()
    return LlmCallOptions(
        per_call_timeout_seconds=budget.per_call_timeout_seconds,
        max_output_tokens=budget.max_output_tokens,
    )


@dataclass
class UsageSummary:
    """Known token totals plus calls whose usage cannot be trusted.

    ``input_tokens`` and ``output_tokens`` sum only calls with provider
    usage metadata. Calls with unavailable usage are counted separately
    and are not added as zero.
    """

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    calls_with_unavailable_usage: int = 0
    calls_with_zero_tokens: int = 0
    calls_truncated: int = 0
    calls_quota: int = 0
    calls_timeout: int = 0
    unparsed_lines: int = 0

    @property
    def total_tokens(self) -> int:
        """Sum of known input and output tokens."""
        return self.input_tokens + self.output_tokens


def is_truncated_finish_reason(finish_reason: str | None) -> bool:
    """Return True when the provider stopped because the output was cut."""
    if finish_reason is None:
        return False
    normalized = finish_reason.strip().upper()
    if normalized.startswith("FINISHREASON."):
        normalized = normalized.split(".", 1)[1]
    return normalized in _TRUNCATED_FINISH_REASONS


def _known_tokens(row: dict[str, Any]) -> tuple[bool, int, int]:
    """Return whether a log row has usable input and output counts.

    ``usage_available: false`` is unknown even if the numeric fields are
    present. Legacy rows written before that flag existed stored missing
    usage as zero, so a missing flag trusts the integers.
    """
    flag = row.get("usage_available", None)
    if flag is False:
        return False, 0, 0
    raw_input = row.get("input_tokens")
    raw_output = row.get("output_tokens")
    if not isinstance(raw_input, int) or isinstance(raw_input, bool):
        return False, 0, 0
    if not isinstance(raw_output, int) or isinstance(raw_output, bool):
        return False, 0, 0
    return True, raw_input, raw_output


def _add_row(summary: UsageSummary, row: dict[str, Any]) -> None:
    summary.calls += 1
    known, input_tokens, output_tokens = _known_tokens(row)
    if not known:
        summary.calls_with_unavailable_usage += 1
    else:
        summary.input_tokens += input_tokens
        summary.output_tokens += output_tokens
        if input_tokens + output_tokens == 0:
            summary.calls_with_zero_tokens += 1
    finish_reason = row.get("finish_reason")
    if isinstance(finish_reason, str) and is_truncated_finish_reason(
        finish_reason
    ):
        summary.calls_truncated += 1
    error_kind = row.get("error_kind")
    if error_kind == "quota":
        summary.calls_quota += 1
    elif error_kind == "timeout":
        summary.calls_timeout += 1


def summarize_token_usage_log(
    log_path: Path,
) -> tuple[dict[int, UsageSummary], UsageSummary]:
    """Summarize token_usage.jsonl by turn and for the whole game.

    Blank lines are ignored. A line that is not a JSON object counts as
    one call with unavailable usage so a corrupt log cannot look empty.
    """
    per_turn: dict[int, UsageSummary] = {}
    game = UsageSummary()
    if not log_path.is_file():
        return per_turn, game
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            game.calls += 1
            game.calls_with_unavailable_usage += 1
            game.unparsed_lines += 1
            continue
        if not isinstance(row, dict):
            game.calls += 1
            game.calls_with_unavailable_usage += 1
            game.unparsed_lines += 1
            continue
        _add_row(game, row)
        move_number = row.get("move_number")
        if isinstance(move_number, int) and not isinstance(move_number, bool):
            bucket = per_turn.setdefault(move_number, UsageSummary())
            _add_row(bucket, row)
    return per_turn, game


def _format_turn_counts(summary: UsageSummary) -> str:
    return (
        f"calls={summary.calls} "
        f"input_tokens={summary.input_tokens} "
        f"output_tokens={summary.output_tokens} "
        f"total_tokens={summary.total_tokens} "
        f"unavailable={summary.calls_with_unavailable_usage} "
        f"zero_tokens={summary.calls_with_zero_tokens} "
        f"truncated={summary.calls_truncated}"
    )


def format_usage_report(log_path: Path | None) -> str:
    """Render a per-turn and per-game usage report from token_usage.jsonl."""
    missing_log = log_path is None or not log_path.is_file()
    if log_path is None or missing_log:
        per_turn: dict[int, UsageSummary] = {}
        game = UsageSummary()
    else:
        per_turn, game = summarize_token_usage_log(log_path)
    lines = [
        "Usage summary (game):",
        f"  calls: {game.calls}",
        f"  input_tokens: {game.input_tokens}",
        f"  output_tokens: {game.output_tokens}",
        f"  total_tokens: {game.total_tokens}",
        (
            "  calls_with_unavailable_usage: "
            f"{game.calls_with_unavailable_usage}"
        ),
        f"  calls_with_zero_tokens: {game.calls_with_zero_tokens}",
        f"  calls_truncated: {game.calls_truncated}",
        f"  calls_quota: {game.calls_quota}",
        f"  calls_timeout: {game.calls_timeout}",
        f"  unparsed_lines: {game.unparsed_lines}",
        "Usage by turn:",
    ]
    if not per_turn:
        lines.append("  (no calls recorded)")
    else:
        for move_number in sorted(per_turn):
            lines.append(
                f"  move {move_number}: "
                f"{_format_turn_counts(per_turn[move_number])}"
            )
    if missing_log:
        lines.append("No token_usage.jsonl was found.")
    lines.append(_REPORT_NOTE)
    return "\n".join(lines)


@dataclass
class UsageBudgetGuard:
    """In-memory budget checked before every provider call.

    Call and token totals are seeded from token_usage.jsonl when a log
    path is supplied, so a restarted process does not forget calls that
    already happened. ``max_wall_seconds`` is measured from construction
    of this guard (one process), not from the first line of the log.

    Within a process the guard counts a call even if the jsonl append
    fails. The logger still never raises. A failed append can under-count
    only after a later restart.
    """

    budget: UsageBudget
    clock: Callable[[], float] = field(default=time.monotonic, repr=False)
    log_path: Path | None = None
    calls: int = 0
    known_input_tokens: int = 0
    known_output_tokens: int = 0
    unavailable_calls: int = 0
    zero_token_calls: int = 0
    _block_reason: str | None = field(default=None, init=False, repr=False)
    _started_at: float = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._started_at = self.clock()
        if self.log_path is not None and self.log_path.is_file():
            self._restore_from_log(self.log_path)

    @property
    def known_total_tokens(self) -> int:
        """Known input plus output tokens. Excludes unavailable calls."""
        return self.known_input_tokens + self.known_output_tokens

    def before_call(self) -> None:
        """Refuse the call when a configured limit is already exhausted.

        Raises:
            UsageBudgetExceeded: The provider call must not be made.
        """
        call_limit = self.budget.max_calls_per_game
        if call_limit is not None and self.calls >= call_limit:
            raise UsageBudgetExceeded(
                (
                    "Usage budget exceeded: "
                    f"max_calls_per_game={call_limit} already used "
                    f"({self.calls} calls, including retries, timeouts, "
                    "and quota errors). Refusing the next provider call."
                ),
                limit_name="max_calls_per_game",
            )
        wall_limit = self.budget.max_wall_seconds
        if wall_limit is not None:
            elapsed = self.clock() - self._started_at
            if elapsed >= wall_limit:
                raise UsageBudgetExceeded(
                    (
                        "Usage budget exceeded: "
                        f"max_wall_seconds={wall_limit} already elapsed "
                        f"({elapsed:.3f}s). Refusing the next provider "
                        "call. A call already in flight is bounded only "
                        "by per_call_timeout_seconds, when that is set."
                    ),
                    limit_name="max_wall_seconds",
                )
        if self._block_reason is not None:
            raise UsageBudgetExceeded(
                self._block_reason,
                limit_name="max_total_tokens_per_game",
            )
        token_limit = self.budget.max_total_tokens_per_game
        if token_limit is not None and self.known_total_tokens >= token_limit:
            raise UsageBudgetExceeded(
                (
                    "Usage budget exceeded: known input+output tokens "
                    f"{self.known_total_tokens} >= "
                    f"max_total_tokens_per_game={token_limit}. "
                    "Refusing the next provider call. This is not a "
                    "precise token cap: the call that crossed the limit "
                    "can overshoot by up to max_output_tokens plus that "
                    "call's prompt."
                ),
                limit_name="max_total_tokens_per_game",
            )

    def after_call(
        self,
        *,
        usage_available: bool,
        input_tokens: int | None,
        output_tokens: int | None,
    ) -> None:
        """Record a call that was actually sent to a provider.

        Unavailable, missing, or negative counts are unknown. When a
        token cap is configured, that unknown stops the next call.
        """
        self.calls += 1
        if (
            not usage_available
            or input_tokens is None
            or output_tokens is None
            or input_tokens < 0
            or output_tokens < 0
        ):
            self.unavailable_calls += 1
            if self.budget.max_total_tokens_per_game is not None:
                self._block_reason = self._unavailable_usage_message()
            return
        self.known_input_tokens += input_tokens
        self.known_output_tokens += output_tokens
        if input_tokens + output_tokens == 0:
            self.zero_token_calls += 1

    def _unavailable_usage_message(self) -> str:
        limit = self.budget.max_total_tokens_per_game
        return (
            "Usage budget exceeded: "
            f"max_total_tokens_per_game={limit} is set, but a previous "
            "call did not return usage metadata. That call is "
            "unavailable, not zero. Refusing the next provider call. "
            "A token cap cannot be enforced precisely when usage is "
            "missing."
        )

    def _restore_from_log(self, log_path: Path) -> None:
        _per_turn, game = summarize_token_usage_log(log_path)
        self.calls = game.calls
        self.known_input_tokens = game.input_tokens
        self.known_output_tokens = game.output_tokens
        self.unavailable_calls = game.calls_with_unavailable_usage
        self.zero_token_calls = game.calls_with_zero_tokens
        if (
            self.budget.max_total_tokens_per_game is not None
            and game.calls_with_unavailable_usage > 0
        ):
            self._block_reason = self._unavailable_usage_message()


def real_usage_guard(guard: object) -> UsageBudgetGuard | None:
    """Return ``guard`` when it is a UsageBudgetGuard, else None."""
    if isinstance(guard, UsageBudgetGuard):
        return guard
    return None
