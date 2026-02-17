"""Human judge interaction logic implemented as a strategy class."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..judge_contracts import (
    JudgeScoreResponse,
    JudgeVetoResponse,
    ScoreAdjustment,
    StateUpdates,
)
from ..utils.rule_filters import filter_scoring_rules
from .base_judge import BaseJudge

if TYPE_CHECKING:
    from ..core.game_manager import GameManager
    from ..data_models import Discussion, Proposal, Vote
    from ..players.base_player import BasePlayer

logger = logging.getLogger(__name__)


class HumanJudge(BaseJudge):
    """Human-driven judge that prompts for decisions via stdin."""

    def get_veto(
        self,
        game_manager: "GameManager",
        proposal: "Proposal",
        votes: list["Vote"],
        discussions: list["Discussion"],
    ) -> JudgeVetoResponse:
        """Prompt the human judge (Arbiter) for a veto decision."""

        judge_response = (
            input("\nJudge (Arbiter), do you VETO this outcome? (y/n): ")
            .strip()
            .lower()
        )
        judge_vetoed = judge_response == "y"
        logger.info(
            "Human judge veto decision for proposal %s: %s",
            proposal.proposal_id,
            "VETO" if judge_vetoed else "ALLOW",
        )
        return {
            "veto": judge_vetoed,
            "reason": "Manual decision by human judge.",
            "private_thoughts": None,
        }

    def assess_scores(
        self,
        game_manager: "GameManager",
        players: list["BasePlayer"],
        proposal: "Proposal",
        votes: list["Vote"],
        discussions: list["Discussion"],
        proposal_passed: bool,
    ) -> JudgeScoreResponse:
        """Prompt the Judge to assign point changes for each player."""

        assert game_manager.game_state is not None
        assert game_manager.rules_manager is not None

        point_rules = filter_scoring_rules(game_manager.rules_manager.rules)

        outcome_text = "PASSED" if proposal_passed else "FAILED"
        print(
            f"\n--- Judge (Scorer), please assess points for Move "
            f"#{game_manager.game_state.move_number} ---"
        )
        print(f"The proposal {outcome_text} the vote.\n")

        print("\nRelevant Point-Scoring Rules:")
        for rule in point_rules:
            status_char = rule.status.value[0].upper()
            print(f"Rule {rule.rule_id} ({status_char}): {rule.text}")

        print()

        adjustments: list[ScoreAdjustment] = []

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

            logger.info(
                "Human judge proposed %s %+d points",
                player.player_name,
                points_change,
            )
            adjustments.append(
                {
                    "player": player.player_name,
                    "delta": points_change,
                    "reason": "Manual score entry by human judge.",
                }
            )

        return {
            "private_thoughts": None,
            "score_adjustments": adjustments,
        }

    def maintain_state(
        self,
        game_manager: "GameManager",
        proposal: "Proposal",
        original_rule_text: str | None,
        new_rule_text: str | None,
    ) -> StateUpdates:
        """
        Interactive CLI to update GameState flags and target_score.

        Displays current state, prompts for changes, validates input.
        """
        from ..utils.flag_schema import (
            format_supported_flags,
            load_flag_schema,
            validate_flag_value,
        )

        assert game_manager.game_state is not None

        print(
            f"\n--- Judge (State Maintenance), review state for "
            f"proposal {proposal.proposal_id} ---"
        )
        print(f"\nProposal type: {proposal.type.value}")
        if original_rule_text:
            print(f"Original rule text: {original_rule_text}")
        if new_rule_text:
            print(f"New rule text: {new_rule_text}")

        # Display current state
        print("\n=== Current Game State ===")
        print(f"Target score: {game_manager.game_state.target_score}")
        print(f"Flags: {game_manager.game_state.flags}")

        # Display supported flags
        print("\n=== Supported Flags ===")
        print(format_supported_flags())

        # Collect changes
        state_updates: StateUpdates = {}
        schema = load_flag_schema()

        # Prompt for target_score
        print("\n--- Target Score ---")
        print(
            f"Current: {game_manager.game_state.target_score} "
            "(Press Enter to keep unchanged)"
        )
        while True:
            target_input = input(
                "New target_score (or Enter to skip): "
            ).strip()
            if not target_input:
                break
            if target_input.lower() == "none":
                # Only add if different from current
                if game_manager.game_state.target_score is not None:
                    state_updates["target_score"] = None
                    logger.info("Human judge set target_score to None")
                break
            try:
                target_value = int(target_input)
                # Only add if different from current
                if target_value != game_manager.game_state.target_score:
                    state_updates["target_score"] = target_value
                    logger.info(
                        "Human judge changed target_score to %d", target_value
                    )
                break
            except ValueError:
                print(
                    "Invalid input. Enter an integer, 'none', or press "
                    "Enter."
                )

        # Prompt for each flag
        print("\n--- Flags ---")
        flag_updates = {}
        for flag_name, definition in sorted(schema.items()):
            current_value = game_manager.game_state.flags.get(flag_name)
            valid_values = definition.get("valid_values")

            print(
                f"\n{flag_name} (current: {current_value}) "
                "(Press Enter to keep unchanged)"
            )
            if valid_values:
                print(f"  Valid values: {', '.join(map(str, valid_values))}")

            while True:
                flag_input = input(f"New value for {flag_name}: ").strip()
                if not flag_input:
                    break

                # Convert to appropriate type
                try:
                    flag_type = definition["type"]
                    parsed_value: int | bool | str
                    if flag_type == "integer":
                        parsed_value = int(flag_input)
                    elif flag_type == "boolean":
                        if flag_input.lower() in ("true", "1", "yes"):
                            parsed_value = True
                        elif flag_input.lower() in ("false", "0", "no"):
                            parsed_value = False
                        else:
                            print(
                                "Invalid boolean. Use true/false, yes/no, 1/0."
                            )
                            continue
                    else:  # string
                        parsed_value = flag_input

                    # Validate
                    validate_flag_value(flag_name, parsed_value)
                    # Only add if different from current
                    if parsed_value != current_value:
                        flag_updates[flag_name] = parsed_value
                        logger.info(
                            "Human judge changed flag %s to %s",
                            flag_name,
                            parsed_value,
                        )
                    break
                except ValueError as e:
                    print(f"Invalid input: {e}. Try again.")

        if flag_updates:
            state_updates["flags"] = flag_updates

        if state_updates:
            print(f"\nState updates: {state_updates}")
        else:
            print("\nNo state changes requested.")

        return state_updates
