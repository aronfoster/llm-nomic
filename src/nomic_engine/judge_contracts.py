"""Shared TypedDict contracts for judge interactions."""

from __future__ import annotations

from typing import Any

from typing_extensions import TypedDict


class JudgeVetoResponse(TypedDict):
    """Standard structure for judge veto decisions."""

    veto: bool
    reason: str | None
    private_thoughts: str | None


class ScoreAdjustment(TypedDict):
    """Represents a single player score adjustment."""

    player: str
    delta: int
    reason: str


class JudgeScoreResponse(TypedDict):
    """Standard structure for judge score assessments."""

    private_thoughts: str | None
    score_adjustments: list[ScoreAdjustment]


class StateUpdates(TypedDict, total=False):
    """Container for updates the Judge wants to apply to GameState."""

    flags: dict[str, Any]
    target_score: int | None
