"""Token usage logger for recording LLM API call metadata."""

from __future__ import annotations

import logging
from pathlib import Path

from ..data_models import TokenUsageRecord

logger = logging.getLogger(__name__)


class TokenUsageLogger:
    """Appends structured token usage records to token_usage.jsonl.

    Responsibilities:
    - Accept a completed TokenUsageRecord and append it to the log file
      via record.model_dump_json().
    - Never raise. All write failures log a WARNING and continue.
    - Does not interpret or extract data from raw API responses; that
      responsibility belongs to the call site (in each API client).
    - Does not enforce a budget. UsageBudgetGuard reads this file and
      stops before a later call. A missing count is stored as null
      (usage_available false), not as zero.
    """

    def __init__(self, log_path: Path) -> None:
        """Initialize the logger.

        Args:
            log_path: Path to the token_usage.jsonl file.
        """
        self._log_path = log_path

    def log(self, record: TokenUsageRecord) -> None:
        """Append a TokenUsageRecord as a JSON line. Never raises.

        Args:
            record: The completed token usage record to persist.
        """
        try:
            with self._log_path.open("a", encoding="utf-8") as f:
                f.write(record.model_dump_json())
                f.write("\n")
        except Exception as exc:
            logger.warning(
                "Failed to write token usage record to %s: %s",
                self._log_path,
                exc,
            )
