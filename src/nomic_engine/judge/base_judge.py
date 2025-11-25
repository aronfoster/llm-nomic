"""Abstract base class for judge implementations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from ..core.game_manager import GameManager
    from ..data_models import Discussion, Proposal, Vote
    from ..players.base_player import BasePlayer


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


class BaseJudge(ABC):
    """Common interface for all judge strategies."""

    @abstractmethod
    def get_veto(
        self,
        game_manager: "GameManager",
        proposal: "Proposal",
        votes: list["Vote"],
        discussions: list["Discussion"],
    ) -> JudgeVetoResponse:
        """Return whether the judge vetoes the current proposal."""

    @abstractmethod
    def assess_scores(
        self,
        game_manager: "GameManager",
        players: list["BasePlayer"],
        proposal: "Proposal",
        votes: list["Vote"],
        discussions: list["Discussion"],
    ) -> JudgeScoreResponse:
        """Allow the judge to update scores for the current turn."""
