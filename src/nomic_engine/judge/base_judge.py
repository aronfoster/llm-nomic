"""Abstract base class for judge implementations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..core.game_manager import GameManager
    from ..players.base_player import BasePlayer


class BaseJudge(ABC):
    """Common interface for all judge strategies."""

    @abstractmethod
    def get_veto(self) -> bool:
        """Return whether the judge vetoes the current proposal."""

    @abstractmethod
    def assess_scores(
        self, game_manager: "GameManager", players: list["BasePlayer"]
    ) -> None:
        """Allow the judge to update scores for the current turn."""
