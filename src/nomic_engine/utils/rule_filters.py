"""Utility functions for filtering rules based on specific criteria."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..data_models import Rule


def filter_scoring_rules(rules: list[Rule]) -> list[Rule]:
    """
    Return only rules whose text contains 'point' or 'score'.

    This utility is used by judges to filter the ruleset to only
    scoring-relevant rules when assessing points for a turn.

    Args:
        rules: List of Rule objects to filter

    Returns:
        List of Rule objects whose text contains 'point' or 'score'
        (case-insensitive)
    """
    return [
        r
        for r in rules
        if "point" in r.text.lower() or "score" in r.text.lower()
    ]
