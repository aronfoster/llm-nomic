"""Abstract base class for judge implementations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, TypedDict

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


class StateUpdates(TypedDict, total=False):
    """Container for updates the Judge wants to apply to GameState."""

    flags: dict[str, Any]
    target_score: int | None


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

    @abstractmethod
    def maintain_state(
        self,
        game_manager: "GameManager",
        proposal: "Proposal",
        original_rule_text: str | None,
        new_rule_text: str | None,
    ) -> StateUpdates:
        """
        Update GameState when rule changes require engine configuration
        changes.

        Called after vote passes and judge doesn't veto, before applying
        proposal to rules. NOT called for TRANSMUTE proposals (status
        changes don't affect engine state).

        Args:
            game_manager: The game manager instance
            proposal: The passed proposal being applied
            original_rule_text: The text of the rule being changed (None
                for ADD)
            new_rule_text: The new text being added/amended (None for
                REPEAL)

        Returns:
            StateUpdates dict with flags and/or target_score changes, or
            {} if no changes needed
        """
