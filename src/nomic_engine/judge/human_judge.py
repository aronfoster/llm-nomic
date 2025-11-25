"""Human judge interaction logic implemented as a strategy class."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .base_judge import BaseJudge

if TYPE_CHECKING:
    from ..core.game_manager import GameManager
    from ..players.base_player import BasePlayer

logger = logging.getLogger(__name__)


class HumanJudge(BaseJudge):
    """Human-driven judge that prompts for decisions via stdin."""

    def get_veto(self) -> bool:
        """Prompt the human judge (Arbiter) for a veto decision."""

        judge_response = (
            input("\nJudge (Arbiter), do you VETO this outcome? (y/n): ")
            .strip()
            .lower()
        )
        judge_vetoed = judge_response == "y"
        return judge_vetoed

    def assess_scores(
        self, game_manager: "GameManager", players: list["BasePlayer"]
    ) -> None:
        """Prompt the Judge to assign point changes for each player."""

        assert game_manager.game_state is not None
        assert game_manager.rules_manager is not None

        point_rules = [
            r
            for r in game_manager.rules_manager.rules
            if "point" in r.text.lower()
        ]

        print(
            f"\n--- Judge (Scorer), please assess points for Move "
            f"#{game_manager.game_state.move_number} ---"
        )

        print("\nRelevant Point-Scoring Rules:")
        for rule in point_rules:
            status_char = rule.status.value[0].upper()
            print(f"Rule {rule.rule_id} ({status_char}): {rule.text}")

        print()

        for player in players:
            while True:
                try:
                    points_input = input(
                        f"Enter point change for {player.player_name}: "
                    )
                    points_change = int(points_input)
                    break
                except ValueError:
                    print("Invalid input. Please enter an integer.")
                    continue

            game_manager.game_state.scores[player.player_name] += points_change
            logger.debug(
                f"Applied {points_change} points to {player.player_name}"
            )
