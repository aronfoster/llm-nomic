"""Abstract base class for judge implementations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..core.game_manager import GameManager
    from ..data_models import Discussion, Proposal, Vote
    from ..players.base_player import BasePlayer


class BaseJudge(ABC):
    """Common interface for all judge strategies."""

    @abstractmethod
    def get_veto(
        self,
        game_manager: "GameManager",
        proposal: "Proposal",
        votes: list["Vote"],
        discussions: list["Discussion"],
    ) -> bool:
        """Return whether the judge vetoes the current proposal."""

    @abstractmethod
    def assess_scores(
        self,
        game_manager: "GameManager",
        players: list["BasePlayer"],
        proposal: "Proposal",
        votes: list["Vote"],
        discussions: list["Discussion"],
    ) -> None:
        """Allow the judge to update scores for the current turn."""
